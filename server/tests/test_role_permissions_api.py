"""岗位授权接口的边界：管理员专属菜单与 system_admin 岗位不接受授权写入。

这些菜单由 require_admin 把关，写进 role_permissions 也不会生效；若放行，权限配置界面
就会提供一个"勾了也没用"的选项，并让菜单显示出来却在点开时 403。
"""

from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def test_admin_only_menus_reject_grants() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"perm_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=org_code, org_name="Factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
        with TestClient(app, base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json={
                "organization_code": org_code, "username": "admin", "password": "TestOnlyPassword123!",
            })
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}

            menus = {menu["code"]: menu for menu in client.get("/api/system/menus", headers=headers).json()}
            # 治理类菜单被标为管理员专属，可委派的业务菜单不受影响
            assert menus["system.users"]["admin_only"] is True
            assert menus["system.permissions"]["admin_only"] is True
            assert menus["inventory.query"]["admin_only"] is False
            assert menus["system.approvals"]["admin_only"] is False

            role = client.post("/api/system/roles", json={"code": "clerk", "name": "Clerk"}, headers=headers)
            assert role.status_code == 201, role.text
            role_id = role.json()["id"]

            def grant(pairs: list[dict]) -> object:
                return client.put(f"/api/system/roles/{role_id}/permissions",
                                  json={"permissions": pairs}, headers=headers)

            admin_menu = grant([{"menu_id": menus["system.users"]["id"], "action_code": "view"}])
            assert admin_menu.status_code == 422, admin_menu.text
            assert "system_admin" in admin_menu.json()["detail"]

            # 合法业务菜单仍然可以授权
            assert grant([{"menu_id": menus["inventory.query"]["id"], "action_code": "view"}]).status_code == 200

            # 非法动作码要报"未知动作码"，而不是被误报成缺 view
            unknown = grant([{"menu_id": menus["inventory.query"]["id"], "action_code": "bogus"}])
            assert unknown.status_code == 422
            assert unknown.json()["detail"] == "未知的操作权限码"

            # 非 view 动作缺 view 仍然被拦住
            missing_view = grant([{"menu_id": menus["inventory.query"]["id"], "action_code": "post"}])
            assert missing_view.status_code == 422
            assert missing_view.json()["detail"] == "非查看权限必须同时授予查看权限"

            # system_admin 岗位的权限是隐式的，不接受写入
            admin_role_id = db_admin_role(connection, org_code)
            implicit = client.put(f"/api/system/roles/{admin_role_id}/permissions",
                                  json={"permissions": []}, headers=headers)
            assert implicit.status_code == 409, implicit.text
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()


def db_admin_role(connection, org_code: str) -> str:
    return str(connection.execute(text("""
        SELECT r.id FROM roles r JOIN organizations o ON o.id = r.organization_id
        WHERE o.code = :code AND r.code = 'system_admin'
    """), {"code": org_code}).scalar_one())
