from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def test_bom_versions_activation_and_cycle() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"bom_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=org_code, org_name="BOM test factory",
                      admin_username="admin", admin_password="TestOnlyPassword123!")

        with TestClient(app, base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json={
                "organization_code": org_code, "username": "admin", "password": "TestOnlyPassword123!",
            })
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}

            unit = client.post("/api/units", json={
                "code": "PCS", "name": "pieces", "precision_scale": 0,
            }, headers=headers)
            assert unit.status_code == 201, unit.text
            items = {}
            for code, item_type in (("RAW", "raw_material"),
                                    ("SEMI", "semi_finished"), ("FIN", "finished")):
                response = client.post("/api/items", json={
                    "code": code, "name": code, "item_type": item_type,
                    "base_unit_id": unit.json()["id"],
                }, headers=headers)
                assert response.status_code == 201, response.text
                items[code] = response.json()["id"]

            def create(parent: str, version: int, child: str, quantity: str):
                return client.post("/api/boms", json={
                    "parent_item_id": items[parent], "version": version,
                    "lines": [{"child_item_id": items[child], "quantity_base": quantity}],
                }, headers=headers)

            semi = create("SEMI", 1, "RAW", "2")
            assert semi.status_code == 201, semi.text
            assert client.post(f"/api/boms/{semi.json()['id']}/activate", headers=headers).status_code == 200
            fin = create("FIN", 1, "SEMI", "2")
            assert fin.status_code == 201, fin.text
            assert client.post(f"/api/boms/{fin.json()['id']}/activate", headers=headers).status_code == 200

            # 列表按 BOM 头分页，每行带多级展开的用料树：FIN -> SEMI -> RAW
            listing = client.get("/api/boms?limit=10&offset=0")
            assert listing.status_code == 200, listing.text
            assert listing.headers["X-Total-Count"] == str(len(listing.json()))
            fin_row = next(row for row in listing.json()
                           if row["parent_item_id"] == items["FIN"] and row["is_active"])
            assert fin_row["row_kind"] == "bom" and fin_row["item_id"] == items["FIN"]
            semi_node = fin_row["children"][0]
            assert semi_node["item_id"] == items["SEMI"] and Decimal(semi_node["quantity_base"]) == Decimal("2")
            assert semi_node["children"][0]["item_id"] == items["RAW"]

            # 分页只截断 BOM 头，总数不受影响
            first_page = client.get("/api/boms?limit=1&offset=0")
            assert len(first_page.json()) == 1
            assert first_page.headers["X-Total-Count"] == listing.headers["X-Total-Count"]

            cyclic = create("SEMI", 2, "FIN", "1")
            assert cyclic.status_code == 201, cyclic.text
            rejected = client.post(f"/api/boms/{cyclic.json()['id']}/activate", headers=headers)
            assert rejected.status_code == 422, rejected.text
            assert client.get(f"/api/boms/{semi.json()['id']}").json()["is_active"] is True

            replacement = create("FIN", 2, "RAW", "3")
            assert replacement.status_code == 201, replacement.text
            activated = client.post(f"/api/boms/{replacement.json()['id']}/activate", headers=headers)
            assert activated.status_code == 200, activated.text
            assert activated.json()["is_active"] is True
            assert client.get(f"/api/boms/{fin.json()['id']}").json()["is_active"] is False
            assert client.delete(f"/api/boms/{replacement.json()['id']}", headers=headers).status_code == 409
            assert client.delete(f"/api/boms/{cyclic.json()['id']}", headers=headers).status_code == 204
            assert len(client.get(f"/api/boms?parent_item_id={items['FIN']}").json()) == 2
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
