"""Global menu catalog and organization-scoped role permissions."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_csrf
from app.system import repository

router = APIRouter(prefix="/api/system", tags=["system"])

ACTION_CODES = frozenset({
    "view", "create", "update", "delete", "submit", "post", "approve", "reverse",
    "adjust", "force_close",
})

# 治理类菜单由 require_admin 把关，不接受岗位授权：把这些菜单的 view 动作授给非管理员，
# 只会让菜单显示出来、点开 403。权限配置界面据此把它们排除在可勾选范围外。
ADMIN_ONLY_MENU_CODES = frozenset({
    "system.organization", "system.departments", "system.roles",
    "system.users", "system.menus", "system.permissions",
})


class MenuWrite(BaseModel):
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.]*$")
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    parent_id: UUID | None = None
    path: str | None = Field(default=None, max_length=200)
    sort_order: int = 0
    is_active: bool = True


class MenuRead(MenuWrite):
    id: UUID
    admin_only: bool = False
    created_at: datetime
    updated_at: datetime


class PermissionWrite(BaseModel):
    menu_id: UUID
    action_code: str


class RolePermissionsWrite(BaseModel):
    permissions: list[PermissionWrite]


def _lock_menus(db: Session) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(751013)"))


def _menu(db: Session, menu_id: UUID) -> dict | None:
    row = db.execute(text("""
        SELECT id, code, name, parent_id, path, sort_order, is_active, created_at, updated_at
        FROM menus WHERE id = :id
    """), {"id": menu_id}).mappings().first()
    return _with_admin_flag(dict(row)) if row is not None else None


def _menus(db: Session, *, newest_first: bool = False) -> list[dict]:
    # 侧边栏（my-menus）仍按 sort_order 展示；管理列表按创建时间倒序。
    order = "created_at DESC, sort_order, code" if newest_first else "sort_order, code"
    return [_with_admin_flag(dict(row)) for row in db.execute(text(f"""
        SELECT id, code, name, parent_id, path, sort_order, is_active, created_at, updated_at
        FROM menus ORDER BY {order}
    """)).mappings()]


def _with_admin_flag(menu: dict) -> dict:
    return {**menu, "admin_only": menu["code"] in ADMIN_ONLY_MENU_CODES}


def _validate_parent(db: Session, menu_id: UUID | None, parent_id: UUID | None) -> None:
    if parent_id is None:
        return
    parent = _menu(db, parent_id)
    if parent is None or not parent["is_active"] or parent["parent_id"] is not None:
        raise HTTPException(status_code=422, detail="上级必须是启用中的一级菜单")
    if parent_id == menu_id:
        raise HTTPException(status_code=422, detail="菜单不能作为自己的上级")
    if menu_id is not None:
        has_children = db.execute(text("SELECT EXISTS (SELECT 1 FROM menus WHERE parent_id = :id)"),
                                  {"id": menu_id}).scalar_one()
        if has_children:
            raise HTTPException(status_code=409, detail="有子菜单的菜单不能变成子菜单")


def _audit(db: Session, user: CurrentUser, action: str, document_type: str,
           document_id: UUID) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
        VALUES (:org, :actor, :action, :document_type, :document_id)
    """), {"org": user.organization_id, "actor": user.id, "action": action,
           "document_type": document_type, "document_id": document_id})


@router.get("/menus", response_model=list[MenuRead])
def list_menus(user: CurrentUser = Depends(require_admin),
               db: Session = Depends(get_db)) -> list[dict]:
    return _menus(db, newest_first=True)


@router.get("/my-menus", response_model=list[MenuRead])
def my_menus(user: CurrentUser = Depends(get_current_user),
             db: Session = Depends(get_db)) -> list[dict]:
    all_menus = [menu for menu in _menus(db) if menu["is_active"]]
    admin = db.execute(text("""
        SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = :user_id AND r.organization_id = :org
          AND r.code = 'system_admin' AND r.is_active LIMIT 1
    """), {"user_id": user.id, "org": user.organization_id}).scalar_one_or_none()
    if admin:
        return all_menus
    visible = set(db.execute(text("""
        SELECT rp.menu_id FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        JOIN role_permissions rp ON rp.role_id = r.id
        WHERE ur.user_id = :user_id AND r.organization_id = :org
          AND r.is_active AND rp.action_code = 'view'
    """), {"user_id": user.id, "org": user.organization_id}).scalars())
    for menu in all_menus:
        if menu["id"] in visible and menu["parent_id"] is not None:
            visible.add(menu["parent_id"])
    # The read-only flow guide is available to staff with an operational menu.
    operational_groups = {"sales", "purchase", "inventory", "production", "outsourcing", "reconciliation"}
    if any(menu["id"] in visible and menu["code"].split(".")[0] in operational_groups
           for menu in all_menus):
        visible.update(menu["id"] for menu in all_menus if menu["code"] == "business_flow")
    return [menu for menu in all_menus if menu["id"] in visible]


@router.get("/my-permissions", response_model=dict[str, list[str]])
def my_permissions(user: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> dict[str, list[str]]:
    admin = db.execute(text("""
        SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = :user_id AND r.organization_id = :org
          AND r.code = 'system_admin' AND r.is_active LIMIT 1
    """), {"user_id": user.id, "org": user.organization_id}).scalar_one_or_none()
    if admin:
        return {menu["code"]: sorted(ACTION_CODES) for menu in _menus(db) if menu["is_active"]}
    rows = db.execute(text("""
        SELECT DISTINCT m.code, rp.action_code FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        JOIN role_permissions rp ON rp.role_id = r.id
        JOIN menus m ON m.id = rp.menu_id
        WHERE ur.user_id = :user_id AND r.organization_id = :org
          AND r.is_active AND m.is_active
        ORDER BY m.code, rp.action_code
    """), {"user_id": user.id, "org": user.organization_id}).all()
    result: dict[str, list[str]] = {}
    for menu_code, action_code in rows:
        result.setdefault(menu_code, []).append(action_code)
    return result


@router.get("/menus/{menu_id}", response_model=MenuRead)
def get_menu(menu_id: UUID, user: CurrentUser = Depends(require_admin),
             db: Session = Depends(get_db)) -> dict:
    result = _menu(db, menu_id)
    if result is None:
        raise HTTPException(status_code=404, detail="菜单不存在")
    return result


@router.post("/menus", response_model=MenuRead, status_code=201,
             dependencies=[Depends(require_csrf)])
def create_menu(payload: MenuWrite, user: CurrentUser = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    _lock_menus(db)
    _validate_parent(db, None, payload.parent_id)
    try:
        menu_id = db.execute(text("""
            INSERT INTO menus (code, name, parent_id, path, sort_order, is_active)
            VALUES (:code, :name, :parent_id, :path, :sort_order, :is_active) RETURNING id
        """), {"code": payload.code, "name": payload.name.strip(),
               "parent_id": payload.parent_id, "path": payload.path,
               "sort_order": payload.sort_order, "is_active": payload.is_active}).scalar_one()
        _audit(db, user, "menu.create", "menu", menu_id)
        result = _menu(db, menu_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="菜单编码已存在") from exc


@router.put("/menus/{menu_id}", response_model=MenuRead,
            dependencies=[Depends(require_csrf)])
def update_menu(menu_id: UUID, payload: MenuWrite,
                user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    _lock_menus(db)
    if _menu(db, menu_id) is None:
        raise HTTPException(status_code=404, detail="菜单不存在")
    _validate_parent(db, menu_id, payload.parent_id)
    if not payload.is_active:
        active_children = db.execute(text("""
            SELECT EXISTS (SELECT 1 FROM menus WHERE parent_id = :id AND is_active)
        """), {"id": menu_id}).scalar_one()
        if active_children:
            raise HTTPException(status_code=409, detail="菜单下还有启用的子菜单")
    try:
        db.execute(text("""
            UPDATE menus SET code = :code, name = :name, parent_id = :parent_id,
                path = :path, sort_order = :sort_order, is_active = :is_active WHERE id = :id
        """), {"id": menu_id, "code": payload.code, "name": payload.name.strip(),
               "parent_id": payload.parent_id, "path": payload.path,
               "sort_order": payload.sort_order, "is_active": payload.is_active})
        _audit(db, user, "menu.update", "menu", menu_id)
        result = _menu(db, menu_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="菜单编码已存在") from exc


@router.delete("/menus/{menu_id}", status_code=204,
               dependencies=[Depends(require_csrf)])
def delete_menu(menu_id: UUID, user: CurrentUser = Depends(require_admin),
                db: Session = Depends(get_db)) -> None:
    _lock_menus(db)
    if _menu(db, menu_id) is None:
        raise HTTPException(status_code=404, detail="菜单不存在")
    try:
        db.execute(text("DELETE FROM menus WHERE id = :id"), {"id": menu_id})
        _audit(db, user, "menu.delete", "menu", menu_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="菜单已被引用") from exc


@router.get("/roles/{role_id}/permissions", response_model=list[PermissionWrite])
def get_role_permissions(role_id: UUID, user: CurrentUser = Depends(require_admin),
                         db: Session = Depends(get_db)) -> list[dict]:
    if repository.get_role(db, user.organization_id, role_id) is None:
        raise HTTPException(status_code=404, detail="岗位角色不存在")
    return [dict(row) for row in db.execute(text("""
        SELECT menu_id, action_code FROM role_permissions
        WHERE role_id = :id ORDER BY menu_id, action_code
    """), {"id": role_id}).mappings()]


@router.put("/roles/{role_id}/permissions", response_model=list[PermissionWrite],
            dependencies=[Depends(require_csrf)])
def replace_role_permissions(role_id: UUID, payload: RolePermissionsWrite,
                             user: CurrentUser = Depends(require_admin),
                             db: Session = Depends(get_db)) -> list[dict]:
    db.execute(text("SELECT id FROM organizations WHERE id = :id FOR UPDATE"),
               {"id": user.organization_id}).scalar_one()
    role = repository.get_role(db, user.organization_id, role_id)
    if role is None or not role["is_active"]:
        raise HTTPException(status_code=404, detail="没有找到启用中的岗位")
    if role["code"] == "system_admin":
        raise HTTPException(status_code=409,
                            detail="system_admin 的权限是隐式的，不需要也不能编辑")
    pairs = [(permission.menu_id, permission.action_code) for permission in payload.permissions]
    if len(pairs) != len(set(pairs)):
        raise HTTPException(status_code=422, detail="权限重复")
    # 先校验动作码与菜单可用性，再校验 view 依赖：否则非法动作码会被报成缺 view，误导排查。
    for menu_id, action_code in pairs:
        if action_code not in ACTION_CODES:
            raise HTTPException(status_code=422, detail="未知的操作权限码")
        menu = _menu(db, menu_id)
        if menu is None or not menu["is_active"]:
            raise HTTPException(status_code=422, detail="菜单不可用")
        if menu["admin_only"]:
            raise HTTPException(status_code=422,
                                detail=f"{menu['code']} is administered by system_admin and cannot be granted")
    pair_set = set(pairs)
    for menu_id, action_code in pairs:
        if action_code != "view" and (menu_id, "view") not in pair_set:
            raise HTTPException(status_code=422, detail="非查看权限必须同时授予查看权限")
    db.execute(text("DELETE FROM role_permissions WHERE role_id = :id"), {"id": role_id})
    for menu_id, action_code in pairs:
        db.execute(text("""
            INSERT INTO role_permissions (role_id, menu_id, action_code)
            VALUES (:role_id, :menu_id, :action_code)
        """), {"role_id": role_id, "menu_id": menu_id, "action_code": action_code})
    _audit(db, user, "role.permissions.replace", "role", role_id)
    result = get_role_permissions(role_id, user, db)
    db.commit()
    return result
