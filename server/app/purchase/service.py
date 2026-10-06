from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.document_numbers import next_document_number
from app.inventory.quantities import quantity_snapshot
from app.purchase import repository
from app.purchase.schemas import PurchaseOrderWrite


def audit(db: Session, org: UUID, actor: UUID, action: str,
          document_type: str, document_id: UUID, reason: str | None = None) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, :action, :document_type, :id, :reason)
    """), {"org": org, "actor": actor, "action": action,
           "document_type": document_type, "id": document_id, "reason": reason})


def validate_supplier(db: Session, org: UUID, supplier_id: UUID) -> None:
    valid = db.execute(text("""
        SELECT 1 FROM parties p JOIN party_types pt ON pt.party_id = p.id
        WHERE p.id = :id AND p.organization_id = :org AND p.is_active
          AND pt.party_type = 'supplier'
    """), {"id": supplier_id, "org": org}).scalar_one_or_none()
    if not valid:
        raise HTTPException(status_code=422, detail="供应商不可用")


def order_line(db: Session, order_id: UUID, line_id: UUID) -> dict:
    row = db.execute(text("""
        SELECT id, item_id, quantity_base, conversion_factor, unit_price, amount
        FROM purchase_order_lines WHERE id = :id AND purchase_order_id = :order_id
    """), {"id": line_id, "order_id": order_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=422, detail="采购订单明细不属于该订单")
    return dict(row)


def _snapshots(db: Session, org: UUID, data: PurchaseOrderWrite) -> list[tuple[Decimal, Decimal, Decimal]]:
    result = []
    for line in data.lines:
        factor, base = quantity_snapshot(db, org, line.item_id, line.unit_id, line.quantity)
        amount = (line.quantity * line.unit_price).quantize(Decimal("0.01"),
                                                             rounding=ROUND_HALF_UP)
        if amount >= Decimal("10000000000000000"):
            raise HTTPException(status_code=422, detail="明细金额过大")
        result.append((factor, base, amount))
    return result


def _write_lines(db: Session, order_id: UUID, data: PurchaseOrderWrite,
                 snapshots: list[tuple[Decimal, Decimal, Decimal]]) -> None:
    for index, (line, (factor, base, amount)) in enumerate(zip(data.lines, snapshots, strict=True)):
        db.execute(text("""
            INSERT INTO purchase_order_lines (
                purchase_order_id, item_id, quantity, unit_id, conversion_factor,
                quantity_base, unit_price, amount, sort_order
            ) VALUES (:order_id, :item_id, :quantity, :unit_id, :factor,
                      :base, :unit_price, :amount, :sort_order)
        """), {"order_id": order_id, "item_id": line.item_id,
               "quantity": line.quantity, "unit_id": line.unit_id,
               "factor": factor, "base": base,
               "unit_price": line.unit_price, "amount": amount,
               "sort_order": index})


def create_order(db: Session, org: UUID, actor: UUID, data: PurchaseOrderWrite) -> dict:
    validate_supplier(db, org, data.supplier_id)
    snapshots = _snapshots(db, org, data)
    try:
        # 同组织内串行取号，避免并发下生成重复单号。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="CG", table="purchase_orders",
            counter="purchase_order_number_counters")
        order_id = db.execute(text("""
            INSERT INTO purchase_orders (
                organization_id, document_no, supplier_id, document_date, remark, created_by
            ) VALUES (:org, :document_no, :supplier_id, :document_date, :remark, :actor)
            RETURNING id
        """), {"org": org, "document_no": document_no,
               "supplier_id": data.supplier_id, "document_date": data.document_date,
               "remark": data.remark, "actor": actor}).scalar_one()
        _write_lines(db, order_id, data, snapshots)
        audit(db, org, actor, "purchase_order.create", "purchase_order", order_id)
        result = repository.get_order(db, org, order_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="采购订单号已存在") from exc


def update_order(db: Session, org: UUID, actor: UUID, order_id: UUID,
                 data: PurchaseOrderWrite) -> dict:
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="采购订单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的采购订单可以修改")
    validate_supplier(db, org, data.supplier_id)
    snapshots = _snapshots(db, org, data)
    try:
        db.execute(text("""
            UPDATE purchase_orders SET document_no = :document_no,
                supplier_id = :supplier_id, document_date = :document_date,
                remark = :remark WHERE id = :id AND organization_id = :org
        """), {"id": order_id, "org": org,
               "document_no": (data.document_no or current["document_no"]).strip(),
               "supplier_id": data.supplier_id, "document_date": data.document_date,
               "remark": data.remark})
        db.execute(text("DELETE FROM purchase_order_lines WHERE purchase_order_id = :id"),
                   {"id": order_id})
        _write_lines(db, order_id, data, snapshots)
        audit(db, org, actor, "purchase_order.update", "purchase_order", order_id)
        result = repository.get_order(db, org, order_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="采购订单号已存在") from exc


def delete_order(db: Session, org: UUID, actor: UUID, order_id: UUID) -> None:
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="采购订单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的采购订单可以删除")
    db.execute(text("DELETE FROM purchase_orders WHERE id = :id AND organization_id = :org"),
               {"id": order_id, "org": org})
    audit(db, org, actor, "purchase_order.delete", "purchase_order", order_id)
    db.commit()


def open_order(db: Session, org: UUID, actor: UUID, order_id: UUID) -> dict:
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="采购订单不存在")
    if current["status"] != "draft" or not current["lines"]:
        raise HTTPException(status_code=409, detail="采购订单不能开单")
    db.execute(text("""
        UPDATE purchase_orders SET status = 'open'
        WHERE id = :id AND organization_id = :org
    """), {"id": order_id, "org": org})
    audit(db, org, actor, "purchase_order.open", "purchase_order", order_id)
    result = repository.get_order(db, org, order_id)
    db.commit()
    assert result is not None
    return result


def close_order(db: Session, org: UUID, actor: UUID, order_id: UUID,
                remark: str) -> dict:
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="采购订单不存在")
    if current["status"] != "open":
        raise HTTPException(status_code=409, detail="只有进行中的采购订单可以关闭")
    db.execute(text("""
        UPDATE purchase_orders SET status = 'closed', close_remark = :remark
        WHERE id = :id AND organization_id = :org
    """), {"id": order_id, "org": org, "remark": remark.strip()})
    audit(db, org, actor, "purchase_order.force_close", "purchase_order",
          order_id, remark.strip())
    result = repository.get_order(db, org, order_id)
    db.commit()
    assert result is not None
    return result
