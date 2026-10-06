from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.production import operations_repository as repository
from app.production import operations_service as service
from app.production.operations_schemas import (ConsumptionRead, ConsumptionWrite,
                                                IssueRead, IssueWrite, ReceiptRead,
                                                ReceiptWrite, ReverseRequest)

router = APIRouter(prefix="/api/production", tags=["production"])


@router.get("/issues", response_model=list[IssueRead])
def list_issues(response: Response, production_order_id: UUID | None = None,
                limit: int = Query(default=100, ge=1, le=500),
                offset: int = Query(default=0, ge=0),
                user: CurrentUser = Depends(require_permission("production.issues", "view")),
                db: Session = Depends(get_db)) -> list[dict]:
    ids = repository.list_documents(db, user.organization_id, "production_issues",
                                    production_order_id, limit, offset, response)
    return [item for row in ids
            if (item := repository.get_issue(db, user.organization_id, row["id"])) is not None]


@router.get("/issues/{issue_id}", response_model=IssueRead)
def get_issue(issue_id: UUID,
              user: CurrentUser = Depends(require_permission("production.issues", "view")),
              db: Session = Depends(get_db)) -> dict:
    result = repository.get_issue(db, user.organization_id, issue_id)
    if result is None:
        raise HTTPException(status_code=404, detail="生产领料单不存在")
    return result


@router.post("/issues", response_model=IssueRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_issue(payload: IssueWrite,
                 user: CurrentUser = Depends(require_permission("production.issues", "create")),
                 db: Session = Depends(get_db)) -> dict:
    return service.create_issue(db, user.organization_id, user.id, payload)


@router.put("/issues/{issue_id}", response_model=IssueRead,
            dependencies=[Depends(require_csrf)])
def update_issue(issue_id: UUID, payload: IssueWrite,
                 user: CurrentUser = Depends(require_permission("production.issues", "update")),
                 db: Session = Depends(get_db)) -> dict:
    return service.update_issue(db, user.organization_id, user.id, issue_id, payload)


@router.delete("/issues/{issue_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_issue(issue_id: UUID,
                 user: CurrentUser = Depends(require_permission("production.issues", "delete")),
                 db: Session = Depends(get_db)) -> None:
    service.delete_issue(db, user.organization_id, user.id, issue_id)


@router.post("/issues/{issue_id}/post", response_model=IssueRead,
             dependencies=[Depends(require_csrf)])
def post_issue(issue_id: UUID,
               user: CurrentUser = Depends(require_permission("production.issues", "post")),
               db: Session = Depends(get_db)) -> dict:
    return service.post_issue(db, user.organization_id, user.id, issue_id)


@router.post("/issues/{issue_id}/reverse", response_model=IssueRead,
             dependencies=[Depends(require_csrf)])
def reverse_issue(issue_id: UUID, payload: ReverseRequest,
                  user: CurrentUser = Depends(require_permission("production.issues", "reverse")),
                  db: Session = Depends(get_db)) -> dict:
    return service.reverse_issue(db, user.organization_id, user.id,
                                 issue_id, payload.reason)


@router.get("/consumptions", response_model=list[ConsumptionRead])
def list_consumptions(response: Response, production_order_id: UUID | None = None,
                      limit: int = Query(default=100, ge=1, le=500),
                      offset: int = Query(default=0, ge=0),
                      user: CurrentUser = Depends(require_permission("production.consumptions", "view")),
                      db: Session = Depends(get_db)) -> list[dict]:
    ids = repository.list_documents(db, user.organization_id, "production_consumptions",
                                    production_order_id, limit, offset, response)
    return [item for row in ids
            if (item := repository.get_consumption(db, user.organization_id, row["id"])) is not None]


@router.get("/consumptions/{consumption_id}", response_model=ConsumptionRead)
def get_consumption(consumption_id: UUID,
                    user: CurrentUser = Depends(require_permission("production.consumptions", "view")),
                    db: Session = Depends(get_db)) -> dict:
    result = repository.get_consumption(db, user.organization_id, consumption_id)
    if result is None:
        raise HTTPException(status_code=404, detail="生产消耗单不存在")
    return result


@router.post("/consumptions", response_model=ConsumptionRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_consumption(payload: ConsumptionWrite,
                       user: CurrentUser = Depends(require_permission("production.consumptions", "create")),
                       db: Session = Depends(get_db)) -> dict:
    return service.create_consumption(db, user.organization_id, user.id, payload)


@router.put("/consumptions/{consumption_id}", response_model=ConsumptionRead,
            dependencies=[Depends(require_csrf)])
def update_consumption(consumption_id: UUID, payload: ConsumptionWrite,
                       user: CurrentUser = Depends(require_permission("production.consumptions", "update")),
                       db: Session = Depends(get_db)) -> dict:
    return service.update_consumption(db, user.organization_id, user.id,
                                      consumption_id, payload)


@router.delete("/consumptions/{consumption_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_consumption(consumption_id: UUID,
                       user: CurrentUser = Depends(require_permission("production.consumptions", "delete")),
                       db: Session = Depends(get_db)) -> None:
    service.delete_consumption(db, user.organization_id, user.id, consumption_id)


@router.post("/consumptions/{consumption_id}/post", response_model=ConsumptionRead,
             dependencies=[Depends(require_csrf)])
def post_consumption(consumption_id: UUID,
                     user: CurrentUser = Depends(require_permission("production.consumptions", "post")),
                     db: Session = Depends(get_db)) -> dict:
    return service.post_consumption(db, user.organization_id, user.id, consumption_id)


@router.post("/consumptions/{consumption_id}/reverse", response_model=ConsumptionRead,
             dependencies=[Depends(require_csrf)])
def reverse_consumption(consumption_id: UUID, payload: ReverseRequest,
                        user: CurrentUser = Depends(require_permission("production.consumptions", "reverse")),
                        db: Session = Depends(get_db)) -> dict:
    return service.reverse_consumption(db, user.organization_id, user.id,
                                       consumption_id, payload.reason)


@router.get("/receipts", response_model=list[ReceiptRead])
def list_receipts(response: Response, production_order_id: UUID | None = None,
                  limit: int = Query(default=100, ge=1, le=500),
                  offset: int = Query(default=0, ge=0),
                  user: CurrentUser = Depends(require_permission("production.receipts", "view")),
                  db: Session = Depends(get_db)) -> list[dict]:
    ids = repository.list_documents(db, user.organization_id, "production_receipts",
                                    production_order_id, limit, offset, response)
    return [item for row in ids
            if (item := repository.get_receipt(db, user.organization_id, row["id"])) is not None]


@router.get("/receipts/{receipt_id}", response_model=ReceiptRead)
def get_receipt(receipt_id: UUID,
                user: CurrentUser = Depends(require_permission("production.receipts", "view")),
                db: Session = Depends(get_db)) -> dict:
    result = repository.get_receipt(db, user.organization_id, receipt_id)
    if result is None:
        raise HTTPException(status_code=404, detail="生产入库单不存在")
    return result


@router.post("/receipts", response_model=ReceiptRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_receipt(payload: ReceiptWrite,
                   user: CurrentUser = Depends(require_permission("production.receipts", "create")),
                   db: Session = Depends(get_db)) -> dict:
    return service.create_receipt(db, user.organization_id, user.id, payload)


@router.put("/receipts/{receipt_id}", response_model=ReceiptRead,
            dependencies=[Depends(require_csrf)])
def update_receipt(receipt_id: UUID, payload: ReceiptWrite,
                   user: CurrentUser = Depends(require_permission("production.receipts", "update")),
                   db: Session = Depends(get_db)) -> dict:
    return service.update_receipt(db, user.organization_id, user.id, receipt_id, payload)


@router.delete("/receipts/{receipt_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_receipt(receipt_id: UUID,
                   user: CurrentUser = Depends(require_permission("production.receipts", "delete")),
                   db: Session = Depends(get_db)) -> None:
    service.delete_receipt(db, user.organization_id, user.id, receipt_id)


@router.post("/receipts/{receipt_id}/post", response_model=ReceiptRead,
             dependencies=[Depends(require_csrf)])
def post_receipt(receipt_id: UUID,
                 user: CurrentUser = Depends(require_permission("production.receipts", "post")),
                 db: Session = Depends(get_db)) -> dict:
    return service.post_receipt(db, user.organization_id, user.id, receipt_id)


@router.post("/receipts/{receipt_id}/reverse", response_model=ReceiptRead,
             dependencies=[Depends(require_csrf)])
def reverse_receipt(receipt_id: UUID, payload: ReverseRequest,
                    user: CurrentUser = Depends(require_permission("production.receipts", "reverse")),
                    db: Session = Depends(get_db)) -> dict:
    return service.reverse_receipt(db, user.organization_id, user.id,
                                   receipt_id, payload.reason)
