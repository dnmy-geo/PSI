from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.sales import fulfillment_repository as repository
from app.sales import fulfillment_service as service
from app.sales.fulfillment_schemas import ReturnRead, ReturnWrite, ShipmentRead, ShipmentWrite, ReverseWrite

router = APIRouter(prefix="/api/sales", tags=["sales"])


@router.get("/shipments", response_model=list[ShipmentRead])
def list_shipments(response: Response,
                   sales_order_id: UUID | None = None,
                   limit: int = Query(default=100, ge=1, le=500),
                   offset: int = Query(default=0, ge=0),
                   user: CurrentUser = Depends(require_permission("sales.shipments", "view")),
                   db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_shipments(db, user.organization_id, sales_order_id, limit, offset, response)


@router.get("/shipments/{shipment_id}", response_model=ShipmentRead)
def get_shipment(shipment_id: UUID,
                 user: CurrentUser = Depends(require_permission("sales.shipments", "view")),
                 db: Session = Depends(get_db)) -> dict:
    result = repository.get_shipment(db, user.organization_id, shipment_id)
    if result is None:
        raise HTTPException(status_code=404, detail="出库单不存在")
    return result


@router.post("/shipments", response_model=ShipmentRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_shipment(payload: ShipmentWrite,
                    user: CurrentUser = Depends(require_permission("sales.shipments", "create")),
                    db: Session = Depends(get_db)) -> dict:
    return service.create_shipment(db, user.organization_id, user.id, payload)


@router.put("/shipments/{shipment_id}", response_model=ShipmentRead,
            dependencies=[Depends(require_csrf)])
def update_shipment(shipment_id: UUID, payload: ShipmentWrite,
                    user: CurrentUser = Depends(require_permission("sales.shipments", "update")),
                    db: Session = Depends(get_db)) -> dict:
    return service.update_shipment(db, user.organization_id, user.id, shipment_id, payload)


@router.delete("/shipments/{shipment_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_shipment(shipment_id: UUID,
                    user: CurrentUser = Depends(require_permission("sales.shipments", "delete")),
                    db: Session = Depends(get_db)) -> None:
    service.delete_shipment(db, user.organization_id, user.id, shipment_id)


@router.post("/shipments/{shipment_id}/post", response_model=ShipmentRead,
             dependencies=[Depends(require_csrf)])
def post_shipment(shipment_id: UUID,
                  user: CurrentUser = Depends(require_permission("sales.shipments", "post")),
                  db: Session = Depends(get_db)) -> dict:
    return service.post_shipment(db, user.organization_id, user.id, shipment_id)


@router.post("/shipments/{shipment_id}/reverse", response_model=ShipmentRead,
             dependencies=[Depends(require_csrf)])
def reverse_shipment(shipment_id: UUID, payload: ReverseWrite,
                     user: CurrentUser = Depends(require_permission("sales.shipments", "reverse")),
                     db: Session = Depends(get_db)) -> dict:
    return service.reverse_shipment(db, user.organization_id, user.id,
                                    shipment_id, payload.reason)


@router.get("/returns", response_model=list[ReturnRead])
def list_returns(response: Response,
                 original_shipment_id: UUID | None = None,
                 limit: int = Query(default=100, ge=1, le=500),
                 offset: int = Query(default=0, ge=0),
                 user: CurrentUser = Depends(require_permission("sales.returns", "view")),
                 db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_returns(db, user.organization_id, original_shipment_id, limit, offset, response)


@router.get("/returns/{return_id}", response_model=ReturnRead)
def get_return(return_id: UUID,
               user: CurrentUser = Depends(require_permission("sales.returns", "view")),
               db: Session = Depends(get_db)) -> dict:
    result = repository.get_return(db, user.organization_id, return_id)
    if result is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    return result


@router.post("/returns", response_model=ReturnRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_return(payload: ReturnWrite,
                  user: CurrentUser = Depends(require_permission("sales.returns", "create")),
                  db: Session = Depends(get_db)) -> dict:
    return service.create_return(db, user.organization_id, user.id, payload)


@router.put("/returns/{return_id}", response_model=ReturnRead,
            dependencies=[Depends(require_csrf)])
def update_return(return_id: UUID, payload: ReturnWrite,
                  user: CurrentUser = Depends(require_permission("sales.returns", "update")),
                  db: Session = Depends(get_db)) -> dict:
    return service.update_return(db, user.organization_id, user.id, return_id, payload)


@router.delete("/returns/{return_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_return(return_id: UUID,
                  user: CurrentUser = Depends(require_permission("sales.returns", "delete")),
                  db: Session = Depends(get_db)) -> None:
    service.delete_return(db, user.organization_id, user.id, return_id)


@router.post("/returns/{return_id}/post", response_model=ReturnRead,
             dependencies=[Depends(require_csrf)])
def post_return(return_id: UUID,
                user: CurrentUser = Depends(require_permission("sales.returns", "post")),
                db: Session = Depends(get_db)) -> dict:
    return service.post_return(db, user.organization_id, user.id, return_id)


@router.post("/returns/{return_id}/reverse", response_model=ReturnRead,
             dependencies=[Depends(require_csrf)])
def reverse_return(return_id: UUID, payload: ReverseWrite,
                   user: CurrentUser = Depends(require_permission("sales.returns", "reverse")),
                   db: Session = Depends(get_db)) -> dict:
    return service.reverse_return(db, user.organization_id, user.id,
                                  return_id, payload.reason)
