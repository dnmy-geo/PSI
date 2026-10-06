from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.approval import repository
from app.approval.schemas import ApprovalConfigWrite


def _validate_approvers(db: Session, organization_id: UUID,
                        data: ApprovalConfigWrite) -> None:
    for step in data.steps:
        if step.approver_role_id is not None:
            role = db.execute(text("""
                SELECT is_active FROM roles WHERE id = :id AND organization_id = :org
            """), {"id": step.approver_role_id, "org": organization_id}).scalar_one_or_none()
            if not role:
                raise HTTPException(status_code=422, detail="审批岗位不可用")
            has_user = db.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM user_roles ur JOIN users u ON u.id = ur.user_id
                    WHERE ur.role_id = :role_id AND u.organization_id = :org AND u.is_active
                )
            """), {"role_id": step.approver_role_id, "org": organization_id}).scalar_one()
            if data.is_enabled and not has_user:
                raise HTTPException(status_code=422, detail="审批岗位没有可用成员")
        else:
            user = db.execute(text("""
                SELECT is_active FROM users WHERE id = :id AND organization_id = :org
            """), {"id": step.approver_user_id, "org": organization_id}).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=422, detail="审批人不可用")


def save_config(db: Session, organization_id: UUID, actor_id: UUID,
                document_type: str, data: ApprovalConfigWrite) -> dict:
    db.execute(text("SELECT id FROM organizations WHERE id = :id FOR UPDATE"),
               {"id": organization_id}).scalar_one()
    _validate_approvers(db, organization_id, data)
    current = repository.get_config(db, organization_id, document_type)
    if current is None:
        config_id = db.execute(text("""
            INSERT INTO approval_configs (organization_id, document_type, is_enabled)
            VALUES (:org, :document_type, :is_enabled) RETURNING id
        """), {"org": organization_id, "document_type": document_type,
               "is_enabled": data.is_enabled}).scalar_one()
    else:
        config_id = current["id"]
        db.execute(text("""
            UPDATE approval_configs SET is_enabled = :is_enabled, version = version + 1
            WHERE id = :id AND organization_id = :org
        """), {"id": config_id, "org": organization_id,
               "is_enabled": data.is_enabled})
        db.execute(text("DELETE FROM approval_config_steps WHERE config_id = :id"),
                   {"id": config_id})
    for step_no, step in enumerate(data.steps, start=1):
        db.execute(text("""
            INSERT INTO approval_config_steps (
                config_id, step_no, approver_role_id, approver_user_id
            ) VALUES (:config_id, :step_no, :role_id, :user_id)
        """), {"config_id": config_id, "step_no": step_no,
               "role_id": step.approver_role_id, "user_id": step.approver_user_id})
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
        VALUES (:org, :actor, 'approval_config.save', 'approval_config', :id)
    """), {"org": organization_id, "actor": actor_id, "id": config_id})
    result = repository.get_config(db, organization_id, document_type)
    db.commit()
    assert result is not None
    return result
