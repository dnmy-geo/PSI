from collections.abc import Iterator
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def make_xlsx(rows: list[tuple]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(("仓库编码", "物料编码", "单位编码", "数量"))
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_opening_stock_import_preview_and_post() -> None:
    connection = get_engine().connect()
    outer_transaction = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"opening_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(
                db, org_code=org_code, org_name="期初库存测试工厂",
                admin_username="admin", admin_password="TestOnlyPassword123!",
            )

        with TestClient(app, base_url="https://testserver") as client:
            login = client.post(
                "/api/auth/login",
                json={"organization_code": org_code, "username": "admin", "password": "TestOnlyPassword123!"},
            )
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}
            unit = client.post(
                "/api/units", json={"code": "PCS", "name": "件", "precision_scale": 0}, headers=headers
            )
            assert unit.status_code == 201, unit.text
            item = client.post(
                "/api/items",
                json={
                    "code": "PART_B", "name": "部件B", "item_type": "raw_material",
                    "base_unit_id": unit.json()["id"],
                },
                headers=headers,
            )
            assert item.status_code == 201, item.text
            assert client.get("/api/inventory/opening-stock/template").status_code == 200

            content = make_xlsx([("RAW", "PART_B", "PCS", 12)])
            import_args = {
                "data": {"effective_date": "2026-10-01"},
                "files": {"file": ("opening.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                "headers": headers,
            }
            preview = client.post("/api/inventory/opening-stock/preview",
                                  files=import_args["files"], headers=headers)
            assert preview.status_code == 200, preview.text
            assert preview.json()[0]["warehouse_code"] == "RAW"
            assert preview.json()[0]["quantity_base"] == "12"
            assert client.get("/api/inventory/opening-stock").json() == []
            draft = client.post("/api/inventory/opening-stock/import", **import_args)
            assert draft.status_code == 201, draft.text
            assert draft.json()["status"] == "draft"
            assert draft.json()["lines"][0]["quantity_base"] == "12.000000"
            assert client.get("/api/inventory/balances").json() == []

            document_id = draft.json()["id"]
            posted = client.post(f"/api/inventory/opening-stock/{document_id}/post", headers=headers)
            assert posted.status_code == 200, posted.text
            assert posted.json()["status"] == "posted"
            listed = client.get("/api/inventory/opening-stock", params={"status": "posted"})
            assert listed.status_code == 200, listed.text
            assert [doc["id"] for doc in listed.json()] == [document_id]
            assert client.post(f"/api/inventory/opening-stock/{document_id}/post", headers=headers).status_code == 200
            assert client.get("/api/inventory/balances").json()[0]["quantity_base"] == "12.000000"

            duplicate = client.post("/api/inventory/opening-stock/import", **import_args)
            assert duplicate.status_code == 201, duplicate.text
            assert client.post(
                f"/api/inventory/opening-stock/{duplicate.json()['id']}/post", headers=headers
            ).status_code == 409
            invalid = client.post(
                "/api/inventory/opening-stock/import",
                data={"effective_date": "2026-10-01"},
                files={"file": ("opening.xlsx", b"not excel", "application/octet-stream")},
                headers=headers,
            )
            assert invalid.status_code == 422
            reversed_doc = client.post(
                f"/api/inventory/opening-stock/{document_id}/reverse",
                json={"reason": "期初数量重核"}, headers=headers)
            assert reversed_doc.status_code == 200, reversed_doc.text
            assert reversed_doc.json()["status"] == "reversed"
            assert client.get("/api/inventory/balances").json()[0][
                "quantity_base"] == "0.000000"
            assert client.post(f"/api/inventory/opening-stock/{document_id}/reverse",
                               json={"reason": "重试"}, headers=headers).status_code == 200

        org_id = connection.execute(
            text("SELECT id FROM organizations WHERE code = :code"), {"code": org_code}
        ).scalar_one()
        assert connection.execute(
            text("SELECT count(*) FROM stock_movements WHERE organization_id = :id"), {"id": org_id}
        ).scalar_one() == 2
    finally:
        app.dependency_overrides.clear()
        outer_transaction.rollback()
        connection.close()
