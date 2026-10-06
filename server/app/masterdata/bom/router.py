from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.masterdata.bom import repository, service
from app.masterdata.bom.schemas import BomRead, BomSummary, BomWrite

router = APIRouter(prefix="/api/boms", tags=["boms"])


@router.get("", response_model=list[BomSummary])
def list_boms(
    response: Response,
    parent_item_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_permission("masterdata.boms", "view")), db: Session = Depends(get_db),
) -> list[dict]:
    return repository.list_boms(db, user.organization_id, parent_item_id,
                                limit=limit, offset=offset, response=response)


@router.get("/{bom_id}", response_model=BomRead)
def get_bom(
    bom_id: UUID, user: CurrentUser = Depends(require_permission("masterdata.boms", "view")), db: Session = Depends(get_db)
) -> dict:
    result = repository.get_bom(db, user.organization_id, bom_id)
    if result is None:
        raise HTTPException(status_code=404, detail="用料清单不存在")
    return result


@router.post("", response_model=BomRead, status_code=201, dependencies=[Depends(require_csrf)])
def create_bom(
    payload: BomWrite, user: CurrentUser = Depends(require_permission("masterdata.boms", "create")), db: Session = Depends(get_db)
) -> dict:
    return service.create_bom(db, user.organization_id, user.id, payload)


@router.put("/{bom_id}", response_model=BomRead, dependencies=[Depends(require_csrf)])
def update_bom(
    bom_id: UUID, payload: BomWrite,
    user: CurrentUser = Depends(require_permission("masterdata.boms", "update")), db: Session = Depends(get_db),
) -> dict:
    return service.update_bom(db, user.organization_id, user.id, bom_id, payload)


@router.post("/{bom_id}/activate", response_model=BomRead, dependencies=[Depends(require_csrf)])
def activate_bom(
    bom_id: UUID, user: CurrentUser = Depends(require_permission("masterdata.boms", "post")), db: Session = Depends(get_db)
) -> dict:
    return service.activate_bom(db, user.organization_id, user.id, bom_id)


@router.delete("/{bom_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_bom(
    bom_id: UUID, user: CurrentUser = Depends(require_permission("masterdata.boms", "delete")), db: Session = Depends(get_db)
) -> None:
    service.delete_bom(db, user.organization_id, user.id, bom_id)
