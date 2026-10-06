from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.masterdata.categories import repository, service
from app.masterdata.categories.schemas import CategoryRead, CategoryWrite

router = APIRouter(prefix="/api/item-categories", tags=["item-categories"])


@router.get("", response_model=list[CategoryRead])
def list_categories(user: CurrentUser = Depends(require_permission("masterdata.categories", "view")), db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_categories(db, user.organization_id)


@router.get("/{category_id}", response_model=CategoryRead)
def get_category(
    category_id: UUID, user: CurrentUser = Depends(require_permission("masterdata.categories", "view")), db: Session = Depends(get_db)
) -> dict:
    result = repository.get_category(db, user.organization_id, category_id)
    if result is None:
        raise HTTPException(status_code=404, detail="物料分类不存在")
    return result


@router.post("", response_model=CategoryRead, status_code=201, dependencies=[Depends(require_csrf)])
def create_category(
    payload: CategoryWrite, user: CurrentUser = Depends(require_permission("masterdata.categories", "create")), db: Session = Depends(get_db)
) -> dict:
    return service.create_category(db, user.organization_id, user.id, payload)


@router.put("/{category_id}", response_model=CategoryRead, dependencies=[Depends(require_csrf)])
def update_category(
    category_id: UUID, payload: CategoryWrite,
    user: CurrentUser = Depends(require_permission("masterdata.categories", "update")), db: Session = Depends(get_db),
) -> dict:
    return service.update_category(db, user.organization_id, user.id, category_id, payload)


@router.delete("/{category_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_category(
    category_id: UUID, user: CurrentUser = Depends(require_permission("masterdata.categories", "delete")), db: Session = Depends(get_db)
) -> None:
    service.delete_category(db, user.organization_id, user.id, category_id)
