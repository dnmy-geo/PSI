from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app
from app.inventory.posting import StockChange, post_stock_changes
from app.system.carryover import HEADERS


def workbook_bytes(rows: list[tuple]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_four_carryover_types_preserve_progress_without_replaying_history() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        code = f"carryover_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=code, org_name="Carryover factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
            org = db.execute(text("SELECT id FROM organizations WHERE code = :code"),
                             {"code": code}).scalar_one()
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
            for item_code, item_type in (("FIN", "finished"), ("RAW", "raw_material")):
                item = client.post("/api/items", json={
                    "code": item_code, "name": item_code, "item_type": item_type,
                    "base_unit_id": unit.json()["id"],
                }, headers=headers)
                assert item.status_code == 201, item.text
            for party_code, kind in (("CUST", "customer"), ("SUP", "supplier"),
                                     ("PROC", "processor")):
                party = client.post("/api/parties", json={
                    "code": party_code, "name": party_code, "types": [kind],
                }, headers=headers)
                assert party.status_code == 201, party.text

            rows_by_kind = {
                "sales": [("OLD-SO", "NEW-SO", "2026-10-01", "CUST", "产出", "FIN", "PCS", 10, 4, 6, 12, None, "FINISHED")],
                "purchase": [("OLD-PO", "NEW-PO", "2026-10-01", "SUP", "产出", "RAW", "PCS", 12, 5, 7, 3, None, "RAW")],
                "production": [("OLD-MO", "NEW-MO", "2026-10-01", None, "产出", "FIN", "PCS", 8, 3, 5, None, None, None)],
                "outsourcing": [
                    ("OLD-OUT", "NEW-OUT", "2026-10-01", "PROC", "物料", "RAW", "PCS", 20, 8, 12, None, "我方", None),
                    ("OLD-OUT", "NEW-OUT", "2026-10-01", "PROC", "产出", "FIN", "PCS", 6, 2, 4, 5, None, None),
                ],
            }
            imported = {}
            for kind, rows in rows_by_kind.items():
                template = client.get(f"/api/system/carryover/template/{kind}")
                assert template.status_code == 200, template.text
                files = {"file": ("carryover.xlsx", workbook_bytes(rows),
                                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
                preview = client.post(f"/api/system/carryover/preview/{kind}",
                                      files=files, headers=headers)
                assert preview.status_code == 200, preview.text
                assert preview.json()[0]["remaining_lines"] >= 1
                response = client.post(f"/api/system/carryover/import/{kind}",
                                       files=files, headers=headers)
                assert response.status_code == 200, response.text
                assert response.json()["imported_documents"] == 1
                imported[kind] = client.get("/api/system/carryover/documents",
                                            params={"kind": kind}).json()[0]
                assert imported[kind]["original_document_no"] == rows[0][0]
                detail = client.get(f"/api/system/carryover/documents/{imported[kind]['id']}")
                assert detail.status_code == 200, detail.text
                assert len(detail.json()["lines"]) == len(rows)
                if kind in ("sales", "purchase"):
                    assert detail.json()["lines"][0]["historical_source_no"].startswith("HIST-")
                assert client.post(f"/api/system/carryover/import/{kind}",
                                   files=files, headers=headers).status_code == 409

            sale = client.get(f"/api/sales/orders/{imported['sales']['document_id']}")
            assert sale.status_code == 200, sale.text
            assert sale.json()["status"] == "draft"
            assert sale.json()["lines"][0]["unshipped_quantity_base"] == "6.000000"
            purchase = client.get(f"/api/purchase/orders/{imported['purchase']['document_id']}")
            assert purchase.status_code == 200, purchase.text
            assert purchase.json()["lines"][0]["unreceived_quantity_base"] == "7.000000"
            production = client.get(f"/api/production/orders/{imported['production']['document_id']}")
            assert production.status_code == 200, production.text
            assert production.json()["outputs"][0]["planned_quantity_base"] == 5
            plan = client.get(f"/api/production/plans/{imported['production']['related_plan_id']}")
            assert plan.status_code == 200, plan.text
            assert plan.json()["status"] == "draft"
            outsourcing = client.get(f"/api/outsourcing/orders/{imported['outsourcing']['document_id']}")
            assert outsourcing.status_code == 200, outsourcing.text
            assert outsourcing.json()["outputs"][0]["remaining_quantity_base"] == "4.000000"
            assert outsourcing.json()["materials"][0]["remaining_quantity_base"] == "12.000000"
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                assert db.execute(text("SELECT count(*) FROM stock_movements WHERE organization_id = :org"),
                                  {"org": org}).scalar_one() == 0
                assert db.execute(text("SELECT count(*) FROM business_amount_entries WHERE organization_id = :org"),
                                  {"org": org}).scalar_one() == 0
                progress = db.execute(text("""
                    SELECT original_quantity_base, completed_quantity_base, remaining_quantity_base
                    FROM carryover_lines l JOIN carryover_documents c ON c.id = l.carryover_document_id
                    WHERE c.organization_id = :org AND c.business_kind = 'sales'
                """), {"org": org}).one()
                assert tuple(map(str, progress)) == ("10.000000", "4.000000", "6.000000")
                sources = dict(db.execute(text("""
                    SELECT c.business_kind, l.historical_source_id
                    FROM carryover_lines l JOIN carryover_documents c ON c.id = l.carryover_document_id
                    WHERE c.organization_id = :org AND c.business_kind IN ('sales', 'purchase')
                """), {"org": org}).all())
                assert sources["sales"] is not None and sources["purchase"] is not None
                assert db.execute(text("""
                    SELECT count(*) FROM sales_shipments WHERE organization_id = :org AND is_opening_reference
                """), {"org": org}).scalar_one() == 1
                assert db.execute(text("""
                    SELECT count(*) FROM purchase_receipts WHERE organization_id = :org AND is_opening_reference
                """), {"org": org}).scalar_one() == 1
            assert client.post(f"/api/sales/shipments/{sources['sales']}/reverse",
                               json={"reason": "wrong"}, headers=headers).status_code == 409
            assert client.post(f"/api/purchase/receipts/{sources['purchase']}/reverse",
                               json={"reason": "wrong"}, headers=headers).status_code == 409
            assert client.post(f"/api/purchase/orders/{imported['purchase']['document_id']}/open",
                               headers=headers).status_code == 200
            assert client.post(f"/api/production/plans/{imported['production']['related_plan_id']}/open",
                               headers=headers).status_code == 200
            assert client.post(f"/api/production/orders/{imported['production']['document_id']}/open",
                               headers=headers).status_code == 200
            assert client.post(f"/api/outsourcing/orders/{imported['outsourcing']['document_id']}/open",
                               headers=headers).status_code == 200
            assert client.post(f"/api/sales/orders/{imported['sales']['document_id']}/submit",
                               headers=headers).status_code == 200
            # 报表是「截至期末」口径：期间上界必须覆盖测试当天，否则当天补记的开单/过账
            # 都落在期末之后，未发/未入会算成 0。
            today = date.today()
            period = {"date_from": "2026-10-01", "date_to": (today + timedelta(days=1)).isoformat()}
            sales_report = client.get("/api/reports/sales", params=period)
            purchase_report = client.get("/api/reports/purchase", params=period)
            assert sales_report.status_code == purchase_report.status_code == 200
            assert Decimal(sales_report.json()[0]["quantities"]["unshipped_base"]) == 0
            assert Decimal(purchase_report.json()[0]["quantities"]["unreceived_base"]) == 7

            historical_sale = client.get(f"/api/sales/shipments/{sources['sales']}").json()
            returned = client.post("/api/sales/returns", json={
                "document_no": "HIST-SR-1", "original_shipment_id": str(sources["sales"]),
                "target_warehouse_id": str(connection.execute(text("""
                    SELECT id FROM warehouses WHERE organization_id = :org AND code = 'FINISHED'
                """), {"org": org}).scalar_one()), "document_date": "2026-10-03",
                "lines": [{"sales_shipment_line_id": historical_sale["lines"][0]["id"],
                           "item_id": historical_sale["lines"][0]["item_id"],
                           "unit_id": historical_sale["lines"][0]["unit_id"], "quantity": "1"}],
            }, headers=headers)
            assert returned.status_code == 201, returned.text
            assert client.post(f"/api/sales/returns/{returned.json()['id']}/post",
                               headers=headers).status_code == 200
            replacement = client.post("/api/sales/shipments", json={
                "document_no": "HIST-REPL-1",
                "sales_order_id": historical_sale["sales_order_id"],
                "warehouse_id": historical_sale["warehouse_id"],
                "document_date": "2026-10-03", "shipment_type": "replacement",
                "lines": [{"sales_order_line_id": historical_sale["lines"][0]["sales_order_line_id"],
                           "item_id": historical_sale["lines"][0]["item_id"],
                           "unit_id": historical_sale["lines"][0]["unit_id"],
                           "quantity": "1", "replacement_return_line_id": returned.json()["lines"][0]["id"]}],
            }, headers=headers)
            assert replacement.status_code == 201, replacement.text
            assert client.post(f"/api/sales/shipments/{replacement.json()['id']}/post",
                               headers=headers).status_code == 200
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                raw = db.execute(text("""
                    SELECT id FROM warehouses WHERE organization_id = :org AND code = 'RAW'
                """), {"org": org}).scalar_one()
                raw_item = db.execute(text("""
                    SELECT id FROM items WHERE organization_id = :org AND code = 'RAW'
                """), {"org": org}).scalar_one()
                actor = db.execute(text("""
                    SELECT id FROM users WHERE organization_id = :org AND username = 'admin'
                """), {"org": org}).scalar_one()
                post_stock_changes(db, organization_id=org, actor_id=actor,
                    changes=[StockChange(raw, raw_item, Decimal("1"),
                                         "test_seed", uuid4(), uuid4(), "opening_in")])
                db.commit()
            historical_purchase = client.get(f"/api/purchase/receipts/{sources['purchase']}").json()
            purchase_return = client.post("/api/purchase/returns", json={
                "document_no": "HIST-PR-1", "original_receipt_id": str(sources["purchase"]),
                "warehouse_id": str(raw), "document_date": "2026-10-03",
                "lines": [{"purchase_receipt_line_id": historical_purchase["lines"][0]["id"],
                           "item_id": historical_purchase["lines"][0]["item_id"],
                           "unit_id": historical_purchase["lines"][0]["unit_id"], "quantity": "1"}],
            }, headers=headers)
            assert purchase_return.status_code == 201, purchase_return.text
            assert client.post(f"/api/purchase/returns/{purchase_return.json()['id']}/post",
                               headers=headers).status_code == 200
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                assert db.execute(text("""
                    SELECT COALESCE(sum(amount_delta), 0) FROM business_amount_entries
                    WHERE organization_id = :org
                """), {"org": org}).scalar_one() == Decimal("-3.00")
            replenishment = client.post("/api/purchase/receipts", json={
                "document_no": "HIST-RECV-1",
                "purchase_order_id": historical_purchase["purchase_order_id"],
                "warehouse_id": str(raw), "document_date": "2026-10-03",
                "lines": [{"purchase_order_line_id": historical_purchase["lines"][0]["purchase_order_line_id"],
                           "item_id": historical_purchase["lines"][0]["item_id"],
                           "unit_id": historical_purchase["lines"][0]["unit_id"], "quantity": "1"}],
            }, headers=headers)
            assert replenishment.status_code == 201, replenishment.text
            assert client.post(f"/api/purchase/receipts/{replenishment.json()['id']}/post",
                               headers=headers).status_code == 200
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                assert db.execute(text("""
                    SELECT COALESCE(sum(amount_delta), 0) FROM business_amount_entries
                    WHERE organization_id = :org
                """), {"org": org}).scalar_one() == Decimal("0.00")

            invalid_rows = [
                ("OLD-GOOD", "NEW-GOOD", "2026-10-01", "CUST", "产出", "FIN", "PCS", 2, 0, 2, 1, None, None),
                ("OLD-BAD", "NEW-BAD", "2026-10-01", "CUST", "产出", "MISSING", "PCS", 2, 0, 2, 1, None, None),
            ]
            invalid = client.post("/api/system/carryover/import/sales", files={
                "file": ("carryover.xlsx", workbook_bytes(invalid_rows))}, headers=headers)
            assert invalid.status_code == 422
            assert client.get("/api/system/carryover/documents",
                              params={"kind": "sales"}).json().__len__() == 1
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
