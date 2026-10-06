"""Read-only, organization-scoped audit log queries."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.pagination import paginate
from app.core.security import CurrentUser, require_permission
from app.system.audit_labels import document_labels

router = APIRouter(prefix="/api/system/audit-logs", tags=["system"])


class AuditLogRead(BaseModel):
    id: UUID
    actor_id: UUID | None
    actor_name: str | None
    action_code: str
    document_type: str | None
    document_id: UUID | None
    # 单据单号（组织/岗位/菜单显示编码，账号显示用户名）；解析不到时为 None，前端回退显示 UUID。
    document_label: str | None = None
    reason: str | None
    change_summary: dict[str, Any] | None
    occurred_at: datetime


@router.get("", response_model=list[AuditLogRead])
def list_audit_logs(response: Response,
                    actor_id: UUID | None = None,
                    document_type: str | None = None,
                    document_id: UUID | None = None,
                    action_code: str | None = None,
                    occurred_from: datetime | None = None,
                    occurred_to: datetime | None = None,
                    limit: int = Query(default=100, ge=1, le=500),
                    offset: int = Query(default=0, ge=0),
                    user: CurrentUser = Depends(require_permission("system.audit_logs", "view")),
                    db: Session = Depends(get_db)) -> list[dict]:
    if any(value is not None and value.tzinfo is None
           for value in (occurred_from, occurred_to)):
        raise HTTPException(status_code=422, detail="审计时间筛选必须包含时区")
    if occurred_from and occurred_to and occurred_to <= occurred_from:
        raise HTTPException(status_code=422, detail="操作结束时间必须晚于开始时间")
    query = """
        SELECT l.id, l.actor_id, u.display_name AS actor_name, l.action_code,
               l.document_type, l.document_id, l.reason, l.change_summary,
               l.occurred_at
        FROM audit_logs l LEFT JOIN users u ON u.id = l.actor_id
        WHERE l.organization_id = :org
          AND (CAST(:actor AS uuid) IS NULL OR l.actor_id = :actor)
          AND (CAST(:document_type AS text) IS NULL
               OR l.document_type = :document_type)
          AND (CAST(:document_id AS uuid) IS NULL OR l.document_id = :document_id)
          AND (CAST(:action_code AS text) IS NULL OR l.action_code = :action_code)
          AND (CAST(:occurred_from AS timestamptz) IS NULL
               OR l.occurred_at >= :occurred_from)
          AND (CAST(:occurred_to AS timestamptz) IS NULL
               OR l.occurred_at < :occurred_to)
        ORDER BY l.occurred_at DESC, l.id DESC
    """
    rows = paginate(db, query, {"org": user.organization_id, "actor": actor_id,
                                "document_type": document_type, "document_id": document_id,
                                "action_code": action_code, "occurred_from": occurred_from,
                                "occurred_to": occurred_to},
                    limit=limit, offset=offset, response=response)
    labels = document_labels(db, user.organization_id, rows)
    for row in rows:
        row["document_label"] = labels.get(row["document_id"]) if row["document_id"] else None
    return rows
