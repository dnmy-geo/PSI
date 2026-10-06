from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_csrf
from app.system import repository, service
from app.system.schemas import (DepartmentCreate, DepartmentRead, DepartmentWrite, OrganizationRead,
                                OrganizationUpdate, PasswordReset, RoleRead, RoleWrite,
                                UserCreate, UserRead, UserUpdate)

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/organization", response_model=OrganizationRead)
def get_organization(user: CurrentUser = Depends(get_current_user),
                     db: Session = Depends(get_db)) -> dict:
    return repository.get_organization(db, user.organization_id)


@router.put("/organization", response_model=OrganizationRead, dependencies=[Depends(require_csrf)])
def update_organization(payload: OrganizationUpdate, user: CurrentUser = Depends(require_admin),
                        db: Session = Depends(get_db)) -> dict:
    return service.update_organization(db, user.organization_id, user.id, payload.name)


@router.get("/departments", response_model=list[DepartmentRead])
def list_departments(user: CurrentUser = Depends(get_current_user),
                     db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_departments(db, user.organization_id)


@router.get("/departments/{department_id}", response_model=DepartmentRead)
def get_department(department_id: UUID, user: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> dict:
    result = repository.get_department(db, user.organization_id, department_id)
    if result is None:
        raise HTTPException(status_code=404, detail="部门不存在")
    return result


@router.post("/departments", response_model=DepartmentRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_department(payload: DepartmentCreate, user: CurrentUser = Depends(require_admin),
                      db: Session = Depends(get_db)) -> dict:
    return service.create_department(db, user.organization_id, user.id, payload)


@router.put("/departments/{department_id}", response_model=DepartmentRead,
            dependencies=[Depends(require_csrf)])
def update_department(department_id: UUID, payload: DepartmentWrite,
                      user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return service.update_department(db, user.organization_id, user.id, department_id, payload)


@router.delete("/departments/{department_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_department(department_id: UUID, user: CurrentUser = Depends(require_admin),
                      db: Session = Depends(get_db)) -> None:
    service.delete_department(db, user.organization_id, user.id, department_id)


@router.get("/roles", response_model=list[RoleRead])
def list_roles(user: CurrentUser = Depends(get_current_user),
               db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_roles(db, user.organization_id)


@router.get("/roles/{role_id}", response_model=RoleRead)
def get_role(role_id: UUID, user: CurrentUser = Depends(get_current_user),
             db: Session = Depends(get_db)) -> dict:
    result = repository.get_role(db, user.organization_id, role_id)
    if result is None:
        raise HTTPException(status_code=404, detail="岗位角色不存在")
    return result


@router.post("/roles", response_model=RoleRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_role(payload: RoleWrite, user: CurrentUser = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    return service.create_role(db, user.organization_id, user.id, payload)


@router.put("/roles/{role_id}", response_model=RoleRead,
            dependencies=[Depends(require_csrf)])
def update_role(role_id: UUID, payload: RoleWrite, user: CurrentUser = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    return service.update_role(db, user.organization_id, user.id, role_id, payload)


@router.delete("/roles/{role_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_role(role_id: UUID, user: CurrentUser = Depends(require_admin),
                db: Session = Depends(get_db)) -> None:
    service.delete_role(db, user.organization_id, user.id, role_id)


@router.get("/users", response_model=list[UserRead])
def list_users(user: CurrentUser = Depends(require_admin),
               db: Session = Depends(get_db)) -> list[dict]:
    return repository.list_users(db, user.organization_id)


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(user_id: UUID, user: CurrentUser = Depends(require_admin),
             db: Session = Depends(get_db)) -> dict:
    result = repository.get_user(db, user.organization_id, user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return result


@router.post("/users", response_model=UserRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_user(payload: UserCreate, user: CurrentUser = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    return service.create_user(db, user.organization_id, user.id, payload)


@router.put("/users/{user_id}", response_model=UserRead,
            dependencies=[Depends(require_csrf)])
def update_user(user_id: UUID, payload: UserUpdate,
                user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return service.update_user(db, user.organization_id, user.id, user_id, payload)


@router.post("/users/{user_id}/reset-password", status_code=204,
             dependencies=[Depends(require_csrf)])
def reset_password(user_id: UUID, payload: PasswordReset,
                   user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    service.reset_password(db, user.organization_id, user.id, user_id, payload.password)


@router.delete("/users/{user_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def deactivate_user(user_id: UUID, user: CurrentUser = Depends(require_admin),
                    db: Session = Depends(get_db)) -> None:
    service.deactivate_user(db, user.organization_id, user.id, user_id)
