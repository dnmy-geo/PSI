from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.inventory.posting import StockChange, post_stock_changes
from app.main import app


def test_stocktake_freezes_warehouse_and_approval_posts_cutoff_difference() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        code = f"stocktake_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=code, org_name="Stocktake factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
            org = db.execute(text("SELECT id FROM organizations WHERE code = :code"),
                             {"code": code}).scalar_one()
            actor = db.execute(text("SELECT id FROM users WHERE organization_id = :org"),
                               {"org": org}).scalar_one()
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

            def post(delta: int) -> None:
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    post_stock_changes(db, organization_id=org, actor_id=actor,
                                       changes=[StockChange(
                                           warehouse, item_id, Decimal(delta),
                                           "test_seed", uuid4(), uuid4(), "test")])
                    db.commit()

            post(10)
            created = client.post("/api/inventory/stocktakes", json={
                "document_no": "ST-001", "document_date": "2026-10-01",
                "warehouse_id": str(warehouse),
            }, headers=headers)
            assert created.status_code == 201, created.text
            doc_id = created.json()["id"]
            started = client.post(f"/api/inventory/stocktakes/{doc_id}/start",
                                  headers=headers)
            assert started.status_code == 200, started.text
            assert Decimal(started.json()["lines"][0]["book_quantity_base"]) == 10
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                try:
                    post_stock_changes(db, organization_id=org, actor_id=actor,
                                       changes=[StockChange(
                                           warehouse, item_id, Decimal(-1),
                                           "test_seed", uuid4(), uuid4(), "test")])
                    assert False, "posting during counting should fail"
                except HTTPException as exc:
                    assert exc.status_code == 409
            counts = client.put(f"/api/inventory/stocktakes/{doc_id}/counts",
                                json={"lines": [{"item_id": item_id,
                                                 "counted_quantity_base": "8"}]},
                                headers=headers)
            assert counts.status_code == 200, counts.text
            assert Decimal(counts.json()["lines"][0]["difference_quantity_base"]) == -2
            submitted = client.post(f"/api/inventory/stocktakes/{doc_id}/submit",
                                    headers=headers)
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["status"] == "pending_approval"
            post(-3)
            tasks = client.get("/api/approval/tasks/mine").json()
            task = next(task for task in tasks if task["document_id"] == doc_id)
            decision = client.post(f"/api/approval/tasks/{task['id']}/decision",
                                   json={"decision": "approve"}, headers=headers)
            assert decision.status_code == 200, decision.text
            assert decision.json()["status"] == "approved"
            assert client.get(f"/api/inventory/stocktakes/{doc_id}").json()[
                "status"] == "approved"
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                balance = db.execute(text("""
                    SELECT quantity_base FROM stock_balances
                    WHERE organization_id = :org AND warehouse_id = :warehouse AND item_id = :item
                """), {"org": org, "warehouse": warehouse,
                       "item": item_id}).scalar_one()
                assert balance == 5
                report = client.get("/api/reports/inventory", params={
                    "date_from": "2026-10-01", "date_to": "2026-10-31",
                })
                assert report.status_code == 200, report.text
                assert Decimal(report.json()[0]["stocktake_difference_base"]) == -2
                assert db.execute(text("""
                    SELECT count(*) FROM stock_adjustments
                    WHERE organization_id = :org AND stocktake_id = :id AND status = 'posted'
                """), {"org": org, "id": doc_id}).scalar_one() == 1
            assert client.post(f"/api/approval/tasks/{task['id']}/decision",
                               json={"decision": "approve"},
                               headers=headers).status_code == 409

            rejected = client.post("/api/inventory/stocktakes", json={
                "document_no": "ST-002", "document_date": "2026-10-02",
                "warehouse_id": str(warehouse),
            }, headers=headers)
            assert rejected.status_code == 201, rejected.text
            rejected_id = rejected.json()["id"]
            assert client.post(f"/api/inventory/stocktakes/{rejected_id}/start",
                               headers=headers).status_code == 200
            assert client.put(f"/api/inventory/stocktakes/{rejected_id}/counts",
                              json={"lines": [{"item_id": item_id,
                                               "counted_quantity_base": "5"}]},
                              headers=headers).status_code == 200
            assert client.post(f"/api/inventory/stocktakes/{rejected_id}/submit",
                               headers=headers).status_code == 200
            task = next(task for task in client.get("/api/approval/tasks/mine").json()
                        if task["document_id"] == rejected_id)
            assert client.post(f"/api/approval/tasks/{task['id']}/decision",
                               json={"decision": "reject", "opinion": "重新核数"},
                               headers=headers).status_code == 200
            restarted = client.post(f"/api/inventory/stocktakes/{rejected_id}/start",
                                    headers=headers)
            assert restarted.status_code == 200, restarted.text
            assert restarted.json()["lines"][0]["counted_quantity_base"] is None
            assert Decimal(restarted.json()["lines"][0]["book_quantity_base"]) == 5
            assert client.put(f"/api/inventory/stocktakes/{rejected_id}/counts",
                              json={"lines": [{"item_id": item_id,
                                               "counted_quantity_base": "0"}]},
                              headers=headers).status_code == 200
            assert client.post(f"/api/inventory/stocktakes/{rejected_id}/submit",
                               headers=headers).status_code == 200
            post(-5)
            task = next(task for task in client.get("/api/approval/tasks/mine").json()
                        if task["document_id"] == rejected_id)
            decision_url = f"/api/approval/tasks/{task['id']}/decision"
            assert client.post(decision_url, json={"decision": "approve"},
                               headers=headers).status_code == 409
            assert client.get(f"/api/inventory/stocktakes/{rejected_id}").json()[
                "status"] == "pending_approval"
            post(5)
            assert client.post(decision_url, json={"decision": "approve"},
                               headers=headers).status_code == 200
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
