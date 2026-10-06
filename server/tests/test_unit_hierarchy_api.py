"""单位层级：业务单位挂在基本单位下，只允许两层。

层级是全局的（units.base_unit_id + base_quantity），取代了原先按物料维护的
item_unit_conversions。两层限制是产品规则：已经是别人基本单位的单位，自己不能再挂
基本单位，因此不存在三级链条。
"""

from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def test_unit_hierarchy_stays_two_levels() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"unit_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=org_code, org_name="Factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
        with TestClient(app, base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json={
                "organization_code": org_code, "username": "admin", "password": "TestOnlyPassword123!",
            })
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}

            def make(code: str, **extra) -> dict:
                response = client.post("/api/units", json={
                    "code": code, "name": code, "precision_scale": 0, **extra,
                }, headers=headers)
                assert response.status_code == 201, response.text
                return response.json()

            piece = make("PCS")
            box = make("BOX", base_unit_id=piece["id"], base_quantity="12")

            # 被关联单位反向带出：件被箱挂在下面
            listed = {unit["code"]: unit for unit in client.get("/api/units").json()}
            assert [related["code"] for related in listed["PCS"]["related_units"]] == ["BOX"]
            assert listed["BOX"]["base_quantity"] == "12.000000"
            assert listed["PCS"]["related_units"][0]["base_quantity"] == "12.000000"

            # 已经是别人基本单位的单位，自己不能再挂基本单位。
            # 目标要选一个「自己没有基本单位」的，否则先撞上三级链那条校验（422）。
            standalone = make("EA")
            used_as_base = client.put(f"/api/units/{piece['id']}", json={
                "code": "PCS", "name": "PCS", "precision_scale": 0, "is_active": True,
                "base_unit_id": standalone["id"], "base_quantity": "1000",
            }, headers=headers)
            assert used_as_base.status_code == 409, used_as_base.text

            # 基本单位自身也不能有基本单位，否则就是三级链
            three_levels = client.post("/api/units", json={
                "code": "PALLET", "name": "托盘", "precision_scale": 0,
                "base_unit_id": box["id"], "base_quantity": "20",
            }, headers=headers)
            assert three_levels.status_code == 422, three_levels.text

            # 基本单位与基本数量必须成对
            assert client.post("/api/units", json={
                "code": "HALF", "name": "半个", "precision_scale": 0, "base_unit_id": piece["id"],
            }, headers=headers).status_code == 422

            # 不能自己当自己的基本单位
            assert client.put(f"/api/units/{box['id']}", json={
                "code": "BOX", "name": "BOX", "precision_scale": 0, "is_active": True,
                "base_unit_id": box["id"], "base_quantity": "1",
            }, headers=headers).status_code == 422
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
