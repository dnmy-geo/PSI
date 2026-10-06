from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.masterdata.catalog import repository, service
from app.masterdata.catalog.schemas import (
    ItemCreate, ItemRead, ItemUpdate, UnitCreate, UnitRead, UnitUpdate,
)

router = APIRouter(prefix="/api", tags=["masterdata"])


@router.get("/units", response_model=list[UnitRead])
def list_units(user: CurrentUser = Depends(require_permission("masterdata.units", "view")), db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_units(db, user.organization_id)


@router.get("/units/{unit_id}", response_model=UnitRead)
def get_unit(
    unit_id: UUID, user: CurrentUser = Depends(require_permission("masterdata.units", "view")), db: Session = Depends(get_db)
) -> dict:
    result = repository.get_unit(db, user.organization_id, unit_id)
    if result is None:
        raise HTTPException(status_code=404, detail="计量单位不存在")
    return repository.attach_related_units(db, user.organization_id, [result])[0]


@router.post("/units", response_model=UnitRead, status_code=201, dependencies=[Depends(require_csrf)])
def create_unit(
    payload: UnitCreate, user: CurrentUser = Depends(require_permission("masterdata.units", "create")), db: Session = Depends(get_db)
) -> dict:
    return service.create_unit(db, user.organization_id, user.id, payload)


@router.put("/units/{unit_id}", response_model=UnitRead, dependencies=[Depends(require_csrf)])
def update_unit(
    unit_id: UUID, payload: UnitUpdate,
    user: CurrentUser = Depends(require_permission("masterdata.units", "update")), db: Session = Depends(get_db),
) -> dict:
    return service.update_unit(db, user.organization_id, user.id, unit_id, payload)


@router.delete("/units/{unit_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_unit(
    unit_id: UUID, user: CurrentUser = Depends(require_permission("masterdata.units", "delete")), db: Session = Depends(get_db)
) -> None:
    service.delete_unit(db, user.organization_id, user.id, unit_id)


@router.get("/items", response_model=list[ItemRead])
def list_items(user: CurrentUser = Depends(require_permission("masterdata.items", "view")), db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_items(db, user.organization_id)


@router.get("/items/{item_id}", response_model=ItemRead)
def get_item(
    item_id: UUID, user: CurrentUser = Depends(require_permission("masterdata.items", "view")), db: Session = Depends(get_db)
) -> dict:
    result = repository.get_item(db, user.organization_id, item_id)
    if result is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    return result


@router.post("/items", response_model=ItemRead, status_code=201, dependencies=[Depends(require_csrf)])
def create_item(
    payload: ItemCreate, user: CurrentUser = Depends(require_permission("masterdata.items", "create")), db: Session = Depends(get_db)
) -> dict:
    return service.create_item(db, user.organization_id, user.id, payload)


@router.put("/items/{item_id}", response_model=ItemRead, dependencies=[Depends(require_csrf)])
def update_item(
    item_id: UUID, payload: ItemUpdate,
    user: CurrentUser = Depends(require_permission("masterdata.items", "update")), db: Session = Depends(get_db),
) -> dict:
    return service.update_item(db, user.organization_id, user.id, item_id, payload)


@router.delete("/items/{item_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_item(
    item_id: UUID, user: CurrentUser = Depends(require_permission("masterdata.items", "delete")), db: Session = Depends(get_db)
) -> None:
    service.delete_item(db, user.organization_id, user.id, item_id)


