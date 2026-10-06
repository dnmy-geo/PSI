from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def test_approval_configuration_versions_and_approvers() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"approval_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=org_code, org_name="Approval factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
            other_org = db.execute(text("""
                INSERT INTO organizations (code, name) VALUES (:code, 'Other') RETURNING id
            """), {"code": f"other_{uuid4().hex[:8]}"}).scalar_one()
            other_user = db.execute(text("""
                INSERT INTO users (organization_id, username, display_name, password_hash)
                VALUES (:org, 'other', 'Other', 'test') RETURNING id
            """), {"org": other_org}).scalar_one()
            db.commit()

        with TestClient(app, base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json={
                "organization_code": org_code, "username": "admin", "password": "TestOnlyPassword123!",
            })
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}
            defaults = client.get("/api/approval/configs")
            assert defaults.status_code == 200, defaults.text
            assert {row["document_type"] for row in defaults.json()} == {"sales_order", "stocktake"}
            sales = client.get("/api/approval/configs/sales_order").json()
            assert sales["version"] == 1 and sales["is_enabled"] is True
            assert len(sales["steps"]) == 1
            admin_role = sales["steps"][0]["approver_role_id"]
            assert admin_role is not None

            empty_role = client.post("/api/system/roles", json={
                "code": "sales_manager", "name": "Sales manager",
            }, headers=headers)
            assert empty_role.status_code == 201, empty_role.text
            role_id = empty_role.json()["id"]
            assert client.put("/api/approval/configs/sales_order", json={
                "steps": [{"approver_role_id": role_id}],
            }, headers=headers).status_code == 422
            assert client.get("/api/approval/configs/sales_order").json()["version"] == 1

            approver = client.post("/api/system/users", json={
                "username": "approver", "display_name": "Approver",
                "password": "ApproverPassword123!", "role_ids": [role_id],
            }, headers=headers)
            assert approver.status_code == 201, approver.text
            assert client.put("/api/approval/configs/sales_order", json={
                "steps": [{"approver_user_id": str(other_user)}],
            }, headers=headers).status_code == 422
            updated = client.put("/api/approval/configs/sales_order", json={
                "steps": [{"approver_role_id": role_id},
                          {"approver_user_id": approver.json()["id"]}],
            }, headers=headers)
            assert updated.status_code == 200, updated.text
            assert updated.json()["version"] == 2
            assert [step["step_no"] for step in updated.json()["steps"]] == [1, 2]
            assert client.delete(f"/api/system/users/{approver.json()['id']}",
                                 headers=headers).status_code == 409
            disabled = client.put("/api/approval/configs/sales_order", json={
                "is_enabled": False, "steps": [{"approver_role_id": admin_role}],
            }, headers=headers)
            assert disabled.status_code == 200, disabled.text
            assert disabled.json()["version"] == 3
            assert disabled.json()["is_enabled"] is False
            assert client.delete(f"/api/system/users/{approver.json()['id']}",
                                 headers=headers).status_code == 204
            assert client.put("/api/approval/configs/sales_order", json={
                "steps": [{"approver_role_id": role_id, "approver_user_id": approver.json()["id"]}],
            }, headers=headers).status_code == 422
            assert client.get("/api/approval/configs/unknown").status_code == 422
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
