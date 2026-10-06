from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def test_purchase_partial_receipt_return_and_supplier_replenishment() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"purchase_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=org_code, org_name="Purchase factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
            org_id = db.execute(text("SELECT id FROM organizations WHERE code = :code"),
                                {"code": org_code}).scalar_one()
            raw_warehouse = db.execute(text("""
                SELECT id FROM warehouses WHERE organization_id = :org AND code = 'RAW'
            """), {"org": org_id}).scalar_one()

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
                "code": "MATERIAL", "name": "Material", "item_type": "raw_material",
                "base_unit_id": unit.json()["id"],
            }, headers=headers)
            supplier = client.post("/api/parties", json={
                "code": "SUP", "name": "Supplier", "types": ["supplier"],
            }, headers=headers)
            assert unit.status_code == item.status_code == supplier.status_code == 201
            body = {
                "document_no": "PO-001", "supplier_id": supplier.json()["id"],
                "document_date": "2026-10-01",
                "lines": [{"item_id": item.json()["id"], "unit_id": unit.json()["id"],
                           "quantity": "5", "unit_price": "10"}],
            }
            order = client.post("/api/purchase/orders", json=body, headers=headers)
            assert order.status_code == 201, order.text
            order_id = order.json()["id"]
            order_line_id = order.json()["lines"][0]["id"]
            assert order.json()["status"] == "draft"
            assert client.get("/api/purchase/orders").status_code == 200

            def receipt_body(no: str, quantity: str) -> dict:
                return {
                    "document_no": no, "purchase_order_id": order_id,
                    "warehouse_id": str(raw_warehouse), "document_date": "2026-10-02",
                    "lines": [{"purchase_order_line_id": order_line_id,
                               "item_id": item.json()["id"],
                               "unit_id": unit.json()["id"], "quantity": quantity}],
                }

            assert client.post("/api/purchase/receipts", json=receipt_body(
                "PR-EARLY", "1"), headers=headers).status_code == 409
            assert client.post(f"/api/purchase/orders/{order_id}/open",
                               headers=headers).status_code == 200
            alerts = client.get("/api/workbench/alerts")
            assert alerts.status_code == 200, alerts.text
            assert any(row["code"] == "purchase_unreceived" and
                       row["document_id"] == order_id for row in alerts.json())
            assert client.put(f"/api/purchase/orders/{order_id}", json=body,
                              headers=headers).status_code == 409

            first = client.post("/api/purchase/receipts", json=receipt_body(
                "PR-001", "3"), headers=headers)
            assert first.status_code == 201, first.text
            receipt_id = first.json()["id"]
            receipt_line_id = first.json()["lines"][0]["id"]
            edited = client.put(f"/api/purchase/receipts/{receipt_id}", json={
                **receipt_body("PR-001", "3"), "remark": "Selected usable goods",
            }, headers=headers)
            assert edited.status_code == 200, edited.text
            receipt_line_id = edited.json()["lines"][0]["id"]
            posted = client.post(f"/api/purchase/receipts/{receipt_id}/post", headers=headers)
            assert posted.status_code == 200, posted.text
            assert posted.json()["lines"][0]["amount"] == "30.00"
            assert client.post(f"/api/purchase/receipts/{receipt_id}/post",
                               headers=headers).status_code == 200
            assert client.delete(f"/api/purchase/receipts/{receipt_id}", headers=headers).status_code == 409
            assert client.get(f"/api/purchase/orders/{order_id}").json()["lines"][0][
                "unreceived_quantity_base"] == "2.000000"
            purchase_report = client.get("/api/reports/purchase", params={
                "date_from": "2026-10-01", "date_to": "2026-10-31",
            })
            assert purchase_report.status_code == 200, purchase_report.text
            assert Decimal(purchase_report.json()[0]["quantities"]["unreceived_base"]) == 2
            before_open = client.get("/api/reports/purchase", params={
                "date_from": "2026-10-01", "date_to": "2026-10-01",
            })
            assert Decimal(before_open.json()[0]["quantities"]["unreceived_base"]) == 0
            connection.execute(text("""
                UPDATE stock_movements SET posted_at = '2026-10-02 12:00:00+08'
                WHERE source_type = 'purchase_receipt' AND source_id = :id
            """), {"id": receipt_id})
            connection.execute(text("""
                UPDATE purchase_receipts SET posted_at = '2026-10-02 12:00:00+08'
                WHERE id = :id
            """), {"id": receipt_id})
            connection.execute(text("""
                UPDATE audit_logs SET occurred_at = '2026-10-02 11:00:00+08'
                WHERE action_code = 'purchase_order.open' AND document_id = :id
            """), {"id": order_id})

            over = client.post("/api/purchase/receipts", json=receipt_body(
                "PR-OVER", "3"), headers=headers)
            assert over.status_code == 201, over.text
            assert client.post(f"/api/purchase/receipts/{over.json()['id']}/post",
                               headers=headers).status_code == 409

            def return_body(no: str, quantity: str) -> dict:
                return {
                    "document_no": no, "original_receipt_id": receipt_id,
                    "warehouse_id": str(raw_warehouse), "document_date": "2026-10-03",
                    "lines": [{"purchase_receipt_line_id": receipt_line_id,
                               "item_id": item.json()["id"],
                               "unit_id": unit.json()["id"], "quantity": quantity}],
                }

            purchase_return = client.post("/api/purchase/returns", json=return_body(
                "PRET-001", "1"), headers=headers)
            assert purchase_return.status_code == 201, purchase_return.text
            return_id = purchase_return.json()["id"]
            # 单号留空（前端不传 document_no）：按 CT+日期+四位流水生成。
            without_number = return_body("PRET-001", "1")
            del without_number["document_no"]
            auto_numbered = client.post("/api/purchase/returns", json=without_number,
                                        headers=headers)
            assert auto_numbered.status_code == 201, auto_numbered.text
            assert auto_numbered.json()["document_no"].startswith("CT20261003")
            assert client.delete(f"/api/purchase/returns/{auto_numbered.json()['id']}",
                                 headers=headers).status_code == 204
            updated_return = client.put(f"/api/purchase/returns/{return_id}", json={
                **return_body("PRET-001", "1"), "remark": "Defective one",
            }, headers=headers)
            assert updated_return.status_code == 200, updated_return.text
            assert client.post(f"/api/purchase/returns/{return_id}/post",
                               headers=headers).status_code == 200
            assert client.post(f"/api/purchase/returns/{return_id}/post",
                               headers=headers).status_code == 200
            assert client.delete(f"/api/purchase/returns/{return_id}", headers=headers).status_code == 409
            current = client.get(f"/api/purchase/orders/{order_id}").json()["lines"][0]
            assert current["received_quantity_base"] == "2.000000"
            assert current["unreceived_quantity_base"] == "3.000000"
            assert connection.execute(text("""
                SELECT COALESCE(sum(amount_delta), 0) FROM business_amount_entries
                WHERE organization_id = :org AND direction = 'payable'
            """), {"org": org_id}).scalar_one() == Decimal("20.00")

            over_return = client.post("/api/purchase/returns", json=return_body(
                "PRET-OVER", "3"), headers=headers)
            assert over_return.status_code == 201, over_return.text
            assert client.post(f"/api/purchase/returns/{over_return.json()['id']}/post",
                               headers=headers).status_code == 409
            assert client.delete(f"/api/purchase/returns/{over_return.json()['id']}",
                                 headers=headers).status_code == 204

            replenished = client.post(f"/api/purchase/receipts/{over.json()['id']}/post",
                                      headers=headers)
            assert replenished.status_code == 200, replenished.text
            assert replenished.json()["lines"][0]["amount"] == "30.00"
            current = client.get(f"/api/purchase/orders/{order_id}").json()["lines"][0]
            assert current["received_quantity_base"] == "5.000000"
            assert current["unreceived_quantity_base"] == "0.000000"
            assert connection.execute(text("""
                SELECT COALESCE(sum(amount_delta), 0) FROM business_amount_entries
                WHERE organization_id = :org AND direction = 'payable'
            """), {"org": org_id}).scalar_one() == Decimal("50.00")
            balance = client.get("/api/inventory/balances", params={
                "warehouse_id": str(raw_warehouse),
            }).json()
            assert balance[0]["quantity_base"] == "5.000000"

            assert client.post(f"/api/purchase/orders/{order_id}/close",
                               json={"remark": "  "}, headers=headers).status_code == 422
            assert client.post(f"/api/purchase/orders/{order_id}/close",
                               json={"remark": "Supplier finished"},
                               headers=headers).status_code == 200
            assert client.post("/api/purchase/receipts", json=receipt_body(
                "PR-LATE", "1"), headers=headers).status_code == 409
            assert client.post(f"/api/purchase/returns/{return_id}/reverse",
                               json={"reason": "重新核对"}, headers=headers).status_code == 409
            assert client.post(f"/api/purchase/receipts/{receipt_id}/reverse",
                               json={"reason": "重新核对"}, headers=headers).status_code == 409
            replenishment_id = over.json()["id"]
            reversed_replenishment = client.post(
                f"/api/purchase/receipts/{replenishment_id}/reverse",
                json={"reason": "撤销补入"}, headers=headers)
            assert reversed_replenishment.status_code == 200, reversed_replenishment.text
            assert reversed_replenishment.json()["status"] == "reversed"
            assert client.post(f"/api/purchase/receipts/{replenishment_id}/reverse",
                               json={"reason": "重试"}, headers=headers).status_code == 200
            assert client.post(f"/api/purchase/returns/{return_id}/reverse",
                               json={"reason": "撤销退货"}, headers=headers).status_code == 200
            assert client.post(f"/api/purchase/receipts/{receipt_id}/reverse",
                               json={"reason": "撤销入库"}, headers=headers).status_code == 200
            assert connection.execute(text("""
                SELECT COALESCE(sum(amount_delta), 0) FROM business_amount_entries
                WHERE organization_id = :org AND direction = 'payable'
            """), {"org": org_id}).scalar_one() == 0
            current = client.get(f"/api/purchase/orders/{order_id}").json()["lines"][0]
            assert Decimal(current["received_quantity_base"]) == 0
            historical = client.get("/api/reports/purchase", params={
                "date_from": "2026-10-01", "date_to": "2026-10-02",
            })
            assert historical.status_code == 200, historical.text
            assert Decimal(historical.json()[0]["quantities"]["unreceived_base"]) == 2
            assert connection.execute(text("""
                SELECT count(*) FROM stock_movements
                WHERE organization_id = :org
                  AND source_type IN ('purchase_receipt_reversal', 'purchase_return_reversal')
                  AND reversal_of_id IS NOT NULL
            """), {"org": org_id}).scalar_one() == 3
            report = client.get("/api/reports/purchase", params={
                "date_from": "2020-01-01", "date_to": "2100-12-31",
            })
            assert report.status_code == 200, report.text
            assert Decimal(report.json()[0]["quantities"]["received_base"]) == 0
            assert Decimal(report.json()[0]["business_amount"]) == 0
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
