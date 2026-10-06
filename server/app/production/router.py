from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.production import repository, service, shortage
from app.production.schemas import (AutoSplitRequest, ManualSplitRequest,
                                    PlanRead, PlanWrite, ProductionOrderRead,
                                    ShortageRead)

router = APIRouter(prefix="/api/production", tags=["production"])


@router.get("/plans", response_model=list[PlanRead])
def list_plans(response: Response,
               status: Literal["draft", "open", "closed"] | None = None,
               limit: int = Query(default=100, ge=1, le=500),
               offset: int = Query(default=0, ge=0),
               user: CurrentUser = Depends(require_permission("production.plans", "view")),
               db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_plans(db, user.organization_id, status, limit, offset, response)


@router.get("/plans/{plan_id}", response_model=PlanRead)
def get_plan(plan_id: UUID,
             user: CurrentUser = Depends(require_permission("production.plans", "view")),
             db: Session = Depends(get_db)) -> dict:
    result = repository.get_plan(db, user.organization_id, plan_id)
    if result is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    return result


@router.post("/plans", response_model=PlanRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_plan(payload: PlanWrite,
                user: CurrentUser = Depends(require_permission("production.plans", "create")),
                db: Session = Depends(get_db)) -> dict:
    return service.create_plan(db, user.organization_id, user.id, payload)


@router.put("/plans/{plan_id}", response_model=PlanRead,
            dependencies=[Depends(require_csrf)])
def update_plan(plan_id: UUID, payload: PlanWrite,
                user: CurrentUser = Depends(require_permission("production.plans", "update")),
                db: Session = Depends(get_db)) -> dict:
    return service.update_plan(db, user.organization_id, user.id, plan_id, payload)


@router.delete("/plans/{plan_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_plan(plan_id: UUID,
                user: CurrentUser = Depends(require_permission("production.plans", "delete")),
                db: Session = Depends(get_db)) -> None:
    service.delete_plan(db, user.organization_id, user.id, plan_id)


@router.post("/plans/{plan_id}/open", response_model=PlanRead,
             dependencies=[Depends(require_csrf)])
def open_plan(plan_id: UUID,
              user: CurrentUser = Depends(require_permission("production.plans", "post")),
              db: Session = Depends(get_db)) -> dict:
    return service.open_plan(db, user.organization_id, user.id, plan_id)


@router.post("/plans/{plan_id}/close", response_model=PlanRead,
             dependencies=[Depends(require_csrf)])
def close_plan(plan_id: UUID,
               user: CurrentUser = Depends(require_permission("production.plans", "post")),
               db: Session = Depends(get_db)) -> dict:
    return service.close_plan(db, user.organization_id, user.id, plan_id)


@router.get("/plans/{plan_id}/shortage", response_model=ShortageRead)
def plan_shortage(plan_id: UUID,
                  user: CurrentUser = Depends(require_permission("production.plans", "view")),
                  db: Session = Depends(get_db)) -> dict:
    plan = repository.get_plan(db, user.organization_id, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    return shortage.calculate_shortage(db, user.organization_id, plan)


@router.post("/plans/{plan_id}/split/auto", response_model=list[ProductionOrderRead],
             status_code=201, dependencies=[Depends(require_csrf)])
def auto_split(plan_id: UUID, payload: AutoSplitRequest,
               user: CurrentUser = Depends(require_permission("production.plans", "post")),
               db: Session = Depends(get_db)) -> list[dict]:
    return service.auto_split(db, user.organization_id, user.id,
                              plan_id, payload.order_count)


@router.post("/plans/{plan_id}/split/manual", response_model=list[ProductionOrderRead],
             status_code=201, dependencies=[Depends(require_csrf)])
def manual_split(plan_id: UUID, payload: ManualSplitRequest,
                 user: CurrentUser = Depends(require_permission("production.plans", "post")),
                 db: Session = Depends(get_db)) -> list[dict]:
    return service.manual_split(db, user.organization_id, user.id, plan_id, payload.orders)


@router.get("/orders", response_model=list[ProductionOrderRead])
def list_orders(response: Response,
                production_plan_id: UUID | None = None,
                limit: int = Query(default=100, ge=1, le=500),
                offset: int = Query(default=0, ge=0),
                user: CurrentUser = Depends(require_permission("production.orders", "view")),
                db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_orders(db, user.organization_id,
                                  production_plan_id, limit, offset, response)


@router.get("/orders/{order_id}", response_model=ProductionOrderRead)
def get_order(order_id: UUID,
              user: CurrentUser = Depends(require_permission("production.orders", "view")),
              db: Session = Depends(get_db)) -> dict:
    result = repository.get_order(db, user.organization_id, order_id)
    if result is None:
        raise HTTPException(status_code=404, detail="生产订单不存在")
    return result


@router.post("/orders/{order_id}/open", response_model=ProductionOrderRead,
             dependencies=[Depends(require_csrf)])
def open_order(order_id: UUID,
               user: CurrentUser = Depends(require_permission("production.orders", "post")),
               db: Session = Depends(get_db)) -> dict:
    return service.open_order(db, user.organization_id, user.id, order_id)


@router.delete("/orders/{order_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_order(order_id: UUID,
                 user: CurrentUser = Depends(require_permission("production.orders", "delete")),
                 db: Session = Depends(get_db)) -> None:
    service.delete_order(db, user.organization_id, user.id, order_id)
