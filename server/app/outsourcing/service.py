from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.document_numbers import next_document_number
from app.outsourcing import repository
from app.outsourcing.schemas import OrderWrite


def audit(db: Session, org: UUID, actor: UUID, action: str,
          document_type: str, doc_id: UUID, reason: str | None = None) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, :action, :document_type, :id, :reason)
    """), {"org": org, "actor": actor, "action": action,
           "document_type": document_type, "id": doc_id, "reason": reason})


def _validate(db: Session, org: UUID, data: OrderWrite) -> None:
    processor = db.execute(text("""
        SELECT 1 FROM parties p JOIN party_types t ON t.party_id = p.id
        WHERE p.id = :id AND p.organization_id = :org AND p.is_active
          AND t.party_type = 'processor'
    """), {"id": data.processor_id, "org": org}).scalar_one_or_none()
    if not processor:
        raise HTTPException(status_code=422, detail="加工商不可用")
    material_keys = [(line.item_id, line.supply_party) for line in data.materials]
    if len(material_keys) != len(set(material_keys)):
        raise HTTPException(status_code=422, detail="物料与供料方的组合重复")
    if len({line.item_id for line in data.outputs}) != len(data.outputs):
        raise HTTPException(status_code=422, detail="产出物料重复")
    for line in [*data.materials, *data.outputs]:
        row = db.execute(text("""
            SELECT item_type, is_active FROM items
            WHERE id = :id AND organization_id = :org
        """), {"id": line.item_id, "org": org}).mappings().first()
        if row is None or not row["is_active"]:
            raise HTTPException(status_code=422, detail="物料不可用")
    for line in data.outputs:
        item_type = db.execute(text("""
            SELECT item_type FROM items WHERE id = :id AND organization_id = :org
        """), {"id": line.item_id, "org": org}).scalar_one()
        if item_type not in ("semi_finished", "finished"):
            raise HTTPException(status_code=422, detail="产出必须是半成品或成品")


def _write_lines(db: Session, order_id: UUID, data: OrderWrite) -> None:
    for index, line in enumerate(data.materials):
        db.execute(text("""
            INSERT INTO outsourcing_material_lines
                (outsourcing_order_id, item_id, supply_party, expected_quantity_base, sort_order)
            VALUES (:order_id, :item, :supply_party, :quantity, :sort_order)
        """), {"order_id": order_id, "item": line.item_id,
               "supply_party": line.supply_party,
               "quantity": line.expected_quantity_base, "sort_order": index})
    for index, line in enumerate(data.outputs):
        db.execute(text("""
            INSERT INTO outsourcing_output_lines
                (outsourcing_order_id, item_id, expected_quantity_base, unit_price, sort_order)
            VALUES (:order_id, :item, :quantity, :price, :sort_order)
        """), {"order_id": order_id, "item": line.item_id,
               "quantity": line.expected_quantity_base,
               "price": line.unit_price, "sort_order": index})


def create_order(db: Session, org: UUID, actor: UUID, data: OrderWrite) -> dict:
    _validate(db, org, data)
    try:
        # 同组织内串行取号，避免并发下生成重复单号（与销售/采购/调拨同一套）。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="WW", table="outsourcing_orders",
            counter="outsourcing_order_number_counters")
        order_id = db.execute(text("""
            INSERT INTO outsourcing_orders
                (organization_id, document_no, processor_id, document_date,
                 remark, created_by)
            VALUES (:org, :number, :processor, :date, :remark, :actor)
            RETURNING id
        """), {"org": org, "number": document_no,
               "processor": data.processor_id, "date": data.document_date,
               "remark": data.remark, "actor": actor}).scalar_one()
        _write_lines(db, order_id, data)
        audit(db, org, actor, "outsourcing_order.create", "outsourcing_order", order_id)
        result = repository.get_order(db, org, order_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="委外单号已存在") from exc


def update_order(db: Session, org: UUID, actor: UUID, order_id: UUID,
                 data: OrderWrite) -> dict:
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="委外单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的委外单可以修改")
    _validate(db, org, data)
    try:
        db.execute(text("""
            UPDATE outsourcing_orders SET document_no = :number,
                processor_id = :processor, document_date = :date, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"id": order_id, "org": org,
               # 编辑时留空保留原单号，不会被清掉。
               "number": (data.document_no or current["document_no"]).strip(),
               "processor": data.processor_id, "date": data.document_date,
               "remark": data.remark})
        db.execute(text("DELETE FROM outsourcing_material_lines WHERE outsourcing_order_id = :id"),
                   {"id": order_id})
        db.execute(text("DELETE FROM outsourcing_output_lines WHERE outsourcing_order_id = :id"),
                   {"id": order_id})
        _write_lines(db, order_id, data)
        audit(db, org, actor, "outsourcing_order.update", "outsourcing_order", order_id)
        result = repository.get_order(db, org, order_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="委外单号已存在") from exc


def delete_order(db: Session, org: UUID, actor: UUID, order_id: UUID) -> None:
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="委外单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的委外单可以删除")
    db.execute(text("DELETE FROM outsourcing_orders WHERE id = :id AND organization_id = :org"),
               {"id": order_id, "org": org})
    audit(db, org, actor, "outsourcing_order.delete", "outsourcing_order", order_id)
    db.commit()


def set_status(db: Session, org: UUID, actor: UUID, order_id: UUID,
               target: str, remark: str | None = None) -> dict:
    current = repository.get_order(db, org, order_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="委外单不存在")
    if target == "open" and current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的订单可以开单")
    if target == "closed" and current["status"] != "open":
        raise HTTPException(status_code=409, detail="只有进行中的订单可以关闭")
    db.execute(text("""
        UPDATE outsourcing_orders SET status = :status,
            remark = CASE WHEN :status = 'closed' THEN :remark ELSE remark END
        WHERE id = :id AND organization_id = :org
    """), {"status": target, "remark": remark.strip() if remark else None,
           "id": order_id, "org": org})
    audit(db, org, actor, f"outsourcing_order.{target}",
          "outsourcing_order", order_id, remark.strip() if remark else None)
    result = repository.get_order(db, org, order_id)
    db.commit()
    assert result is not None
    return result
