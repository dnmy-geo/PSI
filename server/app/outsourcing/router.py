from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.outsourcing import repository, service
from app.outsourcing.schemas import CloseWrite, OrderRead, OrderWrite

router = APIRouter(prefix="/api/outsourcing/orders", tags=["outsourcing"])


@router.get("", response_model=list[OrderRead])
def list_orders(response: Response,
                status: Literal["draft", "open", "closed"] | None = None,
                limit: int = Query(default=100, ge=1, le=500),
                offset: int = Query(default=0, ge=0),
                user: CurrentUser = Depends(require_permission("outsourcing.orders", "view")),
                db: Session = Depends(get_db)) -> list[dict]:
    return [repository.get_order(db, user.organization_id, row["id"])
            for row in repository.list_order_ids(
                db, user.organization_id, status, limit, offset, response)]


@router.get("/{order_id}", response_model=OrderRead)
def get_order(order_id: UUID,
              user: CurrentUser = Depends(require_permission("outsourcing.orders", "view")),
              db: Session = Depends(get_db)) -> dict:
    result = repository.get_order(db, user.organization_id, order_id)
    if result is None:
        raise HTTPException(status_code=404, detail="委外单不存在")
    return result


@router.post("", response_model=OrderRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_order(payload: OrderWrite,
                 user: CurrentUser = Depends(require_permission("outsourcing.orders", "create")),
                 db: Session = Depends(get_db)) -> dict:
    return service.create_order(db, user.organization_id, user.id, payload)


@router.put("/{order_id}", response_model=OrderRead,
            dependencies=[Depends(require_csrf)])
def update_order(order_id: UUID, payload: OrderWrite,
                 user: CurrentUser = Depends(require_permission("outsourcing.orders", "update")),
                 db: Session = Depends(get_db)) -> dict:
    return service.update_order(db, user.organization_id, user.id, order_id, payload)


@router.delete("/{order_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_order(order_id: UUID,
                 user: CurrentUser = Depends(require_permission("outsourcing.orders", "delete")),
                 db: Session = Depends(get_db)) -> None:
    service.delete_order(db, user.organization_id, user.id, order_id)


@router.post("/{order_id}/open", response_model=OrderRead,
             dependencies=[Depends(require_csrf)])
def open_order(order_id: UUID,
               user: CurrentUser = Depends(require_permission("outsourcing.orders", "post")),
               db: Session = Depends(get_db)) -> dict:
    return service.set_status(db, user.organization_id, user.id, order_id, "open")


@router.post("/{order_id}/close", response_model=OrderRead,
             dependencies=[Depends(require_csrf)])
def close_order(order_id: UUID, payload: CloseWrite,
                user: CurrentUser = Depends(require_permission("outsourcing.orders", "force_close")),
                db: Session = Depends(get_db)) -> dict:
    return service.set_status(db, user.organization_id, user.id,
                              order_id, "closed", payload.remark)
