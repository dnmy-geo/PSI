from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def test_manual_adjustment_and_reversal_keep_audit_and_nonnegative_stock() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        code = f"adjust_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=code, org_name="Adjustment factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
            org = db.execute(text("SELECT id FROM organizations WHERE code = :code"),
                             {"code": code}).scalar_one()
            warehouse = db.execute(text("""
                SELECT id FROM warehouses WHERE organization_id = :org AND code = 'RAW'
            """), {"org": org}).scalar_one()
        with TestClient(app, base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json={
                "organization_code": code, "username": "admin",
                "password": "TestOnlyPassword123!",
            })
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}
            unit = client.post("/api/units", json={
                "code": "PCS", "name": "Pieces", "precision_scale": 0,
            }, headers=headers)
            assert unit.status_code == 201, unit.text
            item = client.post("/api/items", json={
                "code": "MAT", "name": "Material", "item_type": "raw_material",
                "base_unit_id": unit.json()["id"],
            }, headers=headers)
            assert item.status_code == 201, item.text
            item_id = item.json()["id"]
            payload = {
                "document_no": "ADJ-001", "document_date": "2026-10-01",
                "warehouse_id": str(warehouse), "reason": "期初差异复核",
                "lines": [{"item_id": item_id, "quantity_delta_base": "5"}],
            }
            assert client.post("/api/inventory/adjustments", json={
                **payload, "lines": [{"item_id": item_id,
                                       "quantity_delta_base": "0"}],
            }, headers=headers).status_code == 422
            created = client.post("/api/inventory/adjustments", json=payload,
                                  headers=headers)
            assert created.status_code == 201, created.text
            doc_id = created.json()["id"]
            posted = client.post(f"/api/inventory/adjustments/{doc_id}/post",
                                 headers=headers)
            assert posted.status_code == 200, posted.text
            assert posted.json()["status"] == "posted"
            assert client.post(f"/api/inventory/adjustments/{doc_id}/post",
                               headers=headers).status_code == 200
            assert client.put(f"/api/inventory/adjustments/{doc_id}", json=payload,
                              headers=headers).status_code == 409
            negative = client.post("/api/inventory/adjustments", json={
                **payload, "document_no": "ADJ-NEG",
                "lines": [{"item_id": item_id, "quantity_delta_base": "-6"}],
            }, headers=headers)
            assert negative.status_code == 201, negative.text
            assert client.post(f"/api/inventory/adjustments/{negative.json()['id']}/post",
                               headers=headers).status_code == 409
            reversed_doc = client.post(f"/api/inventory/adjustments/{doc_id}/reverse",
                                       json={"reason": "更正盘点依据"}, headers=headers)
            assert reversed_doc.status_code == 200, reversed_doc.text
            assert reversed_doc.json()["status"] == "reversed"
            assert client.post(f"/api/inventory/adjustments/{doc_id}/reverse",
                               json={"reason": "重试"}, headers=headers).status_code == 200
            logs = client.get("/api/system/audit-logs", params={
                "document_type": "stock_adjustment", "document_id": doc_id,
            })
            assert logs.status_code == 200, logs.text
            assert {row["action_code"] for row in logs.json()} >= {
                "stock_adjustment.create", "stock_adjustment.post",
                "stock_adjustment.reverse",
            }
            assert next(row for row in logs.json()
                        if row["action_code"] == "stock_adjustment.reverse")[
                            "reason"] == "更正盘点依据"
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                assert db.execute(text("""
                    SELECT quantity_base FROM stock_balances
                    WHERE organization_id = :org AND warehouse_id = :warehouse
                      AND item_id = :item
                """), {"org": org, "warehouse": warehouse,
                       "item": item_id}).scalar_one() == Decimal(0)
                assert db.execute(text("""
                    SELECT count(*) FROM stock_movements
                    WHERE organization_id = :org
                      AND source_type = 'stock_adjustment_reversal'
                      AND reversal_of_id IS NOT NULL
                """), {"org": org}).scalar_one() == 1
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
