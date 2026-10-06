"""Authorized manual stock adjustments and audited reversals."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.pagination import paginate
from app.core.security import CurrentUser, require_csrf, require_permission
from app.inventory.posting import StockChange, post_stock_changes

router = APIRouter(prefix="/api/inventory/adjustments", tags=["inventory"])


class AdjustmentLineWrite(BaseModel):
    item_id: UUID
    quantity_delta_base: Decimal = Field(max_digits=20, decimal_places=6)


class AdjustmentWrite(BaseModel):
    document_no: str = Field(min_length=1, max_length=80, pattern=r"\S")
    document_date: date
    warehouse_id: UUID
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    remark: str | None = None
    lines: list[AdjustmentLineWrite] = Field(min_length=1)


class ReverseWrite(BaseModel):
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class AdjustmentLineRead(AdjustmentLineWrite):
    id: UUID


class AdjustmentRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    document_date: date
    warehouse_id: UUID
    stocktake_id: UUID | None
    reason: str
    status: str
    remark: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    posted_at: datetime | None
    lines: list[AdjustmentLineRead]


def _get(db: Session, org: UUID, doc_id: UUID, *, lock: bool = False) -> dict | None:
    row = db.execute(text("""
        SELECT id, organization_id, document_no, document_date, warehouse_id,
               stocktake_id, reason, status, remark, created_by, created_at,
               updated_at, posted_at
        FROM stock_adjustments WHERE id = :id AND organization_id = :org
    """ + (" FOR UPDATE" if lock else "")), {"id": doc_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT id, item_id, quantity_delta_base FROM stock_adjustment_lines
        WHERE adjustment_id = :id ORDER BY sort_order, id
    """), {"id": doc_id}).mappings()]
    return result


def _required(db: Session, org: UUID, doc_id: UUID, *, lock: bool = False) -> dict:
    result = _get(db, org, doc_id, lock=lock)
    if result is None:
        raise HTTPException(status_code=404, detail="库存调整单不存在")
    return result


def _audit(db: Session, org: UUID, actor: UUID, action: str,
           doc_id: UUID, reason: str | None = None) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, :action, 'stock_adjustment', :id, :reason)
    """), {"org": org, "actor": actor, "action": action,
           "id": doc_id, "reason": reason})


def _validate(db: Session, org: UUID, data: AdjustmentWrite) -> None:
    if len({line.item_id for line in data.lines}) != len(data.lines):
        raise HTTPException(status_code=422, detail="调整物料重复")
    if any(line.quantity_delta_base == 0 for line in data.lines):
        raise HTTPException(status_code=422, detail="调整数量不能为零")
    warehouse = db.execute(text("""
        SELECT is_active FROM warehouses WHERE id = :id AND organization_id = :org
    """), {"id": data.warehouse_id, "org": org}).scalar_one_or_none()
    if not warehouse:
        raise HTTPException(status_code=422, detail="仓库不可用")
    for line in data.lines:
        item = db.execute(text("""
            SELECT is_active FROM items WHERE id = :id AND organization_id = :org
        """), {"id": line.item_id, "org": org}).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=422, detail="物料不可用")


def _write_lines(db: Session, doc_id: UUID, data: AdjustmentWrite) -> None:
    for index, line in enumerate(data.lines):
        db.execute(text("""
            INSERT INTO stock_adjustment_lines
                (adjustment_id, item_id, quantity_delta_base, sort_order)
            VALUES (:doc, :item, :delta, :sort_order)
        """), {"doc": doc_id, "item": line.item_id,
               "delta": line.quantity_delta_base, "sort_order": index})


@router.get("", response_model=list[AdjustmentRead])
def list_adjustments(response: Response, warehouse_id: UUID | None = None,
                     limit: int = Query(default=100, ge=1, le=500),
                     offset: int = Query(default=0, ge=0),
                     user: CurrentUser = Depends(require_permission("inventory.adjustments", "view")),
                     db: Session = Depends(get_db)) -> list[dict]:
    query = """
        SELECT id FROM stock_adjustments WHERE organization_id = :org
          AND (CAST(:warehouse AS uuid) IS NULL OR warehouse_id = :warehouse)
        ORDER BY created_at DESC, document_no DESC
    """
    rows = paginate(db, query, {"org": user.organization_id, "warehouse": warehouse_id},
                    limit=limit, offset=offset, response=response)
    return [_get(db, user.organization_id, row["id"]) for row in rows]


@router.get("/{doc_id}", response_model=AdjustmentRead)
def get_adjustment(doc_id: UUID,
                   user: CurrentUser = Depends(require_permission("inventory.adjustments", "view")),
                   db: Session = Depends(get_db)) -> dict:
    return _required(db, user.organization_id, doc_id)


@router.post("", response_model=AdjustmentRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_adjustment(payload: AdjustmentWrite,
                      user: CurrentUser = Depends(require_permission("inventory.adjustments", "adjust")),
                      db: Session = Depends(get_db)) -> dict:
    _validate(db, user.organization_id, payload)
    try:
        doc_id = db.execute(text("""
            INSERT INTO stock_adjustments (organization_id, document_no,
                document_date, warehouse_id, reason, remark, created_by)
            VALUES (:org, :number, :date, :warehouse, :reason, :remark, :actor)
            RETURNING id
        """), {"org": user.organization_id, "number": payload.document_no.strip(),
               "date": payload.document_date, "warehouse": payload.warehouse_id,
               "reason": payload.reason.strip(), "remark": payload.remark,
               "actor": user.id}).scalar_one()
        _write_lines(db, doc_id, payload)
        _audit(db, user.organization_id, user.id, "stock_adjustment.create",
               doc_id, payload.reason.strip())
        result = _required(db, user.organization_id, doc_id)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="库存调整单号已存在") from exc


@router.put("/{doc_id}", response_model=AdjustmentRead,
            dependencies=[Depends(require_csrf)])
def update_adjustment(doc_id: UUID, payload: AdjustmentWrite,
                      user: CurrentUser = Depends(require_permission("inventory.adjustments", "adjust")),
                      db: Session = Depends(get_db)) -> dict:
    current = _required(db, user.organization_id, doc_id, lock=True)
    if current["status"] != "draft" or current["stocktake_id"] is not None:
        raise HTTPException(status_code=409, detail="只有手工新建的草稿调整单可以修改")
    _validate(db, user.organization_id, payload)
    try:
        db.execute(text("""
            UPDATE stock_adjustments SET document_no = :number, document_date = :date,
                warehouse_id = :warehouse, reason = :reason, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"number": payload.document_no.strip(), "date": payload.document_date,
               "warehouse": payload.warehouse_id, "reason": payload.reason.strip(),
               "remark": payload.remark, "id": doc_id, "org": user.organization_id})
        db.execute(text("DELETE FROM stock_adjustment_lines WHERE adjustment_id = :id"),
                   {"id": doc_id})
        _write_lines(db, doc_id, payload)
        _audit(db, user.organization_id, user.id, "stock_adjustment.update",
               doc_id, payload.reason.strip())
        result = _required(db, user.organization_id, doc_id)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="库存调整单号已存在") from exc


@router.delete("/{doc_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_adjustment(doc_id: UUID,
                      user: CurrentUser = Depends(require_permission("inventory.adjustments", "adjust")),
                      db: Session = Depends(get_db)) -> None:
    doc = _required(db, user.organization_id, doc_id, lock=True)
    if doc["status"] != "draft" or doc["stocktake_id"] is not None:
        raise HTTPException(status_code=409, detail="只有手工新建的草稿调整单可以删除")
    db.execute(text("DELETE FROM stock_adjustments WHERE id = :id AND organization_id = :org"),
               {"id": doc_id, "org": user.organization_id})
    _audit(db, user.organization_id, user.id, "stock_adjustment.delete", doc_id)
    db.commit()


@router.post("/{doc_id}/post", response_model=AdjustmentRead,
             dependencies=[Depends(require_csrf)])
def post_adjustment(doc_id: UUID,
                    user: CurrentUser = Depends(require_permission("inventory.adjustments", "adjust")),
                    db: Session = Depends(get_db)) -> dict:
    doc = _required(db, user.organization_id, doc_id, lock=True)
    if doc["status"] == "posted":
        return doc
    if doc["status"] != "draft" or doc["stocktake_id"] is not None:
        raise HTTPException(status_code=409, detail="库存调整单不能过账")
    changes = [StockChange(
        warehouse_id=doc["warehouse_id"], item_id=line["item_id"],
        quantity_delta_base=line["quantity_delta_base"],
        source_type="stock_adjustment", source_id=doc_id,
        source_line_id=line["id"], movement_kind="manual_adjustment")
        for line in doc["lines"]]
    post_stock_changes(db, organization_id=user.organization_id,
                       actor_id=user.id, changes=changes)
    db.execute(text("""
        UPDATE stock_adjustments SET status = 'posted', posted_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": doc_id, "org": user.organization_id})
    _audit(db, user.organization_id, user.id, "stock_adjustment.post",
           doc_id, doc["reason"])
    result = _required(db, user.organization_id, doc_id)
    db.commit()
    return result


@router.post("/{doc_id}/reverse", response_model=AdjustmentRead,
             dependencies=[Depends(require_csrf)])
def reverse_adjustment(doc_id: UUID, payload: ReverseWrite,
                       user: CurrentUser = Depends(require_permission("inventory.adjustments", "reverse")),
                       db: Session = Depends(get_db)) -> dict:
    doc = _required(db, user.organization_id, doc_id, lock=True)
    if doc["status"] == "reversed":
        return doc
    if doc["status"] != "posted":
        raise HTTPException(status_code=409, detail="只有已过账的库存调整单可以冲销")
    changes = []
    for line in doc["lines"]:
        original_id = db.execute(text("""
            SELECT id FROM stock_movements
            WHERE organization_id = :org AND source_type = 'stock_adjustment'
              AND source_id = :doc AND source_line_id = :line
        """), {"org": user.organization_id, "doc": doc_id,
               "line": line["id"]}).scalar_one()
        changes.append(StockChange(
            warehouse_id=doc["warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=-line["quantity_delta_base"],
            source_type="stock_adjustment_reversal", source_id=doc_id,
            source_line_id=line["id"], movement_kind="adjustment_reversal",
            reversal_of_id=original_id))
    post_stock_changes(db, organization_id=user.organization_id,
                       actor_id=user.id, changes=changes)
    db.execute(text("""
        UPDATE stock_adjustments SET status = 'reversed'
        WHERE id = :id AND organization_id = :org
    """), {"id": doc_id, "org": user.organization_id})
    _audit(db, user.organization_id, user.id, "stock_adjustment.reverse",
           doc_id, payload.reason.strip())
    result = _required(db, user.organization_id, doc_id)
    db.commit()
    return result
