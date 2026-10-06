from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_category(db: Session, organization_id: UUID, category_id: UUID) -> dict | None:
    row = db.execute(
        text("""
            SELECT id, organization_id, code, name, parent_id, created_at, updated_at
            FROM item_categories WHERE organization_id = :org AND id = :id
        """),
        {"org": organization_id, "id": category_id},
    ).mappings().first()
    return dict(row) if row else None


def list_categories(db: Session, organization_id: UUID) -> list[dict]:
    return [dict(row) for row in db.execute(
        text("""
            SELECT id, organization_id, code, name, parent_id, created_at, updated_at
            FROM item_categories WHERE organization_id = :org ORDER BY created_at DESC, code
        """),
        {"org": organization_id},
    ).mappings()]

