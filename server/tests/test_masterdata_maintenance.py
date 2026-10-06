from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def test_categories_parties_and_catalog_maintenance() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"master_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(
                db, org_code=org_code, org_name="主数据测试工厂",
                admin_username="admin", admin_password="TestOnlyPassword123!",
            )
            org_id = db.execute(text("SELECT id FROM organizations WHERE code = :code"), {"code": org_code}).scalar_one()
            other_org_id = db.execute(
                text("INSERT INTO organizations (code, name) VALUES (:code, '另一工厂') RETURNING id"),
                {"code": f"other_{uuid4().hex[:8]}"},
            ).scalar_one()
            other_category_id = db.execute(
                text("""
                    INSERT INTO item_categories (organization_id, code, name)
                    VALUES (:org, 'OTHER', '其他') RETURNING id
                """),
                {"org": other_org_id},
            ).scalar_one()
            db.commit()

        with TestClient(app, base_url="https://testserver") as client:
            login = client.post(
                "/api/auth/login",
                json={"organization_code": org_code, "username": "admin", "password": "TestOnlyPassword123!"},
            )
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}

            root = client.post(
                "/api/item-categories", json={"code": "RAW", "name": "原料", "parent_id": None},
                headers=headers,
            )
            assert root.status_code == 201, root.text
            child = client.post(
                "/api/item-categories",
                json={"code": "METAL", "name": "金属", "parent_id": root.json()["id"]},
                headers=headers,
            )
            assert child.status_code == 201, child.text
            assert client.put(
                f"/api/item-categories/{root.json()['id']}",
                json={"code": "RAW", "name": "原料", "parent_id": child.json()["id"]},
                headers=headers,
            ).status_code == 422
            assert client.post(
                "/api/item-categories",
                json={"code": "BAD", "name": "错误", "parent_id": str(other_category_id)},
                headers=headers,
            ).status_code == 422
            assert client.delete(f"/api/item-categories/{root.json()['id']}", headers=headers).status_code == 409

            unit = client.post(
                "/api/units", json={"code": "KG", "name": "千克", "precision_scale": 3}, headers=headers
            )
            assert unit.status_code == 201, unit.text
            item = client.post(
                "/api/items",
                json={
                    "code": "STEEL", "name": "钢材", "item_type": "raw_material",
                    "base_unit_id": unit.json()["id"], "category_id": child.json()["id"],
                },
                headers=headers,
            )
            assert item.status_code == 201, item.text
            # 按 id 取单条：列表页的「详情」「编辑」都依赖它，缺了会返回 405 而打不开弹窗。
            for path, created in (("units", unit), ("items", item)):
                fetched = client.get(f"/api/{path}/{created.json()['id']}")
                assert fetched.status_code == 200, fetched.text
                assert fetched.json()["id"] == created.json()["id"]
            assert client.get(f"/api/units/{uuid4()}").status_code == 404
            assert client.put(
                f"/api/units/{unit.json()['id']}",
                json={"code": "KG", "name": "千克", "precision_scale": 0, "is_active": True},
                headers=headers,
            ).status_code == 409
            assert client.delete(f"/api/units/{unit.json()['id']}", headers=headers).status_code == 409
            edited = client.put(
                f"/api/items/{item.json()['id']}",
                json={
                    "code": "STEEL_2", "name": "钢材二号", "category_id": child.json()["id"],
                    "is_active": False,
                },
                headers=headers,
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["item_type"] == "raw_material"
            assert client.delete(f"/api/items/{item.json()['id']}", headers=headers).status_code == 204
            assert client.delete(f"/api/item-categories/{child.json()['id']}", headers=headers).status_code == 204
            assert client.delete(f"/api/item-categories/{root.json()['id']}", headers=headers).status_code == 204
            assert client.delete(f"/api/units/{unit.json()['id']}", headers=headers).status_code == 204

            party = client.post(
                "/api/parties",
                json={
                    "code": "ACME", "name": "同一往来单位", "contact_name": "张三",
                    "types": ["customer", "supplier", "processor"],
                },
                headers=headers,
            )
            assert party.status_code == 201, party.text
            party_id = party.json()["id"]
            assert party.json()["types"] == ["customer", "processor", "supplier"]
            assert len(client.get("/api/parties?party_type=supplier").json()) == 1
            assert len(client.get("/api/parties?party_type=customer").json()) == 1

            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                db.execute(
                    text("""
                        INSERT INTO purchase_orders (organization_id, document_no, supplier_id, document_date)
                        VALUES (:org, 'TEST-PO-001', :party, CURRENT_DATE)
                    """),
                    {"org": org_id, "party": party_id},
                )
                db.commit()

            assert client.put(
                f"/api/parties/{party_id}",
                json={"code": "ACME", "name": "同一往来单位", "types": ["customer"], "is_active": True},
                headers=headers,
            ).status_code == 409
            updated = client.put(
                f"/api/parties/{party_id}",
                json={
                    "code": "ACME2", "name": "同一往来单位", "types": ["customer", "supplier"],
                    "is_active": False,
                },
                headers=headers,
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["types"] == ["customer", "supplier"]
            assert client.delete(f"/api/parties/{party_id}", headers=headers).status_code == 409

        assert connection.execute(
            text("SELECT count(*) FROM audit_logs WHERE organization_id = :org"), {"org": org_id}
        ).scalar_one() >= 10
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
