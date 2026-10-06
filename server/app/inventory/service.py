from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.document_numbers import next_document_number
from app.inventory import repository
from app.inventory.posting import StockChange, post_stock_changes
from app.inventory.quantities import quantity_snapshot
from app.inventory.schemas import TransferCreate


def create_transfer(db: Session, organization_id: UUID, actor_id: UUID, data: TransferCreate) -> dict:
    if data.source_warehouse_id == data.target_warehouse_id:
        raise HTTPException(status_code=422, detail="来源仓与目标仓不能相同")
    active_count = db.execute(
        text("""
            SELECT count(*) FROM warehouses
            WHERE organization_id = :organization_id AND is_active
              AND id IN (:source_id, :target_id)
        """),
        {
            "organization_id": organization_id,
            "source_id": data.source_warehouse_id,
            "target_id": data.target_warehouse_id,
        },
    ).scalar_one()
    if active_count != 2:
        raise HTTPException(status_code=422, detail="仓库不可用")

    snapshots = [
        quantity_snapshot(db, organization_id, line.item_id, line.unit_id, line.quantity)
        for line in data.lines
    ]
    try:
        # 同组织内串行取号，避免并发下生成重复单号（与销售/采购单据同一套）。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": organization_id}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, organization_id, data.document_date, prefix="DB", table="stock_transfers",
            counter="stock_transfer_number_counters")
        transfer_id = db.execute(
            text("""
                INSERT INTO stock_transfers (
                    organization_id, document_no, document_date, source_warehouse_id,
                    target_warehouse_id, remark, created_by
                ) VALUES (
                    :organization_id, :document_no, :document_date, :source_warehouse_id,
                    :target_warehouse_id, :remark, :created_by
                ) RETURNING id
            """),
            {
                "organization_id": organization_id,
                "document_no": document_no,
                "document_date": data.document_date,
                "source_warehouse_id": data.source_warehouse_id,
                "target_warehouse_id": data.target_warehouse_id,
                "remark": data.remark,
                "created_by": actor_id,
            },
        ).scalar_one()
        for index, (line, (factor, quantity_base)) in enumerate(zip(data.lines, snapshots, strict=True)):
            db.execute(
                text("""
                    INSERT INTO stock_transfer_lines (
                        transfer_id, item_id, quantity, unit_id, conversion_factor, quantity_base, sort_order
                    ) VALUES (
                        :transfer_id, :item_id, :quantity, :unit_id, :factor, :quantity_base, :sort_order
                    )
                """),
                {
                    "transfer_id": transfer_id,
                    "sort_order": index,
                    "item_id": line.item_id,
                    "quantity": line.quantity,
                    "unit_id": line.unit_id,
                    "factor": factor,
                    "quantity_base": quantity_base,
                },
            )
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:organization_id, :actor_id, 'stock_transfer.create', 'stock_transfer', :id)
            """),
            {"organization_id": organization_id, "actor_id": actor_id, "id": transfer_id},
        )
        result = repository.get_transfer(db, organization_id, transfer_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="调拨单号已存在") from exc


def post_transfer(db: Session, organization_id: UUID, actor_id: UUID, transfer_id: UUID) -> dict:
    try:
        transfer = repository.get_transfer(db, organization_id, transfer_id, lock=True)
        if transfer is None:
            raise HTTPException(status_code=404, detail="调拨单不存在")
        if transfer["status"] == "posted":
            return transfer
        if transfer["status"] != "draft":
            raise HTTPException(status_code=409, detail="调拨单不能过账")

        changes: list[StockChange] = []
        for line in transfer["lines"]:
            for warehouse_id, sign, kind in (
                (transfer["source_warehouse_id"], Decimal("-1"), "transfer_out"),
                (transfer["target_warehouse_id"], Decimal("1"), "transfer_in"),
            ):
                changes.append(StockChange(
                    warehouse_id=warehouse_id,
                    item_id=line["item_id"],
                    quantity_delta_base=line["quantity_base"] * sign,
                    source_type="stock_transfer",
                    source_id=transfer_id,
                    source_line_id=line["id"],
                    movement_kind=kind,
                ))
        post_stock_changes(db, organization_id=organization_id, actor_id=actor_id, changes=changes)
        db.execute(
            text("UPDATE stock_transfers SET status = 'posted', posted_at = now() WHERE id = :id"),
            {"id": transfer_id},
        )
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:organization_id, :actor_id, 'stock_transfer.post', 'stock_transfer', :id)
            """),
            {"organization_id": organization_id, "actor_id": actor_id, "id": transfer_id},
        )
        db.commit()
        transfer["status"] = "posted"
        return transfer
    except Exception:
        db.rollback()
        raise


def reverse_transfer(db: Session, organization_id: UUID, actor_id: UUID,
                     transfer_id: UUID, reason: str) -> dict:
    transfer = repository.get_transfer(db, organization_id, transfer_id, lock=True)
    if transfer is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    if transfer["status"] == "reversed":
        return transfer
    if transfer["status"] != "posted":
        raise HTTPException(status_code=409, detail="只有已过账的调拨单可以冲销")
    changes = []
    for line in transfer["lines"]:
        for warehouse_id, sign, original_kind, reverse_kind in (
            (transfer["source_warehouse_id"], Decimal("1"),
             "transfer_out", "transfer_reverse_in"),
            (transfer["target_warehouse_id"], Decimal("-1"),
             "transfer_in", "transfer_reverse_out"),
        ):
            original_id = db.execute(text("""
                SELECT id FROM stock_movements
                WHERE organization_id = :org AND source_type = 'stock_transfer'
                  AND source_id = :doc_id AND source_line_id = :line_id
                  AND movement_kind = :kind
            """), {"org": organization_id, "doc_id": transfer_id,
                   "line_id": line["id"], "kind": original_kind}).scalar_one()
            changes.append(StockChange(
                warehouse_id=warehouse_id, item_id=line["item_id"],
                quantity_delta_base=line["quantity_base"] * sign,
                source_type="stock_transfer_reversal", source_id=transfer_id,
                source_line_id=line["id"], movement_kind=reverse_kind,
                reversal_of_id=original_id))
    post_stock_changes(db, organization_id=organization_id,
                       actor_id=actor_id, changes=changes)
    db.execute(text("""
        UPDATE stock_transfers SET status = 'reversed'
        WHERE id = :id AND organization_id = :org
    """), {"id": transfer_id, "org": organization_id})
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, 'stock_transfer.reverse',
                'stock_transfer', :id, :reason)
    """), {"org": organization_id, "actor": actor_id,
           "id": transfer_id, "reason": reason.strip()})
    result = repository.get_transfer(db, organization_id, transfer_id)
    db.commit()
    assert result is not None
    return result
