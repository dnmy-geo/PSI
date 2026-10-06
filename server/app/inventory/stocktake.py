"""Warehouse stocktake, approval and difference posting."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.approval.workflow import start_approval
from app.core.db import get_db
from app.core.pagination import paginate
from app.core.document_numbers import next_document_number
from app.core.security import CurrentUser, require_csrf, require_permission
from app.inventory.posting import StockChange, post_stock_changes

router = APIRouter(prefix="/api/inventory/stocktakes", tags=["inventory"])


class StocktakeCreate(BaseModel):
    # 留空则由后端按 PD+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    document_date: date
    warehouse_id: UUID
    remark: str | None = None


class CountLineWrite(BaseModel):
    item_id: UUID
    counted_quantity_base: Decimal = Field(ge=0, max_digits=20, decimal_places=6)


class CountWrite(BaseModel):
    lines: list[CountLineWrite] = Field(min_length=1)


class CancelWrite(BaseModel):
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class StocktakeLineRead(BaseModel):
    id: UUID
    item_id: UUID
    book_quantity_base: Decimal
    counted_quantity_base: Decimal | None
    difference_quantity_base: Decimal | None


class StocktakeRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    document_date: date
    warehouse_id: UUID
    cutoff_at: datetime | None
    status: str
    remark: str | None
    lines: list[StocktakeLineRead]
    created_at: datetime
    updated_at: datetime


def _audit(db: Session, org: UUID, actor: UUID, action: str,
           doc_id: UUID, reason: str | None = None) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, :action, 'stocktake', :id, :reason)
    """), {"org": org, "actor": actor, "action": action,
           "id": doc_id, "reason": reason})


def get_stocktake(db: Session, org: UUID, doc_id: UUID, *, lock: bool = False) -> dict | None:
    row = db.execute(text("""
        SELECT id, organization_id, document_no, document_date, warehouse_id,
               cutoff_at, status, remark, created_at, updated_at
        FROM stocktakes WHERE id = :id AND organization_id = :org
    """ + (" FOR UPDATE" if lock else "")), {"id": doc_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = []
    for line in db.execute(text("""
        SELECT id, item_id, book_quantity_base, counted_quantity_base
        FROM stocktake_lines WHERE stocktake_id = :id ORDER BY sort_order, item_id
    """), {"id": doc_id}).mappings():
        item = dict(line)
        item["difference_quantity_base"] = (
            item["counted_quantity_base"] - item["book_quantity_base"]
            if item["counted_quantity_base"] is not None else None)
        result["lines"].append(item)
    return result


def _required(db: Session, org: UUID, doc_id: UUID, *, lock: bool = False) -> dict:
    result = get_stocktake(db, org, doc_id, lock=lock)
    if result is None:
        raise HTTPException(status_code=404, detail="盘点单不存在")
    return result


@router.get("", response_model=list[StocktakeRead])
def list_stocktakes(response: Response, warehouse_id: UUID | None = None,
                    limit: int = Query(default=100, ge=1, le=500),
                    offset: int = Query(default=0, ge=0),
                    user: CurrentUser = Depends(require_permission("inventory.stocktakes", "view")),
                    db: Session = Depends(get_db)) -> list[dict]:
    query = """
        SELECT id FROM stocktakes WHERE organization_id = :org
          AND (CAST(:warehouse_id AS uuid) IS NULL OR warehouse_id = :warehouse_id)
        ORDER BY created_at DESC, document_no DESC
    """
    rows = paginate(db, query, {"org": user.organization_id, "warehouse_id": warehouse_id},
                    limit=limit, offset=offset, response=response)
    return [get_stocktake(db, user.organization_id, row["id"]) for row in rows]


@router.get("/{doc_id}", response_model=StocktakeRead)
def read_stocktake(doc_id: UUID,
                   user: CurrentUser = Depends(require_permission("inventory.stocktakes", "view")),
                   db: Session = Depends(get_db)) -> dict:
    return _required(db, user.organization_id, doc_id)


@router.post("", response_model=StocktakeRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_stocktake(payload: StocktakeCreate,
                     user: CurrentUser = Depends(require_permission("inventory.stocktakes", "create")),
                     db: Session = Depends(get_db)) -> dict:
    active = db.execute(text("""
        SELECT is_active FROM warehouses WHERE id = :warehouse AND organization_id = :org
    """), {"warehouse": payload.warehouse_id,
           "org": user.organization_id}).scalar_one_or_none()
    if not active:
        raise HTTPException(status_code=422, detail="仓库不可用")
    try:
        # 同组织内串行取号，避免并发下生成重复单号（与销售/采购/调拨同一套）。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": user.organization_id}).scalar_one()
        document_no = payload.document_no.strip() if payload.document_no else next_document_number(
            db, user.organization_id, payload.document_date, prefix="PD", table="stocktakes",
            counter="stocktake_number_counters")
        doc_id = db.execute(text("""
            INSERT INTO stocktakes (organization_id, document_no, document_date,
                                    warehouse_id, remark, created_by)
            VALUES (:org, :document_no, :document_date, :warehouse_id,
                    :remark, :actor) RETURNING id
        """), {"org": user.organization_id, "document_no": document_no,
               "document_date": payload.document_date, "warehouse_id": payload.warehouse_id,
               "remark": payload.remark, "actor": user.id}).scalar_one()
        _audit(db, user.organization_id, user.id, "stocktake.create", doc_id)
        result = _required(db, user.organization_id, doc_id)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="盘点单号已存在") from exc


@router.post("/{doc_id}/start", response_model=StocktakeRead,
             dependencies=[Depends(require_csrf)])
def start_stocktake(doc_id: UUID,
                    user: CurrentUser = Depends(require_permission("inventory.stocktakes", "update")),
                    db: Session = Depends(get_db)) -> dict:
    doc = _required(db, user.organization_id, doc_id, lock=True)
    if doc["status"] not in ("draft", "rejected"):
        raise HTTPException(status_code=409, detail="只有草稿或已驳回的盘点单可以开始")
    warehouse = db.execute(text("""
        SELECT is_active FROM warehouses WHERE id = :id AND organization_id = :org
        FOR UPDATE
    """), {"id": doc["warehouse_id"], "org": user.organization_id}).scalar_one_or_none()
    if not warehouse:
        raise HTTPException(status_code=409, detail="仓库不可用")
    counting = db.execute(text("""
        SELECT 1 FROM stocktakes WHERE warehouse_id = :warehouse
          AND status = 'counting' LIMIT 1
    """), {"warehouse": doc["warehouse_id"]}).scalar_one_or_none()
    if counting:
        raise HTTPException(status_code=409, detail="该仓库已有正在进行的盘点")
    if doc["status"] == "rejected":
        db.execute(text("DELETE FROM stocktake_lines WHERE stocktake_id = :id"),
                   {"id": doc_id})
    db.execute(text("""
        INSERT INTO stocktake_lines (stocktake_id, item_id, book_quantity_base, sort_order)
        SELECT :id, item_id, quantity_base,
               row_number() OVER (ORDER BY item_id) - 1
        FROM stock_balances
        WHERE organization_id = :org AND warehouse_id = :warehouse
    """), {"id": doc_id, "org": user.organization_id,
           "warehouse": doc["warehouse_id"]})
    db.execute(text("""
        UPDATE stocktakes SET status = 'counting', cutoff_at = now() WHERE id = :id
    """), {"id": doc_id})
    _audit(db, user.organization_id, user.id, "stocktake.start", doc_id)
    result = _required(db, user.organization_id, doc_id)
    db.commit()
    return result


@router.put("/{doc_id}/counts", response_model=StocktakeRead,
            dependencies=[Depends(require_csrf)])
def record_counts(doc_id: UUID, payload: CountWrite,
                  user: CurrentUser = Depends(require_permission("inventory.stocktakes", "update")),
                  db: Session = Depends(get_db)) -> dict:
    doc = _required(db, user.organization_id, doc_id, lock=True)
    if doc["status"] != "counting":
        raise HTTPException(status_code=409, detail="盘点单不是清点中状态")
    if len({line.item_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(status_code=422, detail="物料重复")
    for line in payload.lines:
        item = db.execute(text("""
            SELECT is_active FROM items WHERE id = :id AND organization_id = :org
        """), {"id": line.item_id, "org": user.organization_id}).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=422, detail="物料不可用")
        db.execute(text("""
            INSERT INTO stocktake_lines (stocktake_id, item_id, book_quantity_base,
                                         counted_quantity_base, sort_order)
            VALUES (:doc_id, :item_id, 0, :counted,
                    (SELECT COALESCE(max(sort_order), -1) + 1 FROM stocktake_lines
                     WHERE stocktake_id = :doc_id))
            ON CONFLICT (stocktake_id, item_id)
            DO UPDATE SET counted_quantity_base = EXCLUDED.counted_quantity_base
        """), {"doc_id": doc_id, "item_id": line.item_id,
               "counted": line.counted_quantity_base})
    _audit(db, user.organization_id, user.id, "stocktake.count", doc_id)
    result = _required(db, user.organization_id, doc_id)
    db.commit()
    return result


@router.post("/{doc_id}/submit", response_model=StocktakeRead,
             dependencies=[Depends(require_csrf)])
def submit_stocktake(doc_id: UUID,
                     user: CurrentUser = Depends(require_permission("inventory.stocktakes", "submit")),
                     db: Session = Depends(get_db)) -> dict:
    doc = _required(db, user.organization_id, doc_id, lock=True)
    if doc["status"] != "counting" or not doc["lines"]:
        raise HTTPException(status_code=409, detail="盘点单尚未就绪")
    if any(line["counted_quantity_base"] is None for line in doc["lines"]):
        raise HTTPException(status_code=409, detail="所有盘点明细都必须录入实盘数")
    start_approval(db, user.organization_id, "stocktake", doc_id, user.id)
    db.execute(text("""
        UPDATE stocktakes SET status = 'pending_approval' WHERE id = :id
    """), {"id": doc_id})
    _audit(db, user.organization_id, user.id, "stocktake.submit", doc_id)
    result = _required(db, user.organization_id, doc_id)
    db.commit()
    return result


@router.post("/{doc_id}/cancel", response_model=StocktakeRead,
             dependencies=[Depends(require_csrf)])
def cancel_stocktake(doc_id: UUID, payload: CancelWrite,
                     user: CurrentUser = Depends(require_permission("inventory.stocktakes", "delete")),
                     db: Session = Depends(get_db)) -> dict:
    doc = _required(db, user.organization_id, doc_id, lock=True)
    if doc["status"] not in ("draft", "counting", "rejected"):
        raise HTTPException(status_code=409, detail="盘点单不能取消")
    db.execute(text("""
        UPDATE stocktakes SET status = 'cancelled'
        WHERE id = :id AND organization_id = :org
    """), {"id": doc_id, "org": user.organization_id})
    _audit(db, user.organization_id, user.id, "stocktake.cancel",
           doc_id, payload.reason.strip())
    result = _required(db, user.organization_id, doc_id)
    db.commit()
    return result


def finish_stocktake_approval(db: Session, org: UUID, actor: UUID,
                              doc_id: UUID, status: str) -> None:
    doc = _required(db, org, doc_id, lock=True)
    if doc["status"] != "pending_approval":
        raise HTTPException(status_code=409, detail="盘点单的审批状态已变化，请刷新重试")
    if status == "approved":
        changes = []
        adjustment_id = None
        differences = [line for line in doc["lines"]
                       if line["difference_quantity_base"] != 0]
        if differences:
            adjustment_id = db.execute(text("""
                INSERT INTO stock_adjustments (
                    organization_id, document_no, document_date, warehouse_id,
                    stocktake_id, reason, status, created_by, posted_at
                ) VALUES (:org, :document_no, CURRENT_DATE, :warehouse, :stocktake,
                          'stocktake_difference', 'posted', :actor, now()) RETURNING id
            """), {"org": org, "document_no": f"STK-{doc_id}",
                   "warehouse": doc["warehouse_id"], "stocktake": doc_id,
                   "actor": actor}).scalar_one()
            for line in differences:
                line_id = db.execute(text("""
                    INSERT INTO stock_adjustment_lines
                        (adjustment_id, item_id, quantity_delta_base)
                    VALUES (:adjustment, :item, :delta) RETURNING id
                """), {"adjustment": adjustment_id, "item": line["item_id"],
                       "delta": line["difference_quantity_base"]}).scalar_one()
                changes.append(StockChange(
                    warehouse_id=doc["warehouse_id"], item_id=line["item_id"],
                    quantity_delta_base=line["difference_quantity_base"],
                    source_type="stock_adjustment", source_id=adjustment_id,
                    source_line_id=line_id, movement_kind="stocktake_difference"))
            post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
        _audit(db, org, actor, "stocktake.approve", doc_id)
    else:
        _audit(db, org, actor, "stocktake.reject", doc_id)
    db.execute(text("""
        UPDATE stocktakes SET status = :status WHERE id = :id AND organization_id = :org
    """), {"status": status, "id": doc_id, "org": org})
