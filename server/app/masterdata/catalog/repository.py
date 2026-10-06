from collections import defaultdict
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


_UNIT_COLUMNS = ("id, organization_id, code, name, precision_scale, is_active, "
                 "base_unit_id, base_quantity, created_at, updated_at")


def get_unit(db: Session, organization_id: UUID, unit_id: UUID) -> dict | None:
    row = db.execute(
        text(f"""
            SELECT {_UNIT_COLUMNS}
            FROM units WHERE id = :id AND organization_id = :organization_id
        """),
        {"id": unit_id, "organization_id": organization_id},
    ).mappings().first()
    return dict(row) if row else None


def lock_unit(db: Session, organization_id: UUID, unit_id: UUID) -> dict | None:
    row = db.execute(
        text(f"""
            SELECT {_UNIT_COLUMNS}
            FROM units WHERE id = :id AND organization_id = :organization_id FOR UPDATE
        """),
        {"id": unit_id, "organization_id": organization_id},
    ).mappings().first()
    return dict(row) if row else None


def attach_related_units(db: Session, organization_id: UUID, units: list[dict]) -> list[dict]:
    """给每个单位补上「被关联单位」：哪些单位把它当作自己的基本单位。"""
    ids = [unit["id"] for unit in units]
    related: dict[UUID, list[dict]] = defaultdict(list)
    if ids:
        for row in db.execute(
            text("""
                SELECT base_unit_id, id, code, name, base_quantity
                FROM units WHERE organization_id = :org AND base_unit_id = ANY(:ids)
                ORDER BY code
            """),
            {"org": organization_id, "ids": ids},
        ).mappings():
            related[row["base_unit_id"]].append({
                "id": row["id"], "code": row["code"], "name": row["name"],
                "base_quantity": row["base_quantity"],
            })
    for unit in units:
        unit["related_units"] = related[unit["id"]]
    return units


def get_item(db: Session, organization_id: UUID, item_id: UUID) -> dict | None:
    row = db.execute(
        text("""
            SELECT id, organization_id, code, name, item_type, base_unit_id, category_id,
                   is_active, created_at, updated_at
            FROM items WHERE id = :id AND organization_id = :organization_id
        """),
        {"id": item_id, "organization_id": organization_id},
    ).mappings().first()
    return dict(row) if row else None


def lock_item(db: Session, organization_id: UUID, item_id: UUID) -> dict | None:
    row = db.execute(
        text("""
            SELECT id, organization_id, code, name, item_type, base_unit_id, category_id,
                   is_active, created_at, updated_at
            FROM items WHERE id = :id AND organization_id = :organization_id FOR UPDATE
        """),
        {"id": item_id, "organization_id": organization_id},
    ).mappings().first()
    return dict(row) if row else None


def list_units(db: Session, organization_id: UUID) -> list[dict]:
    rows = [dict(row) for row in db.execute(
        text(f"""
            SELECT {_UNIT_COLUMNS}
            FROM units WHERE organization_id = :organization_id ORDER BY created_at DESC, code
        """),
        {"organization_id": organization_id},
    ).mappings()]
    return attach_related_units(db, organization_id, rows)


def list_items(db: Session, organization_id: UUID) -> list[dict]:
    return [dict(row) for row in db.execute(
        text("""
            SELECT id, organization_id, code, name, item_type, base_unit_id, category_id,
                   is_active, created_at, updated_at
            FROM items WHERE organization_id = :organization_id ORDER BY created_at DESC, code
        """),
        {"organization_id": organization_id},
    ).mappings()]
