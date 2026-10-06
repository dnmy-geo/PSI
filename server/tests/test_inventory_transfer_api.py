from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.inventory.posting import StockChange, post_stock_changes
from app.main import app


def test_unit_conversion_and_transfer_posting() -> None:
    connection = get_engine().connect()
    outer_transaction = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"transfer_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(
                db, org_code=org_code, org_name="调拨测试工厂",
                admin_username="admin", admin_password="TestOnlyPassword123!",
            )
            org_id = db.execute(text("SELECT id FROM organizations WHERE code = :code"), {"code": org_code}).scalar_one()
            actor_id = db.execute(text("SELECT id FROM users WHERE organization_id = :id"), {"id": org_id}).scalar_one()
            warehouses = dict(db.execute(
                text("SELECT code, id FROM warehouses WHERE organization_id = :id"), {"id": org_id}
            ).all())

        with TestClient(app, base_url="https://testserver") as client:
            login = client.post(
                "/api/auth/login",
                json={"organization_code": org_code, "username": "admin", "password": "TestOnlyPassword123!"},
            )
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}

            each = client.post(
                "/api/units", json={"code": "PCS", "name": "件", "precision_scale": 0}, headers=headers
            )
            assert each.status_code == 201, each.text
            # 换算走全局单位层级：箱挂在件下面，1 箱 = 10 件
            box = client.post(
                "/api/units",
                json={"code": "BOX", "name": "箱", "precision_scale": 0,
                      "base_unit_id": each.json()["id"], "base_quantity": "10"},
                headers=headers,
            )
            assert box.status_code == 201, box.text
            item = client.post(
                "/api/items",
                json={
                    "code": "PART_A", "name": "部件A", "item_type": "raw_material",
                    "base_unit_id": each.json()["id"],
                },
                headers=headers,
            )
            assert item.status_code == 201, item.text
            item_id = item.json()["id"]

            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                post_stock_changes(
                    db, organization_id=org_id, actor_id=actor_id,
                    changes=[StockChange(
                        warehouses["RAW"], item_id, Decimal("20"),
                        "test_opening", uuid4(), uuid4(), "in",
                    )],
                )
                db.commit()

            body = {
                "document_no": "TR-001", "document_date": "2026-10-01",
                "source_warehouse_id": str(warehouses["RAW"]),
                "target_warehouse_id": str(warehouses["SITE"]),
                "lines": [{"item_id": item_id, "unit_id": box.json()["id"], "quantity": "1"}],
            }
            created = client.post("/api/inventory/transfers", json=body, headers=headers)
            assert created.status_code == 201, created.text
            assert created.json()["lines"][0]["quantity_base"] == "10.000000"
            transfer_id = created.json()["id"]
            assert client.get("/api/inventory/transfers/" + transfer_id).json()["status"] == "draft"

            # 单号留空（前端不传 document_no）：按 DB+日期+四位流水生成。
            without_number = {key: value for key, value in body.items() if key != "document_no"}
            auto_numbered = client.post("/api/inventory/transfers", json=without_number, headers=headers)
            assert auto_numbered.status_code == 201, auto_numbered.text
            assert auto_numbered.json()["document_no"].startswith("DB20261001")
            assert auto_numbered.json()["status"] == "draft"

            posted = client.post(f"/api/inventory/transfers/{transfer_id}/post", headers=headers)
            assert posted.status_code == 200, posted.text
            assert posted.json()["status"] == "posted"
            listed = client.get("/api/inventory/transfers", params={"status": "posted"})
            assert listed.status_code == 200, listed.text
            assert [doc["id"] for doc in listed.json()] == [transfer_id]
            assert client.post(f"/api/inventory/transfers/{transfer_id}/post", headers=headers).status_code == 200

            balances = {row["warehouse_id"]: row["quantity_base"] for row in client.get(
                "/api/inventory/balances"
            ).json()}
            assert balances[str(warehouses["RAW"])] == "10.000000"
            assert balances[str(warehouses["SITE"])] == "10.000000"

            movements = client.get("/api/inventory/movements", params={
                "warehouse_id": str(warehouses["SITE"]), "item_id": item_id,
            })
            assert movements.status_code == 200, movements.text
            assert len(movements.json()) == 1
            assert movements.json()[0]["source_id"] == transfer_id
            assert movements.json()[0]["movement_kind"] == "transfer_in"
            assert client.get("/api/inventory/movements", params={"limit": 0}).status_code == 422

            insufficient = dict(body, document_no="TR-002", lines=[dict(body["lines"][0], quantity="2")])
            second = client.post("/api/inventory/transfers", json=insufficient, headers=headers)
            assert second.status_code == 201, second.text
            failed = client.post(f"/api/inventory/transfers/{second.json()['id']}/post", headers=headers)
            assert failed.status_code == 409, failed.text
            assert client.get(f"/api/inventory/transfers/{second.json()['id']}").json()["status"] == "draft"
            reversed_transfer = client.post(
                f"/api/inventory/transfers/{transfer_id}/reverse",
                json={"reason": "仓库调拨录错"}, headers=headers)
            assert reversed_transfer.status_code == 200, reversed_transfer.text
            assert reversed_transfer.json()["status"] == "reversed"
            assert client.post(f"/api/inventory/transfers/{transfer_id}/reverse",
                               json={"reason": "重试"}, headers=headers).status_code == 200
            balances = {row["warehouse_id"]: Decimal(row["quantity_base"])
                        for row in client.get("/api/inventory/balances").json()}
            assert balances[str(warehouses["RAW"])] == 20
            assert balances[str(warehouses["SITE"])] == 0
            report = client.get("/api/reports/inventory", params={
                "date_from": "2020-01-01", "date_to": "2100-12-31",
            })
            assert report.status_code == 200, report.text
            raw = next(row for row in report.json()
                       if row["warehouse_id"] == str(warehouses["RAW"]))
            assert Decimal(raw["current_balance_base"]) == 20
    finally:
        app.dependency_overrides.clear()
        outer_transaction.rollback()
        connection.close()
