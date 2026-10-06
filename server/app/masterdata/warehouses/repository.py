from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def list_warehouses(db: Session, organization_id: UUID) -> list[dict]:
    return [
        dict(row)
        for row in db.execute(
            text("""
                SELECT id, organization_id, code, name, is_active, created_at, updated_at
                FROM warehouses WHERE organization_id = :organization_id
                ORDER BY created_at DESC, code
            """),
            {"organization_id": organization_id},
        ).mappings()
    ]


def get_warehouse(db: Session, organization_id: UUID, warehouse_id: UUID) -> dict | None:
    row = db.execute(
        text("""
            SELECT id, organization_id, code, name, is_active, created_at, updated_at
            FROM warehouses WHERE organization_id = :organization_id AND id = :id
        """),
        {"organization_id": organization_id, "id": warehouse_id},
    ).mappings().first()
    return dict(row) if row is not None else None


def lock_warehouse(db: Session, organization_id: UUID, warehouse_id: UUID) -> dict | None:
    row = db.execute(
        text("""
            SELECT id, organization_id, code, name, is_active
            FROM warehouses WHERE organization_id = :organization_id AND id = :id
            FOR UPDATE
        """),
        {"organization_id": organization_id, "id": warehouse_id},
    ).mappings().first()
    return dict(row) if row is not None else None


def has_stock(db: Session, organization_id: UUID, warehouse_id: UUID) -> bool:
    return bool(db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM stock_balances
                WHERE organization_id = :organization_id AND warehouse_id = :warehouse_id
                  AND quantity_base > 0
            )
        """),
        {"organization_id": organization_id, "warehouse_id": warehouse_id},
    ).scalar_one())
