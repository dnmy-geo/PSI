"""The single transaction-local entry point for stock ledger postings."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class StockChange:
    warehouse_id: UUID
    item_id: UUID
    quantity_delta_base: Decimal
    source_type: str
    source_id: UUID
    source_line_id: UUID
    movement_kind: str
    reversal_of_id: UUID | None = None


def post_stock_changes(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    changes: list[StockChange],
) -> None:
    """Write balances and immutable movements; caller commits the whole business document."""
    if not changes:
        raise ValueError("At least one stock change is required")
    if any(change.quantity_delta_base == 0 for change in changes):
        raise ValueError("Stock changes must be nonzero")

    warehouse_ids = sorted({change.warehouse_id for change in changes})
    item_ids = sorted({change.item_id for change in changes})
    balance_keys = sorted({(change.warehouse_id, change.item_id) for change in changes})

    # Lock active warehouses before balances. Warehouse maintenance uses an
    # exclusive lock on the same row so it cannot disable a posting warehouse.
    for warehouse_id in warehouse_ids:
        active = db.execute(
            text("""
                SELECT is_active FROM warehouses
                WHERE id = :warehouse_id AND organization_id = :organization_id
                FOR SHARE
            """),
            {"warehouse_id": warehouse_id, "organization_id": organization_id},
        ).scalar_one_or_none()
        if active is None or not active:
            raise HTTPException(status_code=409, detail="仓库不可用")
        counting = db.execute(text("""
            SELECT 1 FROM stocktakes
            WHERE organization_id = :organization_id AND warehouse_id = :warehouse_id
              AND status = 'counting' LIMIT 1
        """), {"organization_id": organization_id,
               "warehouse_id": warehouse_id}).scalar_one_or_none()
        if counting:
            raise HTTPException(status_code=409, detail="该仓库正在盘点，暂停收发")

    for item_id in item_ids:
        active = db.execute(
            text("""
                SELECT is_active FROM items
                WHERE id = :item_id AND organization_id = :organization_id
                FOR SHARE
            """),
            {"item_id": item_id, "organization_id": organization_id},
        ).scalar_one_or_none()
        if active is None or not active:
            raise HTTPException(status_code=409, detail="物料不可用")

    current_balances: dict[tuple[UUID, UUID], Decimal] = {}
    for warehouse_id, item_id in balance_keys:
        params = {
            "organization_id": organization_id,
            "warehouse_id": warehouse_id,
            "item_id": item_id,
        }
        db.execute(
            text("""
                INSERT INTO stock_balances (organization_id, warehouse_id, item_id, quantity_base)
                VALUES (:organization_id, :warehouse_id, :item_id, 0)
                ON CONFLICT (organization_id, warehouse_id, item_id) DO NOTHING
            """),
            params,
        )
        quantity = db.execute(
            text("""
                SELECT quantity_base FROM stock_balances
                WHERE organization_id = :organization_id
                  AND warehouse_id = :warehouse_id AND item_id = :item_id
                FOR UPDATE
            """),
            params,
        ).scalar_one()
        current_balances[(warehouse_id, item_id)] = quantity

    totals: dict[tuple[UUID, UUID], Decimal] = {key: Decimal("0") for key in balance_keys}
    for change in changes:
        totals[(change.warehouse_id, change.item_id)] += change.quantity_delta_base
    for key, delta in totals.items():
        if current_balances[key] + delta < 0:
            raise HTTPException(status_code=409, detail="库存不足")

    for (warehouse_id, item_id), delta in totals.items():
        if delta:
            db.execute(
                text("""
                    UPDATE stock_balances
                    SET quantity_base = quantity_base + :delta, updated_at = now()
                    WHERE organization_id = :organization_id
                      AND warehouse_id = :warehouse_id AND item_id = :item_id
                """),
                {
                    "organization_id": organization_id,
                    "warehouse_id": warehouse_id,
                    "item_id": item_id,
                    "delta": delta,
                },
            )

    for change in changes:
        db.execute(
            text("""
                INSERT INTO stock_movements (
                    organization_id, warehouse_id, item_id, quantity_delta_base,
                    source_type, source_id, source_line_id, movement_kind, posted_by
                    , reversal_of_id
                ) VALUES (
                    :organization_id, :warehouse_id, :item_id, :delta,
                    :source_type, :source_id, :source_line_id, :movement_kind, :actor_id
                    , :reversal_of_id
                )
            """),
            {
                "organization_id": organization_id,
                "warehouse_id": change.warehouse_id,
                "item_id": change.item_id,
                "delta": change.quantity_delta_base,
                "source_type": change.source_type,
                "source_id": change.source_id,
                "source_line_id": change.source_line_id,
                "movement_kind": change.movement_kind,
                "actor_id": actor_id,
                "reversal_of_id": change.reversal_of_id,
            },
        )
