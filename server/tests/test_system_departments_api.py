from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def test_organization_and_department_hierarchy() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"system_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=org_code, org_name="Factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
            other_org = db.execute(text("""
                INSERT INTO organizations (code, name) VALUES (:code, 'Other') RETURNING id
            """), {"code": f"other_{uuid4().hex[:8]}"}).scalar_one()
            other_dept = db.execute(text("""
                INSERT INTO departments (organization_id, code, name)
                VALUES (:org, 'OTHER', 'Other') RETURNING id
            """), {"org": other_org}).scalar_one()
            db.commit()

        with TestClient(app, base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json={
                "organization_code": org_code, "username": "admin", "password": "TestOnlyPassword123!",
            })
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}
            assert client.put("/api/system/organization", json={"name": "New Factory"},
                              headers=headers).json()["name"] == "New Factory"
            assert client.get("/api/system/organization").json()["code"] == org_code

            root = client.post("/api/system/departments", json={
                "code": "PROD", "name": "Production",
            }, headers=headers)
            assert root.status_code == 201, root.text
            child = client.post("/api/system/departments", json={
                "code": "LINE1", "name": "Line 1", "parent_id": root.json()["id"],
            }, headers=headers)
            assert child.status_code == 201, child.text
            assert len(client.get("/api/system/departments").json()) == 2
            assert client.get(f"/api/system/departments/{other_dept}").status_code == 404
            assert client.post("/api/system/departments", json={
                "code": "BAD", "name": "Bad", "parent_id": str(other_dept),
            }, headers=headers).status_code == 422
            assert client.put(f"/api/system/departments/{root.json()['id']}", json={
                "code": "PROD", "name": "Production", "parent_id": child.json()["id"],
            }, headers=headers).status_code == 422
            assert client.put(f"/api/system/departments/{root.json()['id']}", json={
                "code": "PROD", "name": "Production", "is_active": False,
            }, headers=headers).status_code == 409
            assert client.delete(f"/api/system/departments/{root.json()['id']}",
                                 headers=headers).status_code == 409
            assert client.delete(f"/api/system/departments/{child.json()['id']}",
                                 headers=headers).status_code == 204
            assert client.delete(f"/api/system/departments/{root.json()['id']}",
                                 headers=headers).status_code == 204

            manual = client.post("/api/system/departments", json={
                "code": "DEP-0001", "name": "Manual department",
            }, headers=headers)
            assert manual.status_code == 201, manual.text
            generated = client.post("/api/system/departments", json={
                "name": "Automatically numbered department",
            }, headers=headers)
            assert generated.status_code == 201, generated.text
            assert generated.json()["code"] == "DEP-0002"
            blank = client.post("/api/system/departments", json={
                "code": "  ", "name": "Blank code department",
            }, headers=headers)
            assert blank.status_code == 201, blank.text
            assert blank.json()["code"] == "DEP-0003"
            assert client.put(f"/api/system/departments/{blank.json()['id']}", json={
                "code": "", "name": "Blank code department",
            }, headers=headers).status_code == 422

            roles = client.get("/api/system/roles")
            assert roles.status_code == 200, roles.text
            admin_role = next(role for role in roles.json() if role["code"] == "system_admin")
            assert client.put(f"/api/system/roles/{admin_role['id']}", json={
                "code": "system_admin", "name": "Changed", "is_active": False,
            }, headers=headers).status_code == 409
            assert client.delete(f"/api/system/roles/{admin_role['id']}",
                                 headers=headers).status_code == 409
            role = client.post("/api/system/roles", json={
                "code": "line_lead", "name": "Line lead",
            }, headers=headers)
            assert role.status_code == 201, role.text
            assert client.get(f"/api/system/roles/{role.json()['id']}").status_code == 200
            changed = client.put(f"/api/system/roles/{role.json()['id']}", json={
                "code": "line_lead", "name": "Lead", "is_active": False,
            }, headers=headers)
            assert changed.status_code == 200, changed.text
            assert changed.json()["is_active"] is False
            assert client.delete(f"/api/system/roles/{role.json()['id']}",
                                 headers=headers).status_code == 204

            worker_role = client.post("/api/system/roles", json={
                "code": "worker", "name": "Worker",
            }, headers=headers)
            assert worker_role.status_code == 201, worker_role.text
            menus = client.get("/api/system/menus")
            assert menus.status_code == 200, menus.text
            inventory_parent = next(menu for menu in menus.json() if menu["code"] == "inventory")
            inventory_query = next(menu for menu in menus.json() if menu["code"] == "inventory.query")
            warehouses_menu = next(menu for menu in menus.json() if menu["code"] == "masterdata.warehouses")
            assert inventory_query["parent_id"] == inventory_parent["id"]
            custom_menu = client.post("/api/system/menus", json={
                "code": "inventory.custom", "name": "Custom", "parent_id": inventory_parent["id"],
                "path": "/inventory/custom",
            }, headers=headers)
            assert custom_menu.status_code == 201, custom_menu.text
            assert client.post("/api/system/menus", json={
                "code": "inventory.custom.deep", "name": "Deep",
                "parent_id": custom_menu.json()["id"],
            }, headers=headers).status_code == 422
            assert client.delete(f"/api/system/menus/{custom_menu.json()['id']}",
                                 headers=headers).status_code == 204
            admin_data = client.get("/api/system/users").json()[0]
            assert admin_data["username"] == "admin"
            assert "password_hash" not in admin_data
            assert client.put(f"/api/system/users/{admin_data['id']}", json={
                "username": "admin", "display_name": "Admin", "role_ids": [worker_role.json()["id"]],
            }, headers=headers).status_code == 409
            assert client.delete(f"/api/system/users/{admin_data['id']}",
                                 headers=headers).status_code == 409

            employee = client.post("/api/system/users", json={
                "username": "worker1", "display_name": "Worker One",
                "password": "EmployeePassword123!", "role_ids": [worker_role.json()["id"]],
            }, headers=headers)
            assert employee.status_code == 201, employee.text
            assert client.post("/api/system/users", json={
                "username": "bad", "display_name": "Bad", "password": "EmployeePassword123!",
                "role_ids": [str(other_dept)],
            }, headers=headers).status_code == 422
            with TestClient(app, base_url="https://testserver") as employee_client:
                employee_login = employee_client.post("/api/auth/login", json={
                    "organization_code": org_code, "username": "worker1",
                    "password": "EmployeePassword123!",
                })
                assert employee_login.status_code == 200, employee_login.text
                assert employee_client.get("/api/system/roles").status_code == 200
                assert employee_client.get("/api/system/users").status_code == 403
                assert employee_client.get("/api/inventory/balances").status_code == 403
                worker_headers = {"X-CSRF-Token": employee_login.json()["csrf_token"]}
                assert employee_client.post("/api/warehouses", json={
                    "code": "WORKER", "name": "Worker warehouse",
                }, headers=worker_headers).status_code == 403
                grant = client.put(f"/api/system/roles/{worker_role.json()['id']}/permissions",
                                   json={"permissions": [{
                                       "menu_id": inventory_query["id"], "action_code": "view",
                                   }, {
                                       "menu_id": warehouses_menu["id"], "action_code": "view",
                                   }, {
                                       "menu_id": warehouses_menu["id"], "action_code": "create",
                                   }]}, headers=headers)
                assert grant.status_code == 200, grant.text
                assert employee_client.get("/api/inventory/balances").status_code == 200
                permissions = employee_client.get("/api/system/my-permissions").json()
                assert permissions["masterdata.warehouses"] == ["create", "view"]
                assert "delete" not in permissions["masterdata.warehouses"]
                created_warehouse = employee_client.post("/api/warehouses", json={
                    "code": "WORKER", "name": "Worker warehouse",
                }, headers=worker_headers)
                assert created_warehouse.status_code == 201, created_warehouse.text
                assert employee_client.delete(
                    f"/api/warehouses/{created_warehouse.json()['id']}",
                    headers=worker_headers,
                ).status_code == 403
                assert client.delete(
                    f"/api/warehouses/{created_warehouse.json()['id']}",
                    headers=headers,
                ).status_code == 204
                visible = {menu["code"] for menu in employee_client.get("/api/system/my-menus").json()}
                assert "inventory.query" in visible and "inventory" in visible
                assert "sales.orders" not in visible
                invalid = client.put(f"/api/system/roles/{worker_role.json()['id']}/permissions",
                                     json={"permissions": [{
                                         "menu_id": str(other_dept), "action_code": "view",
                                     }]}, headers=headers)
                assert invalid.status_code == 422
                assert employee_client.get("/api/inventory/balances").status_code == 200
                assert client.put(f"/api/system/roles/{worker_role.json()['id']}/permissions",
                                  json={"permissions": [{
                                      "menu_id": inventory_query["id"], "action_code": "adjust",
                                  }]}, headers=headers).status_code == 422
                assert client.put(f"/api/system/roles/{worker_role.json()['id']}/permissions",
                                  json={"permissions": []}, headers=headers).status_code == 200
                assert employee_client.get("/api/inventory/balances").status_code == 403
                assert client.post(f"/api/system/users/{employee.json()['id']}/reset-password",
                                   json={"password": "NewEmployeePassword123!"},
                                   headers=headers).status_code == 204
                assert employee_client.get("/api/auth/me").status_code == 401
            assert client.delete(f"/api/system/users/{employee.json()['id']}",
                                 headers=headers).status_code == 204
            assert client.post("/api/auth/login", json={
                "organization_code": org_code, "username": "worker1",
                "password": "NewEmployeePassword123!",
            }).status_code == 401
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
