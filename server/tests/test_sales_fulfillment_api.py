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


def test_partial_ship_return_replacement_and_receivable() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"fulfillment_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=org_code, org_name="Fulfillment factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
            org_id = db.execute(text("SELECT id FROM organizations WHERE code = :code"),
                                {"code": org_code}).scalar_one()
            actor_id = db.execute(text("SELECT id FROM users WHERE organization_id = :org"),
                                  {"org": org_id}).scalar_one()
            warehouses = dict(db.execute(text("""
                SELECT code, id FROM warehouses WHERE organization_id = :org
            """), {"org": org_id}).all())

        with TestClient(app, base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json={
                "organization_code": org_code, "username": "admin", "password": "TestOnlyPassword123!",
            })
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}
            unit = client.post("/api/units", json={
                "code": "PCS", "name": "Pieces", "precision_scale": 0,
            }, headers=headers)
            item = client.post("/api/items", json={
                "code": "PRODUCT", "name": "Product", "item_type": "finished",
                "base_unit_id": unit.json()["id"],
            }, headers=headers)
            customer = client.post("/api/parties", json={
                "code": "CUST", "name": "Customer", "types": ["customer"],
            }, headers=headers)
            assert unit.status_code == item.status_code == customer.status_code == 201
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                post_stock_changes(db, organization_id=org_id, actor_id=actor_id,
                                   changes=[StockChange(
                                       warehouse_id=warehouses["FINISHED"],
                                       item_id=item.json()["id"],
                                       quantity_delta_base=Decimal("5"),
                                       source_type="test_seed", source_id=uuid4(),
                                       source_line_id=uuid4(), movement_kind="opening_in",
                                   )])
                db.commit()

            order = client.post("/api/sales/orders", json={
                "document_no": "SO-001", "customer_id": customer.json()["id"],
                "document_date": "2026-10-01",
                "lines": [{"item_id": item.json()["id"], "unit_id": unit.json()["id"],
                           "quantity": "5", "unit_price": "10"}],
            }, headers=headers)
            assert order.status_code == 201, order.text
            order_id = order.json()["id"]
            order_line_id = order.json()["lines"][0]["id"]

            def shipment_body(no: str, quantity: str, warehouse: str,
                              kind: str = "normal", return_line_id: str | None = None) -> dict:
                return {
                    "document_no": no, "sales_order_id": order_id,
                    "warehouse_id": str(warehouses[warehouse]),
                    "document_date": "2026-10-01", "shipment_type": kind,
                    "lines": [{"sales_order_line_id": order_line_id,
                               "item_id": item.json()["id"],
                               "unit_id": unit.json()["id"], "quantity": quantity,
                               "replacement_return_line_id": return_line_id}],
                }

            assert client.post("/api/sales/shipments", json=shipment_body(
                "SH-EARLY", "1", "FINISHED"), headers=headers).status_code == 409
            assert client.post(f"/api/sales/orders/{order_id}/submit", headers=headers).status_code == 200
            instance = client.get(f"/api/approval/documents/sales_order/{order_id}/instances").json()[0]
            task_id = instance["tasks"][0]["id"]
            assert client.post(f"/api/approval/tasks/{task_id}/decision",
                               json={"decision": "approve"}, headers=headers).status_code == 200
            alerts = client.get("/api/workbench/alerts")
            assert alerts.status_code == 200, alerts.text
            assert any(row["code"] == "sales_unshipped" and
                       row["document_id"] == order_id for row in alerts.json())

            first = client.post("/api/sales/shipments", json=shipment_body(
                "SH-001", "3", "FINISHED"), headers=headers)
            assert first.status_code == 201, first.text
            first_id = first.json()["id"]
            first_line_id = first.json()["lines"][0]["id"]
            edited_first = client.put(f"/api/sales/shipments/{first_id}", json={
                **shipment_body("SH-001", "3", "FINISHED"), "remark": "First batch",
            }, headers=headers)
            assert edited_first.status_code == 200, edited_first.text
            first_line_id = edited_first.json()["lines"][0]["id"]
            assert client.post(f"/api/sales/shipments/{first_id}/post",
                               headers=headers).status_code == 200
            assert client.post(f"/api/sales/shipments/{first_id}/post",
                               headers=headers).status_code == 200
            assert client.put(f"/api/sales/shipments/{first_id}", json=shipment_body(
                "SH-001", "3", "FINISHED"), headers=headers).status_code == 409
            assert client.delete(f"/api/sales/shipments/{first_id}", headers=headers).status_code == 409
            current = client.get(f"/api/sales/orders/{order_id}").json()["lines"][0]
            assert current["shipped_quantity_base"] == "3.000000"
            assert current["unshipped_quantity_base"] == "2.000000"
            sales_report = client.get("/api/reports/sales", params={
                "date_from": "2026-10-01", "date_to": "2026-10-31",
            })
            assert sales_report.status_code == 200, sales_report.text
            assert Decimal(sales_report.json()[0]["quantities"]["unshipped_base"]) == 2
            before_approval = client.get("/api/reports/sales", params={
                "date_from": "2026-10-01", "date_to": "2026-10-01",
            })
            assert Decimal(before_approval.json()[0]["quantities"]["unshipped_base"]) == 0
            # Keep the first shipment in an earlier reporting period. Later reversals
            # and forced closure must not rewrite that period's outstanding quantity.
            connection.execute(text("""
                UPDATE stock_movements SET posted_at = '2026-10-02 12:00:00+08'
                WHERE source_type = 'sales_shipment' AND source_id = :id
            """), {"id": first_id})
            connection.execute(text("""
                UPDATE sales_shipments SET posted_at = '2026-10-02 12:00:00+08'
                WHERE id = :id
            """), {"id": first_id})
            connection.execute(text("""
                UPDATE approval_instances SET finished_at = '2026-10-02 11:00:00+08'
                WHERE document_type = 'sales_order' AND document_id = :id
            """), {"id": order_id})
            assert connection.execute(text("""
                SELECT COALESCE(sum(amount_delta), 0) FROM business_amount_entries
                WHERE organization_id = :org AND direction = 'receivable'
            """), {"org": org_id}).scalar_one() == Decimal("30.00")

            sales_return = client.post("/api/sales/returns", json={
                "document_no": "SR-001", "original_shipment_id": first_id,
                "target_warehouse_id": str(warehouses["SITE"]),
                "document_date": "2026-10-02",
                "lines": [{"sales_shipment_line_id": first_line_id,
                           "item_id": item.json()["id"],
                           "unit_id": unit.json()["id"], "quantity": "1"}],
            }, headers=headers)
            assert sales_return.status_code == 201, sales_return.text
            return_id = sales_return.json()["id"]
            return_line_id = sales_return.json()["lines"][0]["id"]
            edited_return = client.put(f"/api/sales/returns/{return_id}", json={
                "document_no": "SR-001", "original_shipment_id": first_id,
                "target_warehouse_id": str(warehouses["SITE"]),
                "document_date": "2026-10-02", "remark": "Selected one",
                "lines": [{"sales_shipment_line_id": first_line_id,
                           "item_id": item.json()["id"],
                           "unit_id": unit.json()["id"], "quantity": "1"}],
            }, headers=headers)
            assert edited_return.status_code == 200, edited_return.text
            return_line_id = edited_return.json()["lines"][0]["id"]
            assert client.post(f"/api/sales/returns/{return_id}/post",
                               headers=headers).status_code == 200
            assert client.post(f"/api/sales/returns/{return_id}/post",
                               headers=headers).status_code == 200
            assert client.delete(f"/api/sales/returns/{return_id}", headers=headers).status_code == 409
            current = client.get(f"/api/sales/orders/{order_id}").json()["lines"][0]
            assert current["shipped_quantity_base"] == "2.000000"
            assert current["unshipped_quantity_base"] == "3.000000"
            assert connection.execute(text("""
                SELECT COALESCE(sum(amount_delta), 0) FROM business_amount_entries
                WHERE organization_id = :org
            """), {"org": org_id}).scalar_one() == Decimal("30.00")

            over_normal = client.post("/api/sales/shipments", json=shipment_body(
                "SH-OVER", "3", "FINISHED"), headers=headers)
            assert over_normal.status_code == 201, over_normal.text
            assert client.post(f"/api/sales/shipments/{over_normal.json()['id']}/post",
                               headers=headers).status_code == 409
            assert client.delete(f"/api/sales/shipments/{over_normal.json()['id']}",
                                 headers=headers).status_code == 204

            replacement = client.post("/api/sales/shipments", json=shipment_body(
                "SH-REP-001", "1", "SITE", "replacement", return_line_id),
                headers=headers)
            assert replacement.status_code == 201, replacement.text
            replacement_id = replacement.json()["id"]
            assert client.post(f"/api/sales/shipments/{replacement_id}/post",
                               headers=headers).status_code == 200
            assert connection.execute(text("""
                SELECT COALESCE(sum(amount_delta), 0) FROM business_amount_entries
                WHERE organization_id = :org
            """), {"org": org_id}).scalar_one() == Decimal("30.00")
            over_replacement = client.post("/api/sales/shipments", json=shipment_body(
                "SH-REP-002", "1", "FINISHED", "replacement", return_line_id),
                headers=headers)
            assert over_replacement.status_code == 201, over_replacement.text
            assert client.post(f"/api/sales/shipments/{over_replacement.json()['id']}/post",
                               headers=headers).status_code == 409

            second = client.post("/api/sales/shipments", json=shipment_body(
                "SH-002", "2", "FINISHED"), headers=headers)
            assert second.status_code == 201, second.text
            assert client.post(f"/api/sales/shipments/{second.json()['id']}/post",
                               headers=headers).status_code == 200
            current = client.get(f"/api/sales/orders/{order_id}").json()["lines"][0]
            assert current["shipped_quantity_base"] == "5.000000"
            assert current["unshipped_quantity_base"] == "0.000000"
            assert connection.execute(text("""
                SELECT COALESCE(sum(amount_delta), 0) FROM business_amount_entries
                WHERE organization_id = :org
            """), {"org": org_id}).scalar_one() == Decimal("50.00")
            balances = {row["warehouse_id"]: row["quantity_base"] for row in client.get(
                "/api/inventory/balances").json()}
            assert balances[str(warehouses["FINISHED"])] == "0.000000"
            assert balances[str(warehouses["SITE"])] == "0.000000"
            assert client.post(f"/api/sales/orders/{order_id}/close",
                               json={"remark": "Complete"}, headers=headers).status_code == 200
            assert client.post("/api/sales/shipments", json=shipment_body(
                "SH-LATE", "1", "FINISHED"), headers=headers).status_code == 409
            assert client.post(f"/api/sales/returns/{return_id}/reverse",
                               json={"reason": "重做退货"}, headers=headers).status_code == 409
            assert client.post(f"/api/sales/shipments/{first_id}/reverse",
                               json={"reason": "重做发货"}, headers=headers).status_code == 409
            assert client.post(f"/api/sales/shipments/{replacement_id}/reverse",
                               json={"reason": "撤销补发"}, headers=headers).status_code == 200
            reversed_return = client.post(f"/api/sales/returns/{return_id}/reverse",
                                          json={"reason": "撤销退货"}, headers=headers)
            assert reversed_return.status_code == 200, reversed_return.text
            assert reversed_return.json()["status"] == "reversed"
            assert client.post(f"/api/sales/returns/{return_id}/reverse",
                               json={"reason": "重试"}, headers=headers).status_code == 200
            assert client.post(f"/api/sales/shipments/{first_id}/reverse",
                               json={"reason": "撤销发货"}, headers=headers).status_code == 200
            assert client.post(f"/api/sales/shipments/{second.json()['id']}/reverse",
                               json={"reason": "撤销第二批"}, headers=headers).status_code == 200
            assert connection.execute(text("""
                SELECT COALESCE(sum(amount_delta), 0) FROM business_amount_entries
                WHERE organization_id = :org AND direction = 'receivable'
            """), {"org": org_id}).scalar_one() == 0
            current = client.get(f"/api/sales/orders/{order_id}").json()["lines"][0]
            assert Decimal(current["shipped_quantity_base"]) == 0
            historical = client.get("/api/reports/sales", params={
                "date_from": "2026-10-01", "date_to": "2026-10-02",
            })
            assert historical.status_code == 200, historical.text
            assert Decimal(historical.json()[0]["quantities"]["unshipped_base"]) == 2
            assert connection.execute(text("""
                SELECT count(*) FROM stock_movements
                WHERE organization_id = :org
                  AND source_type IN ('sales_shipment_reversal', 'sales_return_reversal')
                  AND reversal_of_id IS NOT NULL
            """), {"org": org_id}).scalar_one() == 4
            report = client.get("/api/reports/sales", params={
                "date_from": "2020-01-01", "date_to": "2100-12-31",
            })
            assert report.status_code == 200, report.text
            assert Decimal(report.json()[0]["quantities"]["shipped_base"]) == 0
            assert Decimal(report.json()[0]["business_amount"]) == 0
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
