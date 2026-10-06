from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.sales import repository, service
from app.sales.schemas import CloseRequest, SalesOrderRead, SalesOrderSummary, SalesOrderWrite

router = APIRouter(prefix="/api/sales/orders", tags=["sales"])


@router.get("", response_model=list[SalesOrderSummary])
def list_orders(response: Response,
                status: Literal["draft", "pending_approval", "approved", "rejected", "closed"] | None = None,
                limit: int = Query(default=100, ge=1, le=500),
                offset: int = Query(default=0, ge=0),
                user: CurrentUser = Depends(require_permission("sales.orders", "view")),
                db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_orders(db, user.organization_id, status, limit, offset, response)


@router.get("/{order_id}", response_model=SalesOrderRead)
def get_order(order_id: UUID,
              user: CurrentUser = Depends(require_permission("sales.orders", "view")),
              db: Session = Depends(get_db)) -> dict:
    result = repository.get_order(db, user.organization_id, order_id)
    if result is None:
        raise HTTPException(status_code=404, detail="销售订单不存在")
    return result


@router.post("", response_model=SalesOrderRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_order(payload: SalesOrderWrite,
                 user: CurrentUser = Depends(require_permission("sales.orders", "create")),
                 db: Session = Depends(get_db)) -> dict:
    return service.create_order(db, user.organization_id, user.id, payload)


@router.put("/{order_id}", response_model=SalesOrderRead,
            dependencies=[Depends(require_csrf)])
def update_order(order_id: UUID, payload: SalesOrderWrite,
                 user: CurrentUser = Depends(require_permission("sales.orders", "update")),
                 db: Session = Depends(get_db)) -> dict:
    return service.update_order(db, user.organization_id, user.id, order_id, payload)


@router.delete("/{order_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_order(order_id: UUID,
                 user: CurrentUser = Depends(require_permission("sales.orders", "delete")),
                 db: Session = Depends(get_db)) -> None:
    service.delete_order(db, user.organization_id, user.id, order_id)


@router.post("/{order_id}/submit", response_model=SalesOrderRead,
             dependencies=[Depends(require_csrf)])
def submit_order(order_id: UUID,
                 user: CurrentUser = Depends(require_permission("sales.orders", "post")),
                 db: Session = Depends(get_db)) -> dict:
    return service.submit_order(db, user.organization_id, user.id, order_id)


@router.post("/{order_id}/close", response_model=SalesOrderRead,
             dependencies=[Depends(require_csrf)])
def close_order(order_id: UUID, payload: CloseRequest,
                user: CurrentUser = Depends(require_permission("sales.orders", "force_close")),
                db: Session = Depends(get_db)) -> dict:
    return service.close_order(db, user.organization_id, user.id, order_id, payload.remark)
