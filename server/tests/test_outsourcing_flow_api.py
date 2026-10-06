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


def test_outsourcing_mixed_supply_and_partial_receipts() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        code = f"outside_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=code, org_name="Outsourcing factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
            org = db.execute(text("SELECT id FROM organizations WHERE code = :code"),
                             {"code": code}).scalar_one()
            actor = db.execute(text("SELECT id FROM users WHERE organization_id = :org"),
                               {"org": org}).scalar_one()
            raw_warehouse = db.execute(text("""
                SELECT id FROM warehouses WHERE organization_id = :org AND code = 'RAW'
            """), {"org": org}).scalar_one()
            finished_warehouse = db.execute(text("""
                SELECT id FROM warehouses WHERE organization_id = :org AND code = 'FINISHED'
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
            ids = {}
            for item_code, item_type in (("RAW", "raw_material"),
                                         ("SEMI", "semi_finished")):
                item = client.post("/api/items", json={
                    "code": item_code, "name": item_code, "item_type": item_type,
                    "base_unit_id": unit.json()["id"],
                }, headers=headers)
                assert item.status_code == 201, item.text
                ids[item_code] = item.json()["id"]
            processor = client.post("/api/parties", json={
                "code": "PROC", "name": "Processor", "types": ["processor"],
            }, headers=headers)
            assert processor.status_code == 201, processor.text
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                post_stock_changes(db, organization_id=org, actor_id=actor,
                                   changes=[StockChange(
                                       raw_warehouse, ids["RAW"], Decimal("5"),
                                       "test_seed", uuid4(), uuid4(), "opening_in")])
                db.commit()
            body = {
                "document_no": "OUT-001", "document_date": "2026-10-01",
                "processor_id": processor.json()["id"],
                "materials": [
                    {"item_id": ids["RAW"], "supply_party": "self",
                     "expected_quantity_base": "4"},
                    {"item_id": ids["RAW"], "supply_party": "processor",
                     "expected_quantity_base": "2"},
                ],
                "outputs": [{"item_id": ids["SEMI"],
                             "expected_quantity_base": "5", "unit_price": "3.333333"}],
            }
            order = client.post("/api/outsourcing/orders", json=body, headers=headers)
            assert order.status_code == 201, order.text
            order_id = order.json()["id"]
            materials = {line["supply_party"]: line["id"]
                         for line in order.json()["materials"]}
            output_id = order.json()["outputs"][0]["id"]
            assert client.post(f"/api/outsourcing/orders/{order_id}/open",
                               headers=headers).status_code == 200
            issue_body = {
                "document_no": "OI-001", "outsourcing_order_id": order_id,
                "warehouse_id": str(raw_warehouse), "document_date": "2026-10-02",
                "lines": [{"outsourcing_material_line_id": materials["self"],
                           "item_id": ids["RAW"], "quantity": "4",
                           "unit_id": unit.json()["id"]}],
            }
            assert client.post("/api/outsourcing/issues", json={
                **issue_body, "document_no": "OI-PROC",
                "lines": [dict(issue_body["lines"][0],
                               outsourcing_material_line_id=materials["processor"])],
            }, headers=headers).status_code == 422
            issued = client.post("/api/outsourcing/issues", json=issue_body,
                                 headers=headers)
            assert issued.status_code == 201, issued.text
            issue_id = issued.json()["id"]
            assert client.post(f"/api/outsourcing/issues/{issue_id}/post",
                               headers=headers).status_code == 200
            assert client.post(f"/api/outsourcing/issues/{issue_id}/post",
                               headers=headers).status_code == 200
            material_now = {line["supply_party"]: line
                            for line in client.get(f"/api/outsourcing/orders/{order_id}").json()[
                                "materials"]}
            assert Decimal(material_now["self"]["remaining_quantity_base"]) == 0
            assert Decimal(material_now["processor"]["remaining_quantity_base"]) == 2
            over = client.post("/api/outsourcing/issues", json={
                **issue_body, "document_no": "OI-OVER",
            }, headers=headers)
            assert over.status_code == 201, over.text
            assert client.post(f"/api/outsourcing/issues/{over.json()['id']}/post",
                               headers=headers).status_code == 409

            def receipt_body(no: str, quantity: str) -> dict:
                return {
                    "document_no": no, "outsourcing_order_id": order_id,
                    "warehouse_id": str(finished_warehouse),
                    "document_date": "2026-10-03",
                    "lines": [{"outsourcing_output_line_id": output_id,
                               "item_id": ids["SEMI"], "quantity": quantity,
                               "unit_id": unit.json()["id"]}],
                }

            first = client.post("/api/outsourcing/receipts", json=receipt_body(
                "OR-001", "2"), headers=headers)
            assert first.status_code == 201, first.text
            first_post = client.post(f"/api/outsourcing/receipts/{first.json()['id']}/post",
                                     headers=headers)
            assert first_post.status_code == 200, first_post.text
            assert Decimal(first_post.json()["lines"][0]["amount"]) == Decimal("6.67")
            second = client.post("/api/outsourcing/receipts", json=receipt_body(
                "OR-002", "3"), headers=headers)
            assert second.status_code == 201, second.text
            second_post = client.post(f"/api/outsourcing/receipts/{second.json()['id']}/post",
                                      headers=headers)
            assert second_post.status_code == 200, second_post.text
            assert Decimal(second_post.json()["lines"][0]["amount"]) == Decimal("10.00")
            assert client.post(f"/api/outsourcing/receipts/{second.json()['id']}/post",
                               headers=headers).status_code == 200
            full = client.post("/api/outsourcing/receipts", json=receipt_body(
                "OR-OVER", "1"), headers=headers)
            assert full.status_code == 201, full.text
            assert client.post(f"/api/outsourcing/receipts/{full.json()['id']}/post",
                               headers=headers).status_code == 409
            order_now = client.get(f"/api/outsourcing/orders/{order_id}").json()
            assert Decimal(order_now["outputs"][0]["remaining_quantity_base"]) == 0
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                assert db.execute(text("""
                    SELECT sum(amount_delta) FROM business_amount_entries
                    WHERE organization_id = :org AND source_type = 'outsourcing_receipt'
                """), {"org": org}).scalar_one() == Decimal("16.67")
                assert db.execute(text("""
                    SELECT quantity_base FROM stock_balances
                    WHERE organization_id = :org AND warehouse_id = :warehouse
                      AND item_id = :item
                """), {"org": org, "warehouse": raw_warehouse,
                       "item": ids["RAW"]}).scalar_one() == 1
            assert client.post(f"/api/outsourcing/orders/{order_id}/close",
                               json={"remark": "已交齐"}, headers=headers).status_code == 200
            assert client.post("/api/outsourcing/receipts", json=receipt_body(
                "OR-LATE", "1"), headers=headers).status_code == 409
            assert client.post(f"/api/outsourcing/issues/{issue_id}/reverse",
                               json={"reason": "更正委外单"}, headers=headers).status_code == 409
            for receipt_id in (second.json()["id"], first.json()["id"]):
                reversed_receipt = client.post(
                    f"/api/outsourcing/receipts/{receipt_id}/reverse",
                    json={"reason": "重新核对交回数量"}, headers=headers)
                assert reversed_receipt.status_code == 200, reversed_receipt.text
                assert reversed_receipt.json()["status"] == "reversed"
                assert client.post(f"/api/outsourcing/receipts/{receipt_id}/reverse",
                                   json={"reason": "重试"}, headers=headers).status_code == 200
            reversed_issue = client.post(f"/api/outsourcing/issues/{issue_id}/reverse",
                                         json={"reason": "重新核对供料"}, headers=headers)
            assert reversed_issue.status_code == 200, reversed_issue.text
            assert reversed_issue.json()["status"] == "reversed"
            restored = client.get(f"/api/outsourcing/orders/{order_id}").json()
            assert Decimal(restored["outputs"][0]["remaining_quantity_base"]) == 5
            restored_materials = {line["supply_party"]: line for line in restored["materials"]}
            assert Decimal(restored_materials["self"]["remaining_quantity_base"]) == 4
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                assert db.execute(text("""
                    SELECT sum(amount_delta) FROM business_amount_entries
                    WHERE organization_id = :org AND party_id = :party
                """), {"org": org, "party": processor.json()["id"]}).scalar_one() == 0
                assert db.execute(text("""
                    SELECT count(*) FROM stock_movements
                    WHERE organization_id = :org
                      AND source_type LIKE 'outsourcing_%_reversal'
                      AND reversal_of_id IS NOT NULL
                """), {"org": org}).scalar_one() == 3
            report = client.get("/api/reports/outsourcing", params={
                "date_from": "2020-01-01", "date_to": "2100-12-31",
            })
            assert report.status_code == 200, report.text
            rows = {row["item_id"]: row for row in report.json()}
            assert Decimal(rows[ids["RAW"]]["quantities"]["issued_base"]) == 0
            assert Decimal(rows[ids["SEMI"]]["business_amount"]) == 0
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
