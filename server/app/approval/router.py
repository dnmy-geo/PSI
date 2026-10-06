from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.approval import repository, service
from app.approval import workflow
from app.approval.schemas import (ApprovalConfigRead, ApprovalConfigWrite, ApprovalDecision,
                                  ApprovalInstanceRead, ApprovalTaskRead, DocumentType)
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, has_permission, require_csrf, require_permission

router = APIRouter(prefix="/api/approval", tags=["approval"])


@router.get("/configs", response_model=list[ApprovalConfigRead])
def list_configs(user: CurrentUser = Depends(require_permission("system.approvals", "view")),
                 db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_configs(db, user.organization_id)


@router.get("/configs/{document_type}", response_model=ApprovalConfigRead)
def get_config(document_type: DocumentType, user: CurrentUser = Depends(require_permission("system.approvals", "view")),
               db: Session = Depends(get_db)) -> dict:
    result = repository.get_config(db, user.organization_id, document_type)
    if result is None:
        raise HTTPException(status_code=404, detail="审批配置不存在")
    return result


@router.put("/configs/{document_type}", response_model=ApprovalConfigRead,
            dependencies=[Depends(require_csrf)])
def save_config(document_type: DocumentType, payload: ApprovalConfigWrite,
                user: CurrentUser = Depends(require_permission("system.approvals", "update")), db: Session = Depends(get_db)) -> dict:
    return service.save_config(db, user.organization_id, user.id, document_type, payload)


@router.get("/tasks/mine", response_model=list[ApprovalTaskRead])
def my_tasks(response: Response,
             limit: int = Query(default=100, ge=1, le=500),
             offset: int = Query(default=0, ge=0),
             user: CurrentUser = Depends(get_current_user),
             db: Session = Depends(get_db)) -> list[dict]:
    return workflow.list_my_tasks(db, user.organization_id, user.id, limit, offset, response)


@router.post("/tasks/{task_id}/decision", response_model=ApprovalInstanceRead,
             dependencies=[Depends(require_csrf)])
def decide_task(task_id: UUID, payload: ApprovalDecision,
                user: CurrentUser = Depends(get_current_user),
                db: Session = Depends(get_db)) -> dict:
    return workflow.decide_task(db, user, task_id, payload.decision, payload.opinion)


@router.get("/instances/{instance_id}", response_model=ApprovalInstanceRead)
def get_instance(instance_id: UUID, user: CurrentUser = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> dict:
    result = workflow.get_instance(db, user.organization_id, instance_id)
    if result is None:
        raise HTTPException(status_code=404, detail="审批实例不存在")
    menu_code = "sales.orders" if result["document_type"] == "sales_order" else "inventory.stocktakes"
    if not has_permission(db, user, menu_code, "view"):
        raise HTTPException(status_code=403, detail="没有权限")
    return result


@router.get("/documents/{document_type}/{document_id}/instances",
            response_model=list[ApprovalInstanceRead])
def document_instances(document_type: DocumentType, document_id: UUID,
                       user: CurrentUser = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> list[dict]:
    menu_code = "sales.orders" if document_type == "sales_order" else "inventory.stocktakes"
    if not has_permission(db, user, menu_code, "view"):
        raise HTTPException(status_code=403, detail="没有权限")
    return workflow.list_document_instances(db, user.organization_id,
                                            document_type, document_id)
