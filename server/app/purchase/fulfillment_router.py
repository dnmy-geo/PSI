from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.purchase import fulfillment_repository as repository
from app.purchase import fulfillment_service as service
from app.purchase.fulfillment_schemas import ReceiptRead, ReceiptWrite, ReturnRead, ReturnWrite, ReverseWrite

router = APIRouter(prefix="/api/purchase", tags=["purchase"])


@router.get("/receipts", response_model=list[ReceiptRead])
def list_receipts(response: Response,
                  purchase_order_id: UUID | None = None,
                  limit: int = Query(default=100, ge=1, le=500),
                  offset: int = Query(default=0, ge=0),
                  user: CurrentUser = Depends(require_permission("purchase.receipts", "view")),
                  db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_receipts(db, user.organization_id, purchase_order_id, limit, offset, response)


@router.get("/receipts/{receipt_id}", response_model=ReceiptRead)
def get_receipt(receipt_id: UUID,
                user: CurrentUser = Depends(require_permission("purchase.receipts", "view")),
                db: Session = Depends(get_db)) -> dict:
    result = repository.get_receipt(db, user.organization_id, receipt_id)
    if result is None:
        raise HTTPException(status_code=404, detail="入库单不存在")
    return result


@router.post("/receipts", response_model=ReceiptRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_receipt(payload: ReceiptWrite,
                   user: CurrentUser = Depends(require_permission("purchase.receipts", "create")),
                   db: Session = Depends(get_db)) -> dict:
    return service.create_receipt(db, user.organization_id, user.id, payload)


@router.put("/receipts/{receipt_id}", response_model=ReceiptRead,
            dependencies=[Depends(require_csrf)])
def update_receipt(receipt_id: UUID, payload: ReceiptWrite,
                   user: CurrentUser = Depends(require_permission("purchase.receipts", "update")),
                   db: Session = Depends(get_db)) -> dict:
    return service.update_receipt(db, user.organization_id, user.id, receipt_id, payload)


@router.delete("/receipts/{receipt_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_receipt(receipt_id: UUID,
                   user: CurrentUser = Depends(require_permission("purchase.receipts", "delete")),
                   db: Session = Depends(get_db)) -> None:
    service.delete_receipt(db, user.organization_id, user.id, receipt_id)


@router.post("/receipts/{receipt_id}/post", response_model=ReceiptRead,
             dependencies=[Depends(require_csrf)])
def post_receipt(receipt_id: UUID,
                 user: CurrentUser = Depends(require_permission("purchase.receipts", "post")),
                 db: Session = Depends(get_db)) -> dict:
    return service.post_receipt(db, user.organization_id, user.id, receipt_id)


@router.post("/receipts/{receipt_id}/reverse", response_model=ReceiptRead,
             dependencies=[Depends(require_csrf)])
def reverse_receipt(receipt_id: UUID, payload: ReverseWrite,
                    user: CurrentUser = Depends(require_permission("purchase.receipts", "reverse")),
                    db: Session = Depends(get_db)) -> dict:
    return service.reverse_receipt(db, user.organization_id, user.id,
                                   receipt_id, payload.reason)


@router.get("/returns", response_model=list[ReturnRead])
def list_returns(response: Response,
                 original_receipt_id: UUID | None = None,
                 limit: int = Query(default=100, ge=1, le=500),
                 offset: int = Query(default=0, ge=0),
                 user: CurrentUser = Depends(require_permission("purchase.returns", "view")),
                 db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_returns(db, user.organization_id, original_receipt_id, limit, offset, response)


@router.get("/returns/{return_id}", response_model=ReturnRead)
def get_return(return_id: UUID,
               user: CurrentUser = Depends(require_permission("purchase.returns", "view")),
               db: Session = Depends(get_db)) -> dict:
    result = repository.get_return(db, user.organization_id, return_id)
    if result is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    return result


@router.post("/returns", response_model=ReturnRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_return(payload: ReturnWrite,
                  user: CurrentUser = Depends(require_permission("purchase.returns", "create")),
                  db: Session = Depends(get_db)) -> dict:
    return service.create_return(db, user.organization_id, user.id, payload)


@router.put("/returns/{return_id}", response_model=ReturnRead,
            dependencies=[Depends(require_csrf)])
def update_return(return_id: UUID, payload: ReturnWrite,
                  user: CurrentUser = Depends(require_permission("purchase.returns", "update")),
                  db: Session = Depends(get_db)) -> dict:
    return service.update_return(db, user.organization_id, user.id, return_id, payload)


@router.delete("/returns/{return_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_return(return_id: UUID,
                  user: CurrentUser = Depends(require_permission("purchase.returns", "delete")),
                  db: Session = Depends(get_db)) -> None:
    service.delete_return(db, user.organization_id, user.id, return_id)


@router.post("/returns/{return_id}/post", response_model=ReturnRead,
             dependencies=[Depends(require_csrf)])
def post_return(return_id: UUID,
                user: CurrentUser = Depends(require_permission("purchase.returns", "post")),
                db: Session = Depends(get_db)) -> dict:
    return service.post_return(db, user.organization_id, user.id, return_id)


@router.post("/returns/{return_id}/reverse", response_model=ReturnRead,
             dependencies=[Depends(require_csrf)])
def reverse_return(return_id: UUID, payload: ReverseWrite,
                   user: CurrentUser = Depends(require_permission("purchase.returns", "reverse")),
                   db: Session = Depends(get_db)) -> dict:
    return service.reverse_return(db, user.organization_id, user.id,
                                  return_id, payload.reason)
