from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def test_sales_order_number_uses_document_date_and_never_reuses_deleted_number() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"sales_number_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=org_code, org_name="Number factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
        with TestClient(app, base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json={
                "organization_code": org_code, "username": "admin",
                "password": "TestOnlyPassword123!",
            })
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}
            unit = client.post("/api/units", json={
                "code": "PCS", "name": "Pieces", "precision_scale": 0,
            }, headers=headers).json()
            item = client.post("/api/items", json={
                "code": "PRODUCT", "name": "Product", "item_type": "finished",
                "base_unit_id": unit["id"],
            }, headers=headers).json()
            customer = client.post("/api/parties", json={
                "code": "CUST", "name": "Customer", "types": ["customer"],
            }, headers=headers).json()
            body = {"customer_id": customer["id"], "document_date": "2026-10-03",
                    "lines": [{"item_id": item["id"], "unit_id": unit["id"],
                               "quantity": "1", "unit_price": "10"}]}
            legacy = client.post("/api/sales/orders", json={
                **body, "document_no": "XS202610030007",
            }, headers=headers)
            assert legacy.status_code == 201, legacy.text
            first = client.post("/api/sales/orders", json=body, headers=headers)
            second = client.post("/api/sales/orders", json=body, headers=headers)
            assert first.status_code == second.status_code == 201
            assert first.json()["document_no"] == "XS202610030008"
            assert second.json()["document_no"] == "XS202610030009"
            assert client.delete(f"/api/sales/orders/{second.json()['id']}",
                                 headers=headers).status_code == 204
            third = client.post("/api/sales/orders", json=body, headers=headers)
            assert third.json()["document_no"] == "XS202610030010"
            next_day = client.post("/api/sales/orders", json={
                **body, "document_date": "2026-10-04",
            }, headers=headers)
            assert next_day.json()["document_no"] == "XS202610040001"
            edited = client.put(f"/api/sales/orders/{first.json()['id']}",
                                json={**body, "document_no": "CHANGED", "remark": "Updated"}, headers=headers)
            assert edited.status_code == 200, edited.text
            assert edited.json()["document_no"] == "XS202610030008"
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()


def test_sales_order_approval_reject_resubmit_and_close() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"sales_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=org_code, org_name="Sales factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
            org_id = db.execute(text("SELECT id FROM organizations WHERE code = :code"),
                                {"code": org_code}).scalar_one()

        with TestClient(app, base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json={
                "organization_code": org_code, "username": "admin", "password": "TestOnlyPassword123!",
            })
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}
            unit = client.post("/api/units", json={
                "code": "PCS", "name": "Pieces", "precision_scale": 0,
            }, headers=headers)
            assert unit.status_code == 201, unit.text
            finished = client.post("/api/items", json={
                "code": "PRODUCT", "name": "Product", "item_type": "finished",
                "base_unit_id": unit.json()["id"],
            }, headers=headers)
            raw = client.post("/api/items", json={
                "code": "RAW", "name": "Raw", "item_type": "raw_material",
                "base_unit_id": unit.json()["id"],
            }, headers=headers)
            assert finished.status_code == raw.status_code == 201
            customer = client.post("/api/parties", json={
                "code": "CUST", "name": "Customer", "types": ["customer"],
            }, headers=headers)
            assert customer.status_code == 201, customer.text
            role = client.post("/api/system/roles", json={
                "code": "sales_manager", "name": "Sales manager",
            }, headers=headers)
            assert role.status_code == 201, role.text
            manager = client.post("/api/system/users", json={
                "username": "manager", "display_name": "Manager",
                "password": "ManagerPassword123!", "role_ids": [role.json()["id"]],
            }, headers=headers)
            assert manager.status_code == 201, manager.text
            initial_config = client.get("/api/approval/configs/sales_order").json()
            admin_role_id = initial_config["steps"][0]["approver_role_id"]
            config = client.put("/api/approval/configs/sales_order", json={
                "steps": [{"approver_role_id": admin_role_id},
                          {"approver_user_id": manager.json()["id"]}],
            }, headers=headers)
            assert config.status_code == 200, config.text
            body = {
                "document_no": "SO-001", "customer_id": customer.json()["id"],
                "document_date": "2026-10-01",
                "lines": [{"item_id": finished.json()["id"],
                           "unit_id": unit.json()["id"], "quantity": "5",
                           "unit_price": "10.50"}],
            }
            # 销售单不限定物料类型：原材料也能直接开单（换一个单号，校验后删除草稿）。
            raw_order = client.post("/api/sales/orders", json=dict(body, document_no="SO-RAW", lines=[
                dict(body["lines"][0], item_id=raw.json()["id"]),
            ]), headers=headers)
            assert raw_order.status_code == 201, raw_order.text
            assert raw_order.json()["lines"][0]["item_id"] == raw.json()["id"]
            assert client.delete(f"/api/sales/orders/{raw_order.json()['id']}",
                                 headers=headers).status_code == 204
            created = client.post("/api/sales/orders", json=body, headers=headers)
            assert created.status_code == 201, created.text
            order_id = created.json()["id"]
            assert created.json()["lines"][0]["amount"] == "52.50"
            assert created.json()["lines"][0]["unshipped_quantity_base"] == "5.000000"
            assert client.get("/api/inventory/balances").json() == []

            submitted = client.post(f"/api/sales/orders/{order_id}/submit", headers=headers)
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["status"] == "pending_approval"
            assert client.post(f"/api/sales/orders/{order_id}/submit", headers=headers).status_code == 409
            assert client.put(f"/api/sales/orders/{order_id}", json=body, headers=headers).status_code == 409
            instances = client.get(f"/api/approval/documents/sales_order/{order_id}/instances")
            assert instances.status_code == 200, instances.text
            assert len(instances.json()) == 1
            first_instance = instances.json()[0]
            assert first_instance["config_version"] == config.json()["version"]
            assert len(first_instance["tasks"]) == 2
            first_task = first_instance["tasks"][0]["id"]
            second_task = first_instance["tasks"][1]["id"]
            assert len(client.get("/api/approval/tasks/mine").json()) == 1

            changed_config = client.put("/api/approval/configs/sales_order", json={
                "steps": [{"approver_role_id": admin_role_id}],
            }, headers=headers)
            assert changed_config.status_code == 200, changed_config.text
            with TestClient(app, base_url="https://testserver") as manager_client:
                worker_login = manager_client.post("/api/auth/login", json={
                    "organization_code": org_code, "username": "manager",
                    "password": "ManagerPassword123!",
                })
                assert worker_login.status_code == 200, worker_login.text
                worker_headers = {"X-CSRF-Token": worker_login.json()["csrf_token"]}
                assert manager_client.get("/api/approval/tasks/mine").json() == []
                assert manager_client.post(f"/api/approval/tasks/{first_task}/decision",
                                           json={"decision": "approve"},
                                           headers=worker_headers).status_code == 403
                approved_step = client.post(f"/api/approval/tasks/{first_task}/decision",
                                            json={"decision": "approve"}, headers=headers)
                assert approved_step.status_code == 200, approved_step.text
                assert approved_step.json()["status"] == "pending"
                assert approved_step.json()["current_step_no"] == 2
                assert client.post(f"/api/approval/tasks/{first_task}/decision",
                                   json={"decision": "approve"}, headers=headers).status_code == 409
                assert [task["id"] for task in manager_client.get(
                    "/api/approval/tasks/mine").json()] == [second_task]
                assert manager_client.post(f"/api/approval/tasks/{second_task}/decision",
                                           json={"decision": "approve"},
                                           headers=worker_headers).status_code == 403
                sales_menu_id = next(menu["id"] for menu in client.get(
                    "/api/system/menus").json() if menu["code"] == "sales.orders")
                grant = client.put(f"/api/system/roles/{role.json()['id']}/permissions",
                                   json={"permissions": [
                                       {"menu_id": sales_menu_id, "action_code": "view"},
                                       {"menu_id": sales_menu_id, "action_code": "approve"},
                                   ]}, headers=headers)
                assert grant.status_code == 200, grant.text
                assert manager_client.post(f"/api/approval/tasks/{second_task}/decision",
                                           json={"decision": "reject"},
                                           headers=worker_headers).status_code == 422
                rejected = manager_client.post(f"/api/approval/tasks/{second_task}/decision",
                                               json={"decision": "reject", "opinion": "Revise"},
                                               headers=worker_headers)
                assert rejected.status_code == 200, rejected.text
                assert rejected.json()["status"] == "rejected"
            assert client.get(f"/api/sales/orders/{order_id}").json()["status"] == "rejected"
            edited = client.put(f"/api/sales/orders/{order_id}", json=body, headers=headers)
            assert edited.status_code == 200, edited.text
            assert edited.json()["status"] == "draft"
            assert client.post(f"/api/sales/orders/{order_id}/submit", headers=headers).status_code == 200
            instances = client.get(f"/api/approval/documents/sales_order/{order_id}/instances").json()
            assert len(instances) == 2
            new_instance = next(row for row in instances if row["status"] == "pending")
            assert len(new_instance["tasks"]) == 1
            done = client.post(f"/api/approval/tasks/{new_instance['tasks'][0]['id']}/decision",
                               json={"decision": "approve"}, headers=headers)
            assert done.status_code == 200, done.text
            assert done.json()["status"] == "approved"
            assert client.get(f"/api/sales/orders/{order_id}").json()["status"] == "approved"
            assert client.post(f"/api/sales/orders/{order_id}/close",
                               json={"remark": "Supplier stopped"},
                               headers=headers).json()["status"] == "closed"
            assert client.post(f"/api/sales/orders/{order_id}/close",
                               json={"remark": "Again"}, headers=headers).status_code == 409
            assert client.get("/api/inventory/balances").json() == []
        assert connection.execute(text("SELECT count(*) FROM stock_movements WHERE organization_id = :org"),
                                  {"org": org_id}).scalar_one() == 0
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
