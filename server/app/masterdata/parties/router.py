from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, has_permission, require_csrf
from app.masterdata.parties import repository, service
from app.masterdata.parties.schemas import PartyRead, PartyUpdate, PartyWrite

router = APIRouter(prefix="/api/parties", tags=["parties"])

PARTY_MENUS = {"customer": "masterdata.customers", "supplier": "masterdata.suppliers",
               "processor": "masterdata.processors"}


def _require_party_actions(db: Session, user: CurrentUser, types: set[str], action: str) -> None:
    if not types or any(not has_permission(db, user, PARTY_MENUS[kind], action)
                        for kind in types):
        raise HTTPException(status_code=403, detail="没有权限")


@router.get("", response_model=list[PartyRead])
def list_parties(
    party_type: Literal["customer", "supplier", "processor"] | None = None,
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
) -> list[dict]:
    if party_type is not None:
        _require_party_actions(db, user, {party_type}, "view")
        return repository.list_parties(db, user.organization_id, party_type)
    allowed = {kind for kind, menu in PARTY_MENUS.items()
               if has_permission(db, user, menu, "view")}
    if not allowed:
        raise HTTPException(status_code=403, detail="没有权限")
    return [party for party in repository.list_parties(db, user.organization_id, None)
            if allowed.intersection(party["types"])]


@router.get("/{party_id}", response_model=PartyRead)
def get_party(
    party_id: UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    result = repository.get_party(db, user.organization_id, party_id)
    if result is None:
        raise HTTPException(status_code=404, detail="往来单位不存在")
    if not any(has_permission(db, user, PARTY_MENUS[kind], "view")
               for kind in result["types"]):
        raise HTTPException(status_code=403, detail="没有权限")
    return result


@router.post("", response_model=PartyRead, status_code=201, dependencies=[Depends(require_csrf)])
def create_party(
    payload: PartyWrite, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    _require_party_actions(db, user, payload.types, "create")
    return service.create_party(db, user.organization_id, user.id, payload)


@router.put("/{party_id}", response_model=PartyRead, dependencies=[Depends(require_csrf)])
def update_party(
    party_id: UUID, payload: PartyUpdate,
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    existing = repository.get_party(db, user.organization_id, party_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="往来单位不存在")
    _require_party_actions(db, user, set(existing["types"]) | payload.types, "update")
    return service.update_party(db, user.organization_id, user.id, party_id, payload)


@router.delete("/{party_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_party(
    party_id: UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    existing = repository.get_party(db, user.organization_id, party_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="往来单位不存在")
    _require_party_actions(db, user, set(existing["types"]), "delete")
    service.delete_party(db, user.organization_id, user.id, party_id)
