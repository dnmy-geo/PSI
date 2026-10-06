from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.masterdata.warehouses import repository, service
from app.masterdata.warehouses.schemas import WarehouseCreate, WarehouseRead, WarehouseUpdate

router = APIRouter(prefix="/api/warehouses", tags=["warehouses"])


@router.get("", response_model=list[WarehouseRead])
def list_warehouses(user: CurrentUser = Depends(require_permission("masterdata.warehouses", "view")), db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_warehouses(db, user.organization_id)


@router.get("/{warehouse_id}", response_model=WarehouseRead)
def get_warehouse(
    warehouse_id: UUID,
    user: CurrentUser = Depends(require_permission("masterdata.warehouses", "view")),
    db: Session = Depends(get_db),
) -> dict:
    result = repository.get_warehouse(db, user.organization_id, warehouse_id)
    if result is None:
        raise HTTPException(status_code=404, detail="仓库不存在")
    return result


@router.post("", response_model=WarehouseRead, status_code=201, dependencies=[Depends(require_csrf)])
def create_warehouse(
    payload: WarehouseCreate,
    user: CurrentUser = Depends(require_permission("masterdata.warehouses", "create")),
    db: Session = Depends(get_db),
) -> dict:
    return service.create_warehouse(db, user.organization_id, user.id, payload)


@router.put("/{warehouse_id}", response_model=WarehouseRead, dependencies=[Depends(require_csrf)])
def update_warehouse(
    warehouse_id: UUID,
    payload: WarehouseUpdate,
    user: CurrentUser = Depends(require_permission("masterdata.warehouses", "update")),
    db: Session = Depends(get_db),
) -> dict:
    return service.update_warehouse(db, user.organization_id, user.id, warehouse_id, payload)


@router.delete("/{warehouse_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_warehouse(
    warehouse_id: UUID,
    user: CurrentUser = Depends(require_permission("masterdata.warehouses", "delete")),
    db: Session = Depends(get_db),
) -> None:
    service.delete_warehouse(db, user.organization_id, user.id, warehouse_id)
