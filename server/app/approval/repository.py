from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_config(db: Session, organization_id: UUID, document_type: str) -> dict | None:
    row = db.execute(text("""
        SELECT id, organization_id, document_type, is_enabled, version
        FROM approval_configs WHERE organization_id = :org AND document_type = :document_type
    """), {"org": organization_id, "document_type": document_type}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["steps"] = [dict(step) for step in db.execute(text("""
        SELECT id, step_no, approver_role_id, approver_user_id
        FROM approval_config_steps WHERE config_id = :id ORDER BY step_no
    """), {"id": row["id"]}).mappings()]
    return result


def list_configs(db: Session, organization_id: UUID) -> list[dict]:
    types = db.execute(text("""
        SELECT document_type FROM approval_configs
        WHERE organization_id = :org ORDER BY document_type
    """), {"org": organization_id}).scalars()
    return [config for document_type in types
            if (config := get_config(db, organization_id, document_type)) is not None]
