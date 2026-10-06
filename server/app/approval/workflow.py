"""Approval instances and task decisions, in the document transaction."""

from uuid import UUID

from fastapi import HTTPException, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.approval import repository
from app.core.pagination import paginate
from app.core.security import CurrentUser, has_permission


def start_approval(db: Session, organization_id: UUID, document_type: str,
                   document_id: UUID, submitted_by: UUID) -> UUID:
    """Snapshot configured steps. Caller locks its document and commits."""
    config = repository.get_config(db, organization_id, document_type)
    if config is None or not config["is_enabled"] or not config["steps"]:
        raise HTTPException(status_code=409, detail="审批配置不可用或未启用")
    for step in config["steps"]:
        if step["approver_user_id"] is not None:
            available = db.execute(text("""
                SELECT is_active FROM users WHERE id = :id AND organization_id = :org
            """), {"id": step["approver_user_id"],
                   "org": organization_id}).scalar_one_or_none()
        else:
            available = db.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM roles r JOIN user_roles ur ON ur.role_id = r.id
                    JOIN users u ON u.id = ur.user_id
                    WHERE r.id = :id AND r.organization_id = :org
                      AND r.is_active AND u.is_active
                )
            """), {"id": step["approver_role_id"],
                   "org": organization_id}).scalar_one()
        if not available:
            raise HTTPException(status_code=409, detail="审批步骤没有可用审批人")
    instance_id = db.execute(text("""
        INSERT INTO approval_instances (
            organization_id, config_id, config_version, document_type,
            document_id, submitted_by
        ) VALUES (:org, :config_id, :version, :document_type,
                  :document_id, :submitted_by) RETURNING id
    """), {"org": organization_id, "config_id": config["id"],
           "version": config["version"], "document_type": document_type,
           "document_id": document_id, "submitted_by": submitted_by}).scalar_one()
    for step in config["steps"]:
        db.execute(text("""
            INSERT INTO approval_tasks (
                instance_id, step_no, approver_role_id, approver_user_id
            ) VALUES (:instance_id, :step_no, :role_id, :user_id)
        """), {"instance_id": instance_id, "step_no": step["step_no"],
               "role_id": step["approver_role_id"],
               "user_id": step["approver_user_id"]})
    return instance_id


def get_instance(db: Session, organization_id: UUID, instance_id: UUID) -> dict | None:
    row = db.execute(text("""
        SELECT id, organization_id, config_id, config_version, document_type,
               document_id, status, current_step_no, submitted_by,
               submitted_at, finished_at
        FROM approval_instances WHERE id = :id AND organization_id = :org
    """), {"id": instance_id, "org": organization_id}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["tasks"] = [dict(task) for task in db.execute(text("""
        SELECT id, step_no, approver_role_id, approver_user_id, acted_by,
               status, opinion, created_at, acted_at
        FROM approval_tasks WHERE instance_id = :id ORDER BY step_no
    """), {"id": instance_id}).mappings()]
    return result


def list_document_instances(db: Session, organization_id: UUID, document_type: str,
                            document_id: UUID) -> list[dict]:
    ids = list(db.execute(text("""
        SELECT id FROM approval_instances
        WHERE organization_id = :org AND document_type = :document_type
          AND document_id = :document_id ORDER BY submitted_at DESC, id DESC
    """), {"org": organization_id, "document_type": document_type,
           "document_id": document_id}).scalars())
    return [instance for instance_id in ids
            if (instance := get_instance(db, organization_id, instance_id)) is not None]


def list_my_tasks(db: Session, organization_id: UUID, actor_id: UUID,
                  limit: int, offset: int, response: Response | None = None) -> list[dict]:
    query = """
        SELECT t.id, t.instance_id, t.step_no, t.approver_role_id,
               t.approver_user_id, t.status, t.created_at,
               i.document_type, i.document_id, i.submitted_at
        FROM approval_tasks t JOIN approval_instances i ON i.id = t.instance_id
        WHERE i.organization_id = :org AND i.status = 'pending'
          AND i.current_step_no = t.step_no AND t.status = 'pending'
          AND (t.approver_user_id = :actor OR EXISTS (
              SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
              WHERE ur.user_id = :actor AND ur.role_id = t.approver_role_id
                AND r.organization_id = :org AND r.is_active
          ))
        ORDER BY i.submitted_at, t.id
    """
    return paginate(db, query, {"org": organization_id, "actor": actor_id},
                    limit=limit, offset=offset, response=response)


def decide_task(db: Session, user: CurrentUser,
                task_id: UUID, decision: str, opinion: str | None) -> dict:
    organization_id = user.organization_id
    actor_id = user.id
    if decision == "reject" and not (opinion or "").strip():
        raise HTTPException(status_code=422, detail="驳回时必须填写意见")
    task_ref = db.execute(text("""
        SELECT t.instance_id FROM approval_tasks t
        JOIN approval_instances i ON i.id = t.instance_id
        WHERE t.id = :id AND i.organization_id = :org
    """), {"id": task_id, "org": organization_id}).scalar_one_or_none()
    if task_ref is None:
        raise HTTPException(status_code=404, detail="审批任务不存在")
    instance = db.execute(text("""
        SELECT id, document_type, document_id, status, current_step_no
        FROM approval_instances WHERE id = :id AND organization_id = :org FOR UPDATE
    """), {"id": task_ref, "org": organization_id}).mappings().one()
    task = db.execute(text("""
        SELECT id, step_no, approver_role_id, approver_user_id, status
        FROM approval_tasks WHERE id = :id AND instance_id = :instance_id FOR UPDATE
    """), {"id": task_id, "instance_id": task_ref}).mappings().one()
    if instance["status"] != "pending" or task["status"] != "pending" or \
            task["step_no"] != instance["current_step_no"]:
        raise HTTPException(status_code=409, detail="该审批任务不是当前步骤")
    if task["approver_user_id"] is not None:
        authorized = task["approver_user_id"] == actor_id
    else:
        authorized = bool(db.execute(text("""
            SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :actor AND ur.role_id = :role_id
              AND r.organization_id = :org AND r.is_active LIMIT 1
        """), {"actor": actor_id, "role_id": task["approver_role_id"],
               "org": organization_id}).scalar_one_or_none())
    if not authorized:
        raise HTTPException(status_code=403, detail="您不是该步骤的审批人")
    menu_code = {"sales_order": "sales.orders", "stocktake": "inventory.stocktakes"}.get(
        instance["document_type"])
    if menu_code is None:
        raise HTTPException(status_code=409, detail="该单据类型不支持审批")
    if not has_permission(db, user, menu_code, "approve"):
        raise HTTPException(status_code=403, detail="没有该单据的审批权限")
    db.execute(text("""
        UPDATE approval_tasks SET status = :status, acted_by = :actor,
            opinion = :opinion, acted_at = now() WHERE id = :id
    """), {"id": task_id, "status": "approved" if decision == "approve" else "rejected",
           "actor": actor_id, "opinion": opinion.strip() if opinion else None})
    if decision == "reject":
        db.execute(text("""
            UPDATE approval_tasks SET status = 'skipped'
            WHERE instance_id = :instance_id AND step_no > :step_no AND status = 'pending'
        """), {"instance_id": task_ref, "step_no": task["step_no"]})
        new_status = "rejected"
    else:
        more = db.execute(text("""
            SELECT EXISTS (SELECT 1 FROM approval_tasks
                           WHERE instance_id = :instance_id AND step_no > :step_no)
        """), {"instance_id": task_ref, "step_no": task["step_no"]}).scalar_one()
        new_status = "pending" if more else "approved"
    if new_status == "pending":
        db.execute(text("""
            UPDATE approval_instances SET current_step_no = current_step_no + 1
            WHERE id = :id
        """), {"id": task_ref})
    else:
        db.execute(text("""
            UPDATE approval_instances SET status = :status, finished_at = now()
            WHERE id = :id
        """), {"id": task_ref, "status": new_status})
        if instance["document_type"] == "sales_order":
            updated = db.execute(text("""
                UPDATE sales_orders SET status = :status, updated_at = now()
                WHERE id = :id AND organization_id = :org AND status = 'pending_approval'
            """), {"id": instance["document_id"], "org": organization_id,
                   "status": new_status}).rowcount
            if updated != 1:
                raise HTTPException(status_code=409, detail="销售订单的审批状态已变化，请刷新重试")
        else:
            from app.inventory.stocktake import finish_stocktake_approval
            finish_stocktake_approval(db, organization_id, actor_id,
                                      instance["document_id"], new_status)
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, :action, :document_type, :document_id, :opinion)
    """), {"org": organization_id, "actor": actor_id,
           "action": f"approval.{decision}",
           "document_type": instance["document_type"],
           "document_id": instance["document_id"], "opinion": opinion})
    result = get_instance(db, organization_id, task_ref)
    db.commit()
    assert result is not None
    return result
