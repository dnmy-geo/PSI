from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_organization(db: Session, organization_id: UUID) -> dict:
    return dict(db.execute(text("""
        SELECT id, code, name, is_active FROM organizations WHERE id = :id
    """), {"id": organization_id}).mappings().one())


def get_department(db: Session, organization_id: UUID, department_id: UUID) -> dict | None:
    row = db.execute(text("""
        SELECT id, organization_id, code, name, parent_id, is_active, created_at, updated_at
        FROM departments WHERE id = :id AND organization_id = :org
    """), {"id": department_id, "org": organization_id}).mappings().first()
    return dict(row) if row is not None else None


def list_departments(db: Session, organization_id: UUID) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT id, organization_id, code, name, parent_id, is_active, created_at, updated_at
        FROM departments WHERE organization_id = :org ORDER BY created_at DESC, code
    """), {"org": organization_id}).mappings()]


def get_role(db: Session, organization_id: UUID, role_id: UUID) -> dict | None:
    row = db.execute(text("""
        SELECT id, organization_id, code, name, is_active, created_at, updated_at
        FROM roles WHERE id = :id AND organization_id = :org
    """), {"id": role_id, "org": organization_id}).mappings().first()
    return dict(row) if row is not None else None


def list_roles(db: Session, organization_id: UUID) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT id, organization_id, code, name, is_active, created_at, updated_at
        FROM roles WHERE organization_id = :org ORDER BY created_at DESC, code
    """), {"org": organization_id}).mappings()]


def get_user(db: Session, organization_id: UUID, user_id: UUID) -> dict | None:
    row = db.execute(text("""
        SELECT id, organization_id, username, display_name, department_id, is_active,
               created_at, updated_at
        FROM users WHERE id = :id AND organization_id = :org
    """), {"id": user_id, "org": organization_id}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["role_ids"] = list(db.execute(text("""
        SELECT ur.role_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = :id AND r.organization_id = :org ORDER BY r.code
    """), {"id": user_id, "org": organization_id}).scalars())
    return result


def list_users(db: Session, organization_id: UUID) -> list[dict]:
    ids = db.execute(text("""
        SELECT id FROM users WHERE organization_id = :org ORDER BY created_at DESC, username
    """), {"org": organization_id}).scalars()
    return [user for user_id in ids if (user := get_user(db, organization_id, user_id)) is not None]
