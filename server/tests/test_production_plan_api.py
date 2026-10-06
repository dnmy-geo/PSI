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


def test_multilevel_shortage_and_integer_splits() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"production_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=org_code, org_name="Production factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")
            org_id = db.execute(text("SELECT id FROM organizations WHERE code = :code"),
                                {"code": org_code}).scalar_one()
            actor_id = db.execute(text("SELECT id FROM users WHERE organization_id = :org"),
                                  {"org": org_id}).scalar_one()
            warehouse_id = db.execute(text("""
                SELECT id FROM warehouses WHERE organization_id = :org AND code = 'RAW'
            """), {"org": org_id}).scalar_one()
            site_id = db.execute(text("""
                SELECT id FROM warehouses WHERE organization_id = :org AND code = 'SITE'
            """), {"org": org_id}).scalar_one()
            finished_warehouse_id = db.execute(text("""
                SELECT id FROM warehouses WHERE organization_id = :org AND code = 'FINISHED'
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
            assert unit.status_code == 201, unit.text
            ids = {}
            for code, item_type in (("RAW", "raw_material"),
                                    ("SEMI", "semi_finished"), ("FIN", "finished")):
                item = client.post("/api/items", json={
                    "code": code, "name": code, "item_type": item_type,
                    "base_unit_id": unit.json()["id"],
                }, headers=headers)
                assert item.status_code == 201, item.text
                ids[code] = item.json()["id"]
            semi_bom = client.post("/api/boms", json={
                "parent_item_id": ids["SEMI"], "version": 1,
                "lines": [{"child_item_id": ids["RAW"], "quantity_base": "2"}],
            }, headers=headers)
            fin_bom = client.post("/api/boms", json={
                "parent_item_id": ids["FIN"], "version": 1,
                "lines": [{"child_item_id": ids["SEMI"], "quantity_base": "2"}],
            }, headers=headers)
            assert semi_bom.status_code == fin_bom.status_code == 201
            assert client.post(f"/api/boms/{semi_bom.json()['id']}/activate",
                               headers=headers).status_code == 200
            assert client.post(f"/api/boms/{fin_bom.json()['id']}/activate",
                               headers=headers).status_code == 200
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                post_stock_changes(db, organization_id=org_id, actor_id=actor_id,
                                   changes=[
                                       StockChange(warehouse_id, ids["SEMI"], Decimal("3"),
                                                   "test_seed", uuid4(), uuid4(), "opening_in"),
                                       StockChange(warehouse_id, ids["RAW"], Decimal("5"),
                                                   "test_seed", uuid4(), uuid4(), "opening_in"),
                                   ])
                db.commit()

            body = {"document_no": "PLAN-001", "document_date": "2026-10-01",
                    "lines": [{"item_id": ids["FIN"], "planned_quantity_base": 10}]}
            assert client.post("/api/production/plans", json={
                **body, "lines": [{"item_id": ids["FIN"],
                                    "planned_quantity_base": 10.0}],
            }, headers=headers).status_code == 422
            created = client.post("/api/production/plans", json=body, headers=headers)
            assert created.status_code == 201, created.text
            plan_id = created.json()["id"]
            shortage = client.get(f"/api/production/plans/{plan_id}/shortage")
            assert shortage.status_code == 200, shortage.text
            rows = {row["item_id"]: row for row in shortage.json()["lines"]}
            assert rows[ids["FIN"]]["item_code"] == "FIN"
            assert rows[ids["SEMI"]]["item_name"] == "SEMI"
            assert Decimal(rows[ids["FIN"]]["shortage_quantity_base"]) == 10
            assert Decimal(rows[ids["SEMI"]]["demand_quantity_base"]) == 20
            assert Decimal(rows[ids["SEMI"]]["shortage_quantity_base"]) == 17
            assert Decimal(rows[ids["RAW"]]["demand_quantity_base"]) == 34
            assert Decimal(rows[ids["RAW"]]["shortage_quantity_base"]) == 29
            assert client.get(f"/api/production/plans/{plan_id}/shortage").json() == shortage.json()
            assert client.get("/api/inventory/balances").status_code == 200

            body["lines"][0]["planned_quantity_base"] = 17
            updated = client.put(f"/api/production/plans/{plan_id}", json=body, headers=headers)
            assert updated.status_code == 200, updated.text
            plan_line_id = updated.json()["lines"][0]["id"]
            assert client.post(f"/api/production/plans/{plan_id}/open",
                               headers=headers).status_code == 200
            overview = client.get("/api/workbench/overview")
            assert overview.status_code == 200, overview.text
            assert overview.json()["open_production_plans"] == 1
            alerts = client.get("/api/workbench/alerts")
            assert alerts.status_code == 200, alerts.text
            assert any(alert["code"] == "production_shortage" and
                       alert["item_id"] == ids["RAW"] for alert in alerts.json())
            assert client.get("/api/workbench/tasks").status_code == 200
            assert client.put(f"/api/production/plans/{plan_id}", json=body,
                              headers=headers).status_code == 409
            split = client.post(f"/api/production/plans/{plan_id}/split/auto",
                                json={"order_count": 3}, headers=headers)
            assert split.status_code == 201, split.text
            orders = split.json()
            assert sorted(order["outputs"][0]["planned_quantity_base"] for order in orders) == [5, 6, 6]
            assert len({order["document_no"] for order in orders}) == 3
            assert client.get(f"/api/production/plans/{plan_id}").json()["lines"][0][
                "remaining_quantity_base"] == 0
            assert client.post(f"/api/production/plans/{plan_id}/split/auto",
                               json={"order_count": 1}, headers=headers).status_code == 422
            assert client.post(f"/api/production/plans/{plan_id}/close",
                               headers=headers).status_code == 200
            smallest = next(order for order in orders if order["outputs"][0]["planned_quantity_base"] == 5)
            assert client.post(f"/api/production/orders/{smallest['id']}/open",
                               headers=headers).status_code == 200
            assert client.delete(f"/api/production/orders/{smallest['id']}",
                                 headers=headers).status_code == 204
            reopened = client.get(f"/api/production/plans/{plan_id}").json()
            assert reopened["status"] == "open"
            assert reopened["lines"][0]["remaining_quantity_base"] == 5
            manual = client.post(f"/api/production/plans/{plan_id}/split/manual",
                                 json={"orders": [
                                     {"document_no": "MAN-001", "outputs": [{
                                         "production_plan_line_id": plan_line_id,
                                         "planned_quantity_base": 2,
                                     }]},
                                     {"document_no": "MAN-002", "outputs": [{
                                         "production_plan_line_id": plan_line_id,
                                         "planned_quantity_base": 3,
                                     }]},
                                 ]}, headers=headers)
            assert manual.status_code == 201, manual.text
            all_orders = client.get("/api/production/orders", params={
                "production_plan_id": plan_id,
            }).json()
            assert sum(output["planned_quantity_base"] for order in all_orders
                       for output in order["outputs"]) == 17
            assert client.get(f"/api/production/plans/{plan_id}/shortage").status_code == 200

            mixed_plan = client.post("/api/production/plans", json={
                "document_no": "PLAN-MIXED", "document_date": "2026-10-01",
                "lines": [{"item_id": ids["FIN"], "planned_quantity_base": 4},
                          {"item_id": ids["SEMI"], "planned_quantity_base": 3}],
            }, headers=headers)
            assert mixed_plan.status_code == 201, mixed_plan.text
            mixed_id = mixed_plan.json()["id"]
            mixed_shortage = client.get(f"/api/production/plans/{mixed_id}/shortage")
            assert mixed_shortage.status_code == 200, mixed_shortage.text
            mixed_rows = {row["item_id"]: row for row in mixed_shortage.json()["lines"]}
            assert Decimal(mixed_rows[ids["SEMI"]]["demand_quantity_base"]) == 11
            assert Decimal(mixed_rows[ids["SEMI"]]["shortage_quantity_base"]) == 8
            assert Decimal(mixed_rows[ids["RAW"]]["demand_quantity_base"]) == 16
            assert client.post(f"/api/production/plans/{mixed_id}/open",
                               headers=headers).status_code == 200
            mixed_orders = client.post(f"/api/production/plans/{mixed_id}/split/auto",
                                       json={"order_count": 2}, headers=headers)
            assert mixed_orders.status_code == 201, mixed_orders.text
            assert all({output["item_id"] for output in order["outputs"]}
                       == {ids["FIN"], ids["SEMI"]} for order in mixed_orders.json())

            # 订单编号留空（前端不传 document_no）：按「计划单号-P001」顺序生成。
            auto_plan = client.post("/api/production/plans", json={
                "document_no": "PLAN-AUTO", "document_date": "2026-10-01",
                "lines": [{"item_id": ids["FIN"], "planned_quantity_base": 2}],
            }, headers=headers)
            assert auto_plan.status_code == 201, auto_plan.text
            assert client.post(f"/api/production/plans/{auto_plan.json()['id']}/open",
                               headers=headers).status_code == 200
            auto_numbered = client.post(f"/api/production/plans/{auto_plan.json()['id']}/split/manual",
                                        json={"orders": [{"outputs": [{
                                            "production_plan_line_id": auto_plan.json()["lines"][0]["id"],
                                            "planned_quantity_base": 1,
                                        }]}]}, headers=headers)
            assert auto_numbered.status_code == 201, auto_numbered.text
            auto_no = auto_numbered.json()[0]["document_no"]
            assert auto_no == "PLAN-AUTO-P001", auto_no

            work_order = mixed_orders.json()[0]
            work_order_id = work_order["id"]
            assert client.post(f"/api/production/orders/{work_order_id}/open",
                               headers=headers).status_code == 200
            issue_body = {
                "document_no": "ISSUE-001", "production_order_id": work_order_id,
                "source_warehouse_id": str(warehouse_id),
                "target_warehouse_id": str(site_id), "document_date": "2026-10-02",
                "lines": [{"item_id": ids["RAW"], "unit_id": unit.json()["id"],
                           "quantity": "3", "bom_quantity_base": "2",
                           "loss_quantity_base": "1"}],
            }
            assert client.post("/api/production/issues", json={
                **issue_body, "lines": [dict(issue_body["lines"][0],
                                             bom_quantity_base="3")],
            }, headers=headers).status_code == 422
            issue = client.post("/api/production/issues", json=issue_body, headers=headers)
            assert issue.status_code == 201, issue.text
            issue_id = issue.json()["id"]
            assert client.post(f"/api/production/issues/{issue_id}/post",
                               headers=headers).status_code == 200
            assert client.post(f"/api/production/issues/{issue_id}/post",
                               headers=headers).status_code == 200
            balances = {row["warehouse_id"]: Decimal(row["quantity_base"])
                        for row in client.get("/api/inventory/balances", params={
                            "item_id": ids["RAW"],
                        }).json() if row["item_id"] == ids["RAW"]}
            assert balances[str(warehouse_id)] == 2
            assert balances[str(site_id)] == 3

            consumption_body = {
                "document_no": "CONSUME-001", "production_order_id": work_order_id,
                "warehouse_id": str(site_id), "document_date": "2026-10-02",
                "lines": [{"item_id": ids["RAW"], "unit_id": unit.json()["id"],
                           "quantity": "4"}],
            }
            consumption = client.post("/api/production/consumptions",
                                      json=consumption_body, headers=headers)
            assert consumption.status_code == 201, consumption.text
            consumption_id = consumption.json()["id"]
            assert client.post(f"/api/production/consumptions/{consumption_id}/post",
                               headers=headers).status_code == 409
            consumption_body["lines"][0]["quantity"] = "2"
            assert client.put(f"/api/production/consumptions/{consumption_id}",
                              json=consumption_body, headers=headers).status_code == 200
            assert client.post(f"/api/production/consumptions/{consumption_id}/post",
                               headers=headers).status_code == 200
            assert client.post(f"/api/production/consumptions/{consumption_id}/post",
                               headers=headers).status_code == 200

            receipt_body = {
                "document_no": "MAKE-001", "production_order_id": work_order_id,
                "document_date": "2026-10-03",
                "lines": [{"production_order_output_id": output["id"],
                           "item_id": output["item_id"],
                           "target_warehouse_id": str(finished_warehouse_id),
                           "quantity_base": output["planned_quantity_base"]}
                          for output in work_order["outputs"]],
            }
            receipt = client.post("/api/production/receipts", json=receipt_body,
                                  headers=headers)
            assert receipt.status_code == 201, receipt.text
            receipt_id = receipt.json()["id"]
            assert client.post("/api/production/receipts", json={
                **receipt_body, "document_no": "MAKE-002",
            }, headers=headers).status_code == 409
            assert client.post(f"/api/production/receipts/{receipt_id}/post",
                               headers=headers).status_code == 200
            assert client.post(f"/api/production/receipts/{receipt_id}/post",
                               headers=headers).status_code == 200
            assert client.get(f"/api/production/orders/{work_order_id}").json()[
                "status"] == "completed"
            assert client.delete(f"/api/production/orders/{work_order_id}",
                                 headers=headers).status_code == 409
            assert client.post("/api/production/issues", json={
                **issue_body, "document_no": "ISSUE-LATE",
            }, headers=headers).status_code == 409
            assert connection.execute(text("""
                SELECT count(*) FROM stock_movements WHERE organization_id = :org
                  AND source_type = 'production_receipt'
            """), {"org": org_id}).scalar_one() == len(work_order["outputs"])

            cancelled_order = mixed_orders.json()[1]
            cancelled_id = cancelled_order["id"]
            assert client.post(f"/api/production/orders/{cancelled_id}/open",
                               headers=headers).status_code == 200
            cancel_issue = client.post("/api/production/issues", json={
                **issue_body, "document_no": "ISSUE-CANCEL",
                "production_order_id": cancelled_id,
                "lines": [dict(issue_body["lines"][0], quantity="1",
                               bom_quantity_base="1", loss_quantity_base="0")],
            }, headers=headers)
            assert cancel_issue.status_code == 201, cancel_issue.text
            cancel_issue_id = cancel_issue.json()["id"]
            assert client.post(f"/api/production/issues/{cancel_issue_id}/post",
                               headers=headers).status_code == 200
            assert client.delete(f"/api/production/orders/{cancelled_id}",
                                 headers=headers).status_code == 409
            reversed_issue = client.post(
                f"/api/production/issues/{cancel_issue_id}/reverse",
                json={"reason": "重新拆单"}, headers=headers)
            assert reversed_issue.status_code == 200, reversed_issue.text
            assert reversed_issue.json()["status"] == "reversed"
            assert client.post(f"/api/production/issues/{cancel_issue_id}/reverse",
                               json={"reason": "重试"}, headers=headers).status_code == 200
            assert client.delete(f"/api/production/orders/{cancelled_id}",
                                 headers=headers).status_code == 204
            assert client.get(f"/api/production/orders/{cancelled_id}").json()[
                "status"] == "cancelled"
            assert connection.execute(text("""
                SELECT count(*) FROM stock_movements
                WHERE organization_id = :org AND source_type = 'production_issue_reversal'
                  AND reversal_of_id IS NOT NULL
            """), {"org": org_id}).scalar_one() == 2
            remaining = client.get(f"/api/production/plans/{mixed_id}").json()
            assert sum(line["remaining_quantity_base"] for line in remaining["lines"]) == 3
            resplit = client.post(f"/api/production/plans/{mixed_id}/split/auto",
                                  json={"order_count": 1}, headers=headers)
            assert resplit.status_code == 201, resplit.text
            assert client.post(f"/api/production/consumptions/{consumption_id}/reverse",
                               json={"reason": "重做订单"}, headers=headers).status_code == 409
            reversed_receipt = client.post(
                f"/api/production/receipts/{receipt_id}/reverse",
                json={"reason": "重做订单"}, headers=headers)
            assert reversed_receipt.status_code == 200, reversed_receipt.text
            assert reversed_receipt.json()["status"] == "reversed"
            assert client.get(f"/api/production/orders/{work_order_id}").json()[
                "status"] == "open"
            assert client.post(f"/api/production/receipts/{receipt_id}/reverse",
                               json={"reason": "重试"}, headers=headers).status_code == 200
            assert client.post(f"/api/production/issues/{issue_id}/reverse",
                               json={"reason": "重做订单"}, headers=headers).status_code == 409
            reversed_consumption = client.post(
                f"/api/production/consumptions/{consumption_id}/reverse",
                json={"reason": "重做订单"}, headers=headers)
            assert reversed_consumption.status_code == 200, reversed_consumption.text
            assert reversed_consumption.json()["status"] == "reversed"
            assert client.post(f"/api/production/issues/{issue_id}/reverse",
                               json={"reason": "重做订单"}, headers=headers).status_code == 200
            assert client.delete(f"/api/production/orders/{work_order_id}",
                                 headers=headers).status_code == 204
            assert client.get(f"/api/production/orders/{work_order_id}").json()[
                "status"] == "cancelled"
            assert connection.execute(text("""
                SELECT count(*) FROM stock_movements
                WHERE organization_id = :org
                  AND source_type IN ('production_consumption_reversal',
                                      'production_receipt_reversal')
                  AND reversal_of_id IS NOT NULL
            """), {"org": org_id}).scalar_one() == 1 + len(work_order["outputs"])
            report = client.get("/api/reports/production", params={
                "date_from": "2020-01-01", "date_to": "2100-12-31",
            })
            assert report.status_code == 200, report.text
            rows = {row["item_id"]: row for row in report.json()}
            assert Decimal(rows[ids["RAW"]]["quantities"]["consumed_base"]) == 0
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
