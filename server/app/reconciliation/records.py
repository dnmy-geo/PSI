from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from io import BytesIO
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.pagination import paginate
from app.core.security import CurrentUser, get_current_user, has_permission, require_csrf, require_permission
from app.reconciliation import opening_import

AccountType = Literal["customer", "supplier", "processor"]
RecordType = Literal["receipt", "payment"]
SourceType = Literal["sales_order", "purchase_order", "outsourcing_order"]

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


class CashWrite(BaseModel):
    document_no: str = Field(min_length=1, max_length=80, pattern=r"\S")
    party_id: UUID
    account_type: AccountType
    record_type: RecordType
    document_date: date
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    source_type: SourceType | None = None
    source_id: UUID | None = None
    remark: str | None = None

    @model_validator(mode="after")
    def validate_account(self):
        if (self.account_type == "customer") != (self.record_type == "receipt"):
            raise ValueError("客户只能登记收款，供应商与加工商只能登记付款")
        if (self.source_type is None) != (self.source_id is None):
            raise ValueError("关联单据的类型与编号必须同时填写")
        expected = {"customer": "sales_order", "supplier": "purchase_order",
                    "processor": "outsourcing_order"}[self.account_type]
        if self.source_type is not None and self.source_type != expected:
            raise ValueError("关联单据的类型与账户类型不匹配")
        return self


class CashRead(CashWrite):
    id: UUID
    organization_id: UUID
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class OpeningWrite(BaseModel):
    party_id: UUID
    account_type: AccountType
    effective_date: date
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class OpeningRead(OpeningWrite):
    id: UUID
    organization_id: UUID
    direction: Literal["receivable", "payable"]
    created_at: datetime
    updated_at: datetime


def _permission(db: Session, user: CurrentUser,
                account_type: AccountType, action: str) -> None:
    menu = {"customer": "reconciliation.receipts",
            "supplier": "reconciliation.payments",
            "processor": "reconciliation.payments"}[account_type]
    if not has_permission(db, user, menu, action):
        raise HTTPException(status_code=403, detail="没有权限")


def _party(db: Session, org: UUID, party_id: UUID,
           account_type: AccountType) -> None:
    valid = db.execute(text("""
        SELECT 1 FROM parties p JOIN party_types t ON t.party_id = p.id
        WHERE p.id = :id AND p.organization_id = :org AND p.is_active
          AND t.party_type = :account_type
    """), {"id": party_id, "org": org,
           "account_type": account_type}).scalar_one_or_none()
    if not valid:
        raise HTTPException(status_code=422, detail="该往来单位不具备对应的身份")


def _source(db: Session, org: UUID, data: CashWrite) -> None:
    if data.source_type is None:
        return
    table, party_column = {
        "sales_order": ("sales_orders", "customer_id"),
        "purchase_order": ("purchase_orders", "supplier_id"),
        "outsourcing_order": ("outsourcing_orders", "processor_id"),
    }[data.source_type]
    valid = db.execute(text(f"""
        SELECT 1 FROM {table} WHERE id = :id AND organization_id = :org
          AND {party_column} = :party
    """), {"id": data.source_id, "org": org,
           "party": data.party_id}).scalar_one_or_none()
    if not valid:
        raise HTTPException(status_code=422, detail="关联单据与往来单位不匹配")


def _audit(db: Session, org: UUID, actor: UUID, action: str,
           doc_type: str, doc_id: UUID, reason: str | None = None) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, :action, :type, :id, :reason)
    """), {"org": org, "actor": actor, "action": action,
           "type": doc_type, "id": doc_id, "reason": reason})


def _cash(db: Session, org: UUID, doc_id: UUID, *, lock: bool = False) -> dict:
    row = db.execute(text("""
        SELECT id, organization_id, document_no, party_id, account_type,
               record_type, document_date, amount, source_type, source_id,
               remark, created_by, created_at, updated_at
        FROM cash_records WHERE id = :id AND organization_id = :org
    """ + (" FOR UPDATE" if lock else "")),
        {"id": doc_id, "org": org}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="收付款记录不存在")
    return dict(row)


def _opening(db: Session, org: UUID, doc_id: UUID, *, lock: bool = False) -> dict:
    row = db.execute(text("""
        SELECT id, organization_id, party_id, account_type, direction,
               effective_date, amount, created_at, updated_at
        FROM party_opening_balances WHERE id = :id AND organization_id = :org
    """ + (" FOR UPDATE" if lock else "")),
        {"id": doc_id, "org": org}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="期初往来余额不存在")
    return dict(row)


@router.get("/cash-records", response_model=list[CashRead])
def list_cash_records(response: Response,
                      account_type: AccountType,
                      party_id: UUID | None = None,
                      date_from: date | None = None,
                      date_to: date | None = None,
                      limit: int = Query(default=100, ge=1, le=500),
                      offset: int = Query(default=0, ge=0),
                      user: CurrentUser = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> list[dict]:
    _permission(db, user, account_type, "view")
    if date_from and date_to and date_to < date_from:
        raise HTTPException(status_code=422, detail="结束日期不能早于开始日期")
    query = """
        SELECT id, organization_id, document_no, party_id, account_type,
               record_type, document_date, amount, source_type, source_id,
               remark, created_by, created_at, updated_at
        FROM cash_records WHERE organization_id = :org AND account_type = :account
          AND (CAST(:party AS uuid) IS NULL OR party_id = :party)
          AND (CAST(:date_from AS date) IS NULL OR document_date >= :date_from)
          AND (CAST(:date_to AS date) IS NULL OR document_date <= :date_to)
        ORDER BY created_at DESC, document_no DESC
    """
    return paginate(db, query, {"org": user.organization_id, "account": account_type,
                                "party": party_id, "date_from": date_from,
                                "date_to": date_to},
                    limit=limit, offset=offset, response=response)


@router.get("/cash-records/{doc_id}", response_model=CashRead)
def get_cash_record(doc_id: UUID, user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> dict:
    result = _cash(db, user.organization_id, doc_id)
    _permission(db, user, result["account_type"], "view")
    return result


@router.post("/cash-records", response_model=CashRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_cash_record(payload: CashWrite,
                       user: CurrentUser = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> dict:
    _permission(db, user, payload.account_type, "create")
    _party(db, user.organization_id, payload.party_id, payload.account_type)
    _source(db, user.organization_id, payload)
    try:
        doc_id = db.execute(text("""
            INSERT INTO cash_records (organization_id, document_no, party_id,
                account_type, record_type, document_date, amount, source_type,
                source_id, remark, created_by)
            VALUES (:org, :number, :party, :account, :record_type, :date,
                    :amount, :source_type, :source_id, :remark, :actor)
            RETURNING id
        """), {"org": user.organization_id, "number": payload.document_no.strip(),
               "party": payload.party_id, "account": payload.account_type,
               "record_type": payload.record_type, "date": payload.document_date,
               "amount": payload.amount, "source_type": payload.source_type,
               "source_id": payload.source_id, "remark": payload.remark,
               "actor": user.id}).scalar_one()
        _audit(db, user.organization_id, user.id, "cash_record.create",
               "cash_record", doc_id)
        result = _cash(db, user.organization_id, doc_id)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="收付款单号已存在") from exc


@router.put("/cash-records/{doc_id}", response_model=CashRead,
            dependencies=[Depends(require_csrf)])
def update_cash_record(doc_id: UUID, payload: CashWrite,
                       user: CurrentUser = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> dict:
    current = _cash(db, user.organization_id, doc_id, lock=True)
    _permission(db, user, current["account_type"], "update")
    if current["account_type"] != payload.account_type:
        raise HTTPException(status_code=422, detail="账户类型不能修改")
    _party(db, user.organization_id, payload.party_id, payload.account_type)
    _source(db, user.organization_id, payload)
    try:
        db.execute(text("""
            UPDATE cash_records SET document_no = :number, party_id = :party,
                record_type = :record_type, document_date = :date,
                amount = :amount, source_type = :source_type,
                source_id = :source_id, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"id": doc_id, "org": user.organization_id,
               "number": payload.document_no.strip(), "party": payload.party_id,
               "record_type": payload.record_type, "date": payload.document_date,
               "amount": payload.amount, "source_type": payload.source_type,
               "source_id": payload.source_id, "remark": payload.remark})
        _audit(db, user.organization_id, user.id, "cash_record.update",
               "cash_record", doc_id)
        result = _cash(db, user.organization_id, doc_id)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="收付款单号已存在") from exc


@router.delete("/cash-records/{doc_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_cash_record(doc_id: UUID,
                       user: CurrentUser = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> None:
    current = _cash(db, user.organization_id, doc_id, lock=True)
    _permission(db, user, current["account_type"], "delete")
    db.execute(text("DELETE FROM cash_records WHERE id = :id AND organization_id = :org"),
               {"id": doc_id, "org": user.organization_id})
    _audit(db, user.organization_id, user.id, "cash_record.delete",
           "cash_record", doc_id)
    db.commit()


@router.get("/opening-balances/template")
def opening_balance_template(
    user: CurrentUser = Depends(require_permission("system.initialization", "view")),
) -> StreamingResponse:
    return StreamingResponse(BytesIO(opening_import.template_bytes()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="opening-balances-template.xlsx"'})


@router.post("/opening-balances/preview", dependencies=[Depends(require_csrf)])
def preview_opening_balances(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission("system.initialization", "view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = opening_import.prepare(db, user.organization_id, file.filename or "",
                                  file.file.read(opening_import.MAX_BYTES + 1))
    return [{key: value for key, value in row.items() if key != "party_id"} for row in rows]


@router.post("/opening-balances/import", dependencies=[Depends(require_csrf)])
def import_opening_balances(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission("system.initialization", "create")),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    rows = opening_import.prepare(db, user.organization_id, file.filename or "",
                                  file.file.read(opening_import.MAX_BYTES + 1))
    return {"imported": opening_import.import_rows(db, user.organization_id, user.id, rows)}


@router.get("/opening-balances", response_model=list[OpeningRead])
def list_opening_balances(response: Response,
                          account_type: AccountType | None = None,
                          party_id: UUID | None = None,
                          limit: int = Query(default=100, ge=1, le=500),
                          offset: int = Query(default=0, ge=0),
                          user: CurrentUser = Depends(require_permission("system.initialization", "view")),
                          db: Session = Depends(get_db)) -> list[dict]:
    query = """
        SELECT id, organization_id, party_id, account_type, direction,
               effective_date, amount, created_at, updated_at
        FROM party_opening_balances WHERE organization_id = :org
          AND (CAST(:account AS text) IS NULL OR account_type = :account)
          AND (CAST(:party AS uuid) IS NULL OR party_id = :party)
        ORDER BY created_at DESC, id DESC
    """
    return paginate(db, query, {"org": user.organization_id, "account": account_type,
                                "party": party_id},
                    limit=limit, offset=offset, response=response)


@router.post("/opening-balances", response_model=OpeningRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_opening_balance(payload: OpeningWrite,
                           user: CurrentUser = Depends(require_permission("system.initialization", "create")),
                           db: Session = Depends(get_db)) -> dict:
    _party(db, user.organization_id, payload.party_id, payload.account_type)
    try:
        doc_id = db.execute(text("""
            INSERT INTO party_opening_balances (organization_id, party_id,
                account_type, direction, effective_date, amount)
            VALUES (:org, :party, :account, :direction, :date, :amount)
            RETURNING id
        """), {"org": user.organization_id, "party": payload.party_id,
               "account": payload.account_type,
               "direction": "receivable" if payload.account_type == "customer" else "payable",
               "date": payload.effective_date, "amount": payload.amount}).scalar_one()
        _audit(db, user.organization_id, user.id, "opening_balance.create",
               "party_opening_balance", doc_id)
        result = _opening(db, user.organization_id, doc_id)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该往来单位在该日期已有期初余额") from exc


@router.put("/opening-balances/{doc_id}", response_model=OpeningRead,
            dependencies=[Depends(require_csrf)])
def update_opening_balance(doc_id: UUID, payload: OpeningWrite,
                           user: CurrentUser = Depends(require_permission("system.initialization", "update")),
                           db: Session = Depends(get_db)) -> dict:
    current = _opening(db, user.organization_id, doc_id, lock=True)
    if current["party_id"] != payload.party_id or current["account_type"] != payload.account_type:
        raise HTTPException(status_code=422, detail="期初往来余额的账户类型不能修改")
    _party(db, user.organization_id, payload.party_id, payload.account_type)
    try:
        db.execute(text("""
            UPDATE party_opening_balances SET effective_date = :date, amount = :amount
            WHERE id = :id AND organization_id = :org
        """), {"date": payload.effective_date, "amount": payload.amount,
               "id": doc_id, "org": user.organization_id})
        _audit(db, user.organization_id, user.id, "opening_balance.update",
               "party_opening_balance", doc_id)
        result = _opening(db, user.organization_id, doc_id)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该往来单位在该日期已有期初余额") from exc


@router.delete("/opening-balances/{doc_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_opening_balance(doc_id: UUID,
                           user: CurrentUser = Depends(require_permission("system.initialization", "delete")),
                           db: Session = Depends(get_db)) -> None:
    _opening(db, user.organization_id, doc_id, lock=True)
    db.execute(text("""
        DELETE FROM party_opening_balances WHERE id = :id AND organization_id = :org
    """), {"id": doc_id, "org": user.organization_id})
    _audit(db, user.organization_id, user.id, "opening_balance.delete",
           "party_opening_balance", doc_id)
    db.commit()
