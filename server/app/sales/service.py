from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.approval.workflow import start_approval
from app.core.document_numbers import next_document_number
from app.inventory.quantities import quantity_snapshot
from app.sales import repository
from app.sales.schemas import SalesOrderWrite


def _validate_customer(db: Session, org: UUID, customer_id: UUID) -> None:
    available = db.execute(text("""
        SELECT 1 FROM parties p JOIN party_types pt ON pt.party_id = p.id
        WHERE p.id = :id AND p.organization_id = :org AND p.is_active
          AND pt.party_type = 'customer'
    """), {"id": customer_id, "org": org}).scalar_one_or_none()
    if not available:
        raise HTTPException(status_code=422, detail="客户不可用")


def _snapshots(db: Session, org: UUID, data: SalesOrderWrite) -> list[tuple[Decimal, Decimal, Decimal]]:
    result = []
    for line in data.lines:
        # 销售单不限定物料类型：半成品、原材料也可能直接开单出售；
        # 物料是否存在/启用、单位换算是否合法由 quantity_snapshot 统一把关。
        factor, quantity_base = quantity_snapshot(db, org, line.item_id,
                                                  line.unit_id, line.quantity)
        amount = (line.quantity * line.unit_price).quantize(Decimal("0.01"),
                                                             rounding=ROUND_HALF_UP)
        if amount >= Decimal("10000000000000000"):
            raise HTTPException(status_code=422, detail="明细金额过大")
        result.append((factor, quantity_base, amount))
    return result


def _write_lines(db: Session, order_id: UUID, data: SalesOrderWrite,
                 snapshots: list[tuple[Decimal, Decimal, Decimal]]) -> None:
    for index, (line, (factor, quantity_base, amount)) in enumerate(zip(data.lines, snapshots, strict=True)):
        db.execute(text("""
            INSERT INTO sales_order_lines (
                sales_order_id, item_id, quantity, unit_id, conversion_factor,
                quantity_base, unit_price, amount, sort_order
            ) VALUES (
                :order_id, :item_id, :quantity, :unit_id, :factor,
                :quantity_base, :unit_price, :amount, :sort_order
            )
        """), {"order_id": order_id, "item_id": line.item_id,
               "quantity": line.quantity, "unit_id": line.unit_id,
               "factor": factor, "quantity_base": quantity_base,
               "unit_price": line.unit_price, "amount": amount,
               "sort_order": index})


def _audit(db: Session, org: UUID, actor: UUID, action: str, order_id: UUID,
           reason: str | None = None) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, :action, 'sales_order', :id, :reason)
    """), {"org": org, "actor": actor, "action": action,
           "id": order_id, "reason": reason})


def create_order(db: Session, org: UUID, actor: UUID, data: SalesOrderWrite) -> dict:
    _validate_customer(db, org, data.customer_id)
    snapshots = _snapshots(db, org, data)
    try:
        # Serialize creation within an organization, including legacy clients that
        # still send their own document number.
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="XS", table="sales_orders",
            counter="sales_order_number_counters")
        order_id = db.execute(text("""
            INSERT INTO sales_orders (organization_id, document_no, customer_id,
                                      document_date, delivery_date, remark, created_by)
            VALUES (:org, :document_no, :customer_id, :document_date,
                    :delivery_date, :remark, :actor) RETURNING id
        """), {"org": org, "document_no": document_no,
               "customer_id": data.customer_id, "document_date": data.document_date,
               "delivery_date": data.delivery_date, "remark": data.remark,
               "actor": actor}).scalar_one()
        _write_lines(db, order_id, data, snapshots)
        _audit(db, org, actor, "sales_order.create", order_id)
        result = repository.get_order(db, org, order_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="销售订单号已存在") from exc


def update_order(db: Session, org: UUID, actor: UUID, order_id: UUID,
                 data: SalesOrderWrite) -> dict:
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="销售订单不存在")
    if current["status"] not in ("draft", "rejected"):
        raise HTTPException(status_code=409, detail="销售订单不能修改")
    _validate_customer(db, org, data.customer_id)
    snapshots = _snapshots(db, org, data)
    try:
        db.execute(text("""
            UPDATE sales_orders SET customer_id = :customer_id,
                document_date = :document_date, delivery_date = :delivery_date,
                remark = :remark, status = 'draft', updated_at = now()
            WHERE id = :id AND organization_id = :org
        """), {"id": order_id, "org": org,
               "customer_id": data.customer_id, "document_date": data.document_date,
               "delivery_date": data.delivery_date, "remark": data.remark})
        db.execute(text("DELETE FROM sales_order_lines WHERE sales_order_id = :id"),
                   {"id": order_id})
        _write_lines(db, order_id, data, snapshots)
        _audit(db, org, actor, "sales_order.update", order_id)
        result = repository.get_order(db, org, order_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="销售订单号已存在") from exc


def delete_order(db: Session, org: UUID, actor: UUID, order_id: UUID) -> None:
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="销售订单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的销售订单可以删除")
    db.execute(text("DELETE FROM sales_orders WHERE id = :id AND organization_id = :org"),
               {"id": order_id, "org": org})
    _audit(db, org, actor, "sales_order.delete", order_id)
    db.commit()


def submit_order(db: Session, org: UUID, actor: UUID, order_id: UUID) -> dict:
    db.execute(text("SELECT id FROM organizations WHERE id = :id FOR UPDATE"),
               {"id": org}).scalar_one()
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="销售订单不存在")
    if current["status"] not in ("draft", "rejected"):
        raise HTTPException(status_code=409, detail="销售订单不能提交")
    if not current["lines"]:
        raise HTTPException(status_code=422, detail="销售订单没有明细")
    start_approval(db, org, "sales_order", order_id, actor)
    db.execute(text("""
        UPDATE sales_orders SET status = 'pending_approval', updated_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": order_id, "org": org})
    _audit(db, org, actor, "sales_order.submit", order_id)
    result = repository.get_order(db, org, order_id)
    db.commit()
    assert result is not None
    return result


def close_order(db: Session, org: UUID, actor: UUID, order_id: UUID,
                remark: str) -> dict:
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="销售订单不存在")
    if current["status"] != "approved":
        raise HTTPException(status_code=409, detail="只有已审批的销售订单可以结束")
    db.execute(text("""
        UPDATE sales_orders SET status = 'closed', close_remark = :remark, updated_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": order_id, "org": org, "remark": remark.strip()})
    _audit(db, org, actor, "sales_order.force_close", order_id, remark.strip())
    result = repository.get_order(db, org, order_id)
    db.commit()
    assert result is not None
    return result
