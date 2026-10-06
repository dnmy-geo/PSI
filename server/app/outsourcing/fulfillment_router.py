from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.outsourcing import fulfillment_repository as repository
from app.outsourcing import fulfillment_service as service
from app.outsourcing.fulfillment_schemas import (IssueRead, IssueWrite,
                                                  ReceiptRead, ReceiptWrite, ReverseWrite)

router = APIRouter(prefix="/api/outsourcing", tags=["outsourcing"])


def _get(db: Session, org: UUID, kind: str, doc_id: UUID) -> dict:
    result = repository.get_document(db, org, kind, doc_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"outsourcing {kind} not found")
    return result


@router.get("/issues", response_model=list[IssueRead])
def list_issues(response: Response, outsourcing_order_id: UUID | None = None,
                limit: int = Query(default=100, ge=1, le=500),
                offset: int = Query(default=0, ge=0),
                user: CurrentUser = Depends(require_permission("outsourcing.issues", "view")),
                db: Session = Depends(get_db)) -> list[dict]:
    return [_get(db, user.organization_id, "issue", row["id"])
            for row in repository.list_document_ids(
                db, user.organization_id, "issue", outsourcing_order_id, limit, offset, response)]


@router.get("/issues/{doc_id}", response_model=IssueRead)
def get_issue(doc_id: UUID,
              user: CurrentUser = Depends(require_permission("outsourcing.issues", "view")),
              db: Session = Depends(get_db)) -> dict:
    return _get(db, user.organization_id, "issue", doc_id)


@router.post("/issues", response_model=IssueRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_issue(payload: IssueWrite,
                 user: CurrentUser = Depends(require_permission("outsourcing.issues", "create")),
                 db: Session = Depends(get_db)) -> dict:
    return service.create_document(db, user.organization_id, user.id, "issue", payload)


@router.put("/issues/{doc_id}", response_model=IssueRead,
            dependencies=[Depends(require_csrf)])
def update_issue(doc_id: UUID, payload: IssueWrite,
                 user: CurrentUser = Depends(require_permission("outsourcing.issues", "update")),
                 db: Session = Depends(get_db)) -> dict:
    return service.update_document(db, user.organization_id, user.id,
                                   "issue", doc_id, payload)


@router.delete("/issues/{doc_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_issue(doc_id: UUID,
                 user: CurrentUser = Depends(require_permission("outsourcing.issues", "delete")),
                 db: Session = Depends(get_db)) -> None:
    service.delete_document(db, user.organization_id, user.id, "issue", doc_id)


@router.post("/issues/{doc_id}/post", response_model=IssueRead,
             dependencies=[Depends(require_csrf)])
def post_issue(doc_id: UUID,
               user: CurrentUser = Depends(require_permission("outsourcing.issues", "post")),
               db: Session = Depends(get_db)) -> dict:
    return service.post_document(db, user.organization_id, user.id, "issue", doc_id)


@router.post("/issues/{doc_id}/reverse", response_model=IssueRead,
             dependencies=[Depends(require_csrf)])
def reverse_issue(doc_id: UUID, payload: ReverseWrite,
                  user: CurrentUser = Depends(require_permission("outsourcing.issues", "reverse")),
                  db: Session = Depends(get_db)) -> dict:
    return service.reverse_document(db, user.organization_id, user.id,
                                    "issue", doc_id, payload.reason)


@router.get("/receipts", response_model=list[ReceiptRead])
def list_receipts(response: Response, outsourcing_order_id: UUID | None = None,
                  limit: int = Query(default=100, ge=1, le=500),
                  offset: int = Query(default=0, ge=0),
                  user: CurrentUser = Depends(require_permission("outsourcing.receipts", "view")),
                  db: Session = Depends(get_db)) -> list[dict]:
    return [_get(db, user.organization_id, "receipt", row["id"])
            for row in repository.list_document_ids(
                db, user.organization_id, "receipt", outsourcing_order_id, limit, offset, response)]


@router.get("/receipts/{doc_id}", response_model=ReceiptRead)
def get_receipt(doc_id: UUID,
                user: CurrentUser = Depends(require_permission("outsourcing.receipts", "view")),
                db: Session = Depends(get_db)) -> dict:
    return _get(db, user.organization_id, "receipt", doc_id)


@router.post("/receipts", response_model=ReceiptRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_receipt(payload: ReceiptWrite,
                   user: CurrentUser = Depends(require_permission("outsourcing.receipts", "create")),
                   db: Session = Depends(get_db)) -> dict:
    return service.create_document(db, user.organization_id, user.id, "receipt", payload)


@router.put("/receipts/{doc_id}", response_model=ReceiptRead,
            dependencies=[Depends(require_csrf)])
def update_receipt(doc_id: UUID, payload: ReceiptWrite,
                   user: CurrentUser = Depends(require_permission("outsourcing.receipts", "update")),
                   db: Session = Depends(get_db)) -> dict:
    return service.update_document(db, user.organization_id, user.id,
                                   "receipt", doc_id, payload)


@router.delete("/receipts/{doc_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_receipt(doc_id: UUID,
                   user: CurrentUser = Depends(require_permission("outsourcing.receipts", "delete")),
                   db: Session = Depends(get_db)) -> None:
    service.delete_document(db, user.organization_id, user.id, "receipt", doc_id)


@router.post("/receipts/{doc_id}/post", response_model=ReceiptRead,
             dependencies=[Depends(require_csrf)])
def post_receipt(doc_id: UUID,
                 user: CurrentUser = Depends(require_permission("outsourcing.receipts", "post")),
                 db: Session = Depends(get_db)) -> dict:
    return service.post_document(db, user.organization_id, user.id, "receipt", doc_id)


@router.post("/receipts/{doc_id}/reverse", response_model=ReceiptRead,
             dependencies=[Depends(require_csrf)])
def reverse_receipt(doc_id: UUID, payload: ReverseWrite,
                    user: CurrentUser = Depends(require_permission("outsourcing.receipts", "reverse")),
                    db: Session = Depends(get_db)) -> dict:
    return service.reverse_document(db, user.organization_id, user.id,
                                    "receipt", doc_id, payload.reason)
