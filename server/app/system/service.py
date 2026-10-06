from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import password_hash
from app.system import repository
from app.system.schemas import DepartmentCreate, DepartmentWrite, RoleWrite, UserCreate, UserUpdate


def _lock_org(db: Session, organization_id: UUID) -> None:
    db.execute(text("SELECT id FROM organizations WHERE id = :id FOR UPDATE"),
               {"id": organization_id}).scalar_one()


def _audit(db: Session, org: UUID, actor: UUID, action: str, document_type: str, document_id: UUID) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
        VALUES (:org, :actor, :action, :document_type, :document_id)
    """), {"org": org, "actor": actor, "action": action,
           "document_type": document_type, "document_id": document_id})


def update_organization(db: Session, organization_id: UUID, actor_id: UUID, name: str) -> dict:
    _lock_org(db, organization_id)
    db.execute(text("UPDATE organizations SET name = :name WHERE id = :id"),
               {"name": name.strip(), "id": organization_id})
    _audit(db, organization_id, actor_id, "organization.update", "organization", organization_id)
    result = repository.get_organization(db, organization_id)
    db.commit()
    return result


def _validate_parent(db: Session, org: UUID, department_id: UUID | None, parent_id: UUID | None) -> None:
    if parent_id is None:
        return
    if parent_id == department_id:
        raise HTTPException(status_code=422, detail="部门不能作为自己的上级")
    parent = repository.get_department(db, org, parent_id)
    if parent is None or not parent["is_active"]:
        raise HTTPException(status_code=422, detail="上级部门不可用")
    if department_id is not None:
        cycle = db.execute(text("""
            WITH RECURSIVE ancestors(id, parent_id) AS (
                SELECT id, parent_id FROM departments WHERE id = :parent_id AND organization_id = :org
                UNION
                SELECT d.id, d.parent_id FROM departments d
                JOIN ancestors a ON d.id = a.parent_id WHERE d.organization_id = :org
            )
            SELECT 1 FROM ancestors WHERE id = :department_id LIMIT 1
        """), {"parent_id": parent_id, "department_id": department_id,
               "org": org}).scalar_one_or_none()
        if cycle:
            raise HTTPException(status_code=422, detail="部门层级不能成环")


def _next_department_code(db: Session, org: UUID) -> str:
    codes = db.execute(text("""
        SELECT code FROM departments WHERE organization_id = :org AND code LIKE 'DEP-%'
    """), {"org": org}).scalars()
    numbers = (int(code[4:]) for code in codes if code[4:].isdigit())
    return f"DEP-{max(numbers, default=0) + 1:04d}"


def create_department(db: Session, org: UUID, actor: UUID, data: DepartmentCreate) -> dict:
    _lock_org(db, org)
    _validate_parent(db, org, None, data.parent_id)
    code = data.code.strip() if data.code else ""
    if not code:
        code = _next_department_code(db, org)
    try:
        department_id = db.execute(text("""
            INSERT INTO departments (organization_id, code, name, parent_id, is_active)
            VALUES (:org, :code, :name, :parent_id, :is_active) RETURNING id
        """), {"org": org, "code": code, "name": data.name.strip(),
               "parent_id": data.parent_id, "is_active": data.is_active}).scalar_one()
        _audit(db, org, actor, "department.create", "department", department_id)
        result = repository.get_department(db, org, department_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="部门编码已存在") from exc


def update_department(
    db: Session, org: UUID, actor: UUID, department_id: UUID, data: DepartmentWrite
) -> dict:
    _lock_org(db, org)
    if repository.get_department(db, org, department_id) is None:
        raise HTTPException(status_code=404, detail="部门不存在")
    _validate_parent(db, org, department_id, data.parent_id)
    if not data.is_active:
        used = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM departments WHERE parent_id = :id AND is_active
                UNION ALL
                SELECT 1 FROM users WHERE department_id = :id AND is_active
            )
        """), {"id": department_id}).scalar_one()
        if used:
            raise HTTPException(status_code=409, detail="部门下还有启用的子部门或用户")
    try:
        db.execute(text("""
            UPDATE departments SET code = :code, name = :name,
                parent_id = :parent_id, is_active = :is_active
            WHERE id = :id AND organization_id = :org
        """), {"id": department_id, "org": org, "code": data.code.strip(),
               "name": data.name.strip(), "parent_id": data.parent_id,
               "is_active": data.is_active})
        _audit(db, org, actor, "department.update", "department", department_id)
        result = repository.get_department(db, org, department_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="部门编码已存在") from exc


def delete_department(db: Session, org: UUID, actor: UUID, department_id: UUID) -> None:
    _lock_org(db, org)
    if repository.get_department(db, org, department_id) is None:
        raise HTTPException(status_code=404, detail="部门不存在")
    try:
        db.execute(text("DELETE FROM departments WHERE id = :id AND organization_id = :org"),
                   {"id": department_id, "org": org})
        _audit(db, org, actor, "department.delete", "department", department_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="部门已被引用") from exc


def create_role(db: Session, org: UUID, actor: UUID, data: RoleWrite) -> dict:
    _lock_org(db, org)
    if data.code.strip() == "system_admin":
        raise HTTPException(status_code=409, detail="system_admin 是系统保留岗位")
    try:
        role_id = db.execute(text("""
            INSERT INTO roles (organization_id, code, name, is_active)
            VALUES (:org, :code, :name, :is_active) RETURNING id
        """), {"org": org, "code": data.code.strip(), "name": data.name.strip(),
               "is_active": data.is_active}).scalar_one()
        _audit(db, org, actor, "role.create", "role", role_id)
        result = repository.get_role(db, org, role_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="岗位角色编码已存在") from exc


def update_role(db: Session, org: UUID, actor: UUID, role_id: UUID, data: RoleWrite) -> dict:
    _lock_org(db, org)
    current = repository.get_role(db, org, role_id)
    if current is None:
        raise HTTPException(status_code=404, detail="岗位角色不存在")
    if current["code"] == "system_admin":
        raise HTTPException(status_code=409, detail="system_admin 岗位不能修改")
    if data.code.strip() == "system_admin":
        raise HTTPException(status_code=409, detail="system_admin 是系统保留岗位")
    if not data.is_active:
        assigned = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM user_roles ur JOIN users u ON u.id = ur.user_id
                WHERE ur.role_id = :id AND u.is_active
            )
        """), {"id": role_id}).scalar_one()
        if assigned:
            raise HTTPException(status_code=409, detail="该岗位还有启用中的用户")
    try:
        db.execute(text("""
            UPDATE roles SET code = :code, name = :name, is_active = :is_active
            WHERE id = :id AND organization_id = :org
        """), {"id": role_id, "org": org, "code": data.code.strip(),
               "name": data.name.strip(), "is_active": data.is_active})
        _audit(db, org, actor, "role.update", "role", role_id)
        result = repository.get_role(db, org, role_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="岗位角色编码已存在") from exc


def delete_role(db: Session, org: UUID, actor: UUID, role_id: UUID) -> None:
    _lock_org(db, org)
    current = repository.get_role(db, org, role_id)
    if current is None:
        raise HTTPException(status_code=404, detail="岗位角色不存在")
    if current["code"] == "system_admin":
        raise HTTPException(status_code=409, detail="system_admin 岗位不能删除")
    try:
        db.execute(text("DELETE FROM roles WHERE id = :id AND organization_id = :org"),
                   {"id": role_id, "org": org})
        _audit(db, org, actor, "role.delete", "role", role_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="岗位角色已被使用") from exc


def _validate_user_links(db: Session, org: UUID, department_id: UUID | None,
                         role_ids: list[UUID]) -> None:
    if department_id is not None:
        department = repository.get_department(db, org, department_id)
        if department is None or not department["is_active"]:
            raise HTTPException(status_code=422, detail="部门不可用")
    if len(set(role_ids)) != len(role_ids):
        raise HTTPException(status_code=422, detail="岗位角色重复")
    for role_id in role_ids:
        role = repository.get_role(db, org, role_id)
        if role is None or not role["is_active"]:
            raise HTTPException(status_code=422, detail="岗位角色不可用")


def _assign_roles(db: Session, user_id: UUID, role_ids: list[UUID]) -> None:
    db.execute(text("DELETE FROM user_roles WHERE user_id = :id"), {"id": user_id})
    for role_id in role_ids:
        db.execute(text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
                   {"user_id": user_id, "role_id": role_id})


def _last_admin_guard(db: Session, org: UUID, user_id: UUID,
                      role_ids: list[UUID], is_active: bool) -> None:
    admin_role_id = db.execute(text("""
        SELECT id FROM roles WHERE organization_id = :org AND code = 'system_admin'
    """), {"org": org}).scalar_one()
    if is_active and admin_role_id in role_ids:
        return
    count = db.execute(text("""
        SELECT count(*) FROM users u JOIN user_roles ur ON ur.user_id = u.id
        WHERE u.organization_id = :org AND u.is_active
          AND ur.role_id = :admin_role_id AND u.id <> :user_id
    """), {"org": org, "admin_role_id": admin_role_id, "user_id": user_id}).scalar_one()
    if count == 0:
        raise HTTPException(status_code=409, detail="不能移除最后一个有效管理员")


def _approval_coverage_guard(db: Session, org: UUID, user_id: UUID,
                             role_ids: list[UUID], is_active: bool) -> None:
    if not is_active:
        direct = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM approval_config_steps s
                JOIN approval_configs c ON c.id = s.config_id
                WHERE c.organization_id = :org AND c.is_enabled AND s.approver_user_id = :user_id
                UNION ALL
                SELECT 1 FROM approval_tasks t
                JOIN approval_instances i ON i.id = t.instance_id
                WHERE i.organization_id = :org AND i.status = 'pending'
                  AND t.status = 'pending' AND t.approver_user_id = :user_id
            )
        """), {"org": org, "user_id": user_id}).scalar_one()
        if direct:
            raise HTTPException(status_code=409, detail="该用户是审批人，停用后会导致审批无人可批")
    current_roles = db.execute(text("""
        SELECT role_id FROM user_roles WHERE user_id = :user_id
    """), {"user_id": user_id}).scalars()
    for role_id in current_roles:
        if is_active and role_id in role_ids:
            continue
        other_members = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM user_roles ur JOIN users u ON u.id = ur.user_id
                WHERE ur.role_id = :role_id AND u.organization_id = :org
                  AND u.is_active AND u.id <> :user_id
            )
        """), {"role_id": role_id, "org": org, "user_id": user_id}).scalar_one()
        if other_members:
            continue
        required = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM approval_config_steps s
                JOIN approval_configs c ON c.id = s.config_id
                WHERE c.organization_id = :org AND c.is_enabled AND s.approver_role_id = :role_id
                UNION ALL
                SELECT 1 FROM approval_tasks t
                JOIN approval_instances i ON i.id = t.instance_id
                WHERE i.organization_id = :org AND i.status = 'pending'
                  AND t.status = 'pending' AND t.approver_role_id = :role_id
            )
        """), {"org": org, "role_id": role_id}).scalar_one()
        if required:
            raise HTTPException(status_code=409, detail="该岗位是审批人，停用后会导致审批无人可批")


def create_user(db: Session, org: UUID, actor: UUID, data: UserCreate) -> dict:
    _lock_org(db, org)
    _validate_user_links(db, org, data.department_id, data.role_ids)
    try:
        user_id = db.execute(text("""
            INSERT INTO users (organization_id, department_id, username, display_name,
                               password_hash, is_active)
            VALUES (:org, :department_id, :username, :display_name,
                    :password_hash, :is_active) RETURNING id
        """), {"org": org, "department_id": data.department_id,
               "username": data.username.strip(), "display_name": data.display_name.strip(),
               "password_hash": password_hash.hash(data.password),
               "is_active": data.is_active}).scalar_one()
        _assign_roles(db, user_id, data.role_ids)
        _audit(db, org, actor, "user.create", "user", user_id)
        result = repository.get_user(db, org, user_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在") from exc


def update_user(db: Session, org: UUID, actor: UUID, user_id: UUID, data: UserUpdate) -> dict:
    _lock_org(db, org)
    current = repository.get_user(db, org, user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    _validate_user_links(db, org, data.department_id, data.role_ids)
    _last_admin_guard(db, org, user_id, data.role_ids, data.is_active)
    _approval_coverage_guard(db, org, user_id, data.role_ids, data.is_active)
    try:
        db.execute(text("""
            UPDATE users SET department_id = :department_id, username = :username,
                display_name = :display_name, is_active = :is_active
            WHERE id = :id AND organization_id = :org
        """), {"id": user_id, "org": org, "department_id": data.department_id,
               "username": data.username.strip(), "display_name": data.display_name.strip(),
               "is_active": data.is_active})
        if set(current["role_ids"]) != set(data.role_ids):
            _assign_roles(db, user_id, data.role_ids)
        if not data.is_active or set(current["role_ids"]) != set(data.role_ids):
            db.execute(text("""
                UPDATE auth_sessions SET revoked_at = now()
                WHERE user_id = :id AND revoked_at IS NULL
            """), {"id": user_id})
        _audit(db, org, actor, "user.update", "user", user_id)
        result = repository.get_user(db, org, user_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在") from exc


def reset_password(db: Session, org: UUID, actor: UUID, user_id: UUID,
                   new_password: str) -> None:
    _lock_org(db, org)
    if repository.get_user(db, org, user_id) is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.execute(text("UPDATE users SET password_hash = :hash WHERE id = :id"),
               {"id": user_id, "hash": password_hash.hash(new_password)})
    db.execute(text("""
        UPDATE auth_sessions SET revoked_at = now()
        WHERE user_id = :id AND revoked_at IS NULL
    """), {"id": user_id})
    _audit(db, org, actor, "user.reset_password", "user", user_id)
    db.commit()


def deactivate_user(db: Session, org: UUID, actor: UUID, user_id: UUID) -> None:
    _lock_org(db, org)
    current = repository.get_user(db, org, user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    _last_admin_guard(db, org, user_id, current["role_ids"], False)
    _approval_coverage_guard(db, org, user_id, current["role_ids"], False)
    db.execute(text("UPDATE users SET is_active = false WHERE id = :id AND organization_id = :org"),
               {"id": user_id, "org": org})
    db.execute(text("UPDATE auth_sessions SET revoked_at = now() WHERE user_id = :id AND revoked_at IS NULL"),
               {"id": user_id})
    _audit(db, org, actor, "user.deactivate", "user", user_id)
    db.commit()
