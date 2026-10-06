"""Integration test against the migrated PostgreSQL schema.

The outer transaction rolls back all test records, including bootstrap data.
"""

from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.inventory.posting import StockChange, post_stock_changes
from app.main import app


def test_login_and_warehouse_lifecycle() -> None:
    connection = get_engine().connect()
    outer_transaction = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    try:
        org_code = f"test_{uuid4().hex[:8]}"
        admin_username = f"admin_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            bootstrap(
                session,
                org_code=org_code,
                org_name="测试工厂",
                admin_username=admin_username,
                admin_password="TestOnlyPassword123!",
            )

        with TestClient(app, base_url="https://testserver") as client:
            assert client.get("/api/health").json()["database_revision"] == "0020_outsourcing_numbers"
            assert client.get("/api/warehouses").status_code == 401

            response = client.post(
                "/api/auth/login",
                json={"username": admin_username, "password": "TestOnlyPassword123!"},
            )
            assert response.status_code == 200, response.text
            csrf = response.json()["csrf_token"]
            assert len(client.get("/api/warehouses").json()) == 3

            payload = {"code": "EXTRA", "name": "备用仓"}
            assert client.post("/api/warehouses", json=payload).status_code == 403
            headers = {"X-CSRF-Token": csrf}
            created = client.post("/api/warehouses", json=payload, headers=headers)
            assert created.status_code == 201, created.text
            # 列表页的「详情」「编辑」按 id 取单条，缺这个接口会返回 405 而打不开弹窗。
            fetched = client.get(f"/api/warehouses/{created.json()['id']}")
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["code"] == "EXTRA"
            warehouse_id = created.json()["id"]
            assert client.post("/api/warehouses", json=payload, headers=headers).status_code == 409

            updated = client.put(
                f"/api/warehouses/{warehouse_id}",
                json={"code": "SPARE", "name": "备用仓库", "is_active": False},
                headers=headers,
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["is_active"] is False
            assert updated.json()["code"] == "SPARE"
            assert client.delete(f"/api/warehouses/{warehouse_id}", headers=headers).status_code == 204
            assert client.post("/api/auth/logout", headers=headers).status_code == 204
            assert client.get("/api/auth/me").status_code == 401

        assert connection.execute(text("SELECT count(*) FROM warehouses WHERE code = 'EXTRA'")).scalar_one() == 0
    finally:
        app.dependency_overrides.clear()
        outer_transaction.rollback()
        connection.close()


def test_stock_posting_is_atomic_and_nonnegative() -> None:
    connection = get_engine().connect()
    outer_transaction = connection.begin()
    try:
        org_code = f"stock_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(
                db,
                org_code=org_code,
                org_name="库存测试工厂",
                admin_username="admin",
                admin_password="TestOnlyPassword123!",
            )
            org_id = db.execute(
                text("SELECT id FROM organizations WHERE code = :code"), {"code": org_code}
            ).scalar_one()
            actor_id = db.execute(text("SELECT id FROM users WHERE organization_id = :org"), {"org": org_id}).scalar_one()
            warehouse_rows = db.execute(
                text("SELECT code, id FROM warehouses WHERE organization_id = :org"), {"org": org_id}
            ).all()
            warehouse_ids = dict(warehouse_rows)
            unit_id = db.execute(
                text("INSERT INTO units (organization_id, code, name) VALUES (:org, 'PCS', '件') RETURNING id"),
                {"org": org_id},
            ).scalar_one()
            item_id = db.execute(
                text("""
                    INSERT INTO items (organization_id, code, name, item_type, base_unit_id)
                    VALUES (:org, 'TEST_ITEM', '测试物料', 'raw_material', :unit) RETURNING id
                """),
                {"org": org_id, "unit": unit_id},
            ).scalar_one()
            db.commit()

        source_id = uuid4()
        line_id = uuid4()
        transfer_id = uuid4()
        transfer_line_id = uuid4()
        receipt = StockChange(
            warehouse_ids["RAW"], item_id, Decimal("10"),
            "test_opening", source_id, line_id, "in",
        )
        transfer = [
            StockChange(
                warehouse_ids["RAW"], item_id, Decimal("-4"),
                "test_transfer", transfer_id, transfer_line_id, "out",
            ),
            StockChange(
                warehouse_ids["SITE"], item_id, Decimal("4"),
                "test_transfer", transfer_id, transfer_line_id, "in",
            ),
        ]

        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            post_stock_changes(db, organization_id=org_id, actor_id=actor_id, changes=[receipt])
            post_stock_changes(db, organization_id=org_id, actor_id=actor_id, changes=transfer)
            db.commit()

        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            with pytest.raises(HTTPException) as error:
                post_stock_changes(
                    db, organization_id=org_id, actor_id=actor_id,
                    changes=[StockChange(
                        warehouse_ids["RAW"], item_id, Decimal("-7"),
                        "test_consumption", uuid4(), uuid4(), "out",
                    )],
                )
            assert error.value.status_code == 409
            db.rollback()

        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            with pytest.raises(IntegrityError):
                post_stock_changes(db, organization_id=org_id, actor_id=actor_id, changes=transfer)
            db.rollback()

        balances = dict(connection.execute(
            text("""
                SELECT warehouse_id, quantity_base FROM stock_balances
                WHERE organization_id = :org AND item_id = :item
            """),
            {"org": org_id, "item": item_id},
        ).all())
        assert balances[warehouse_ids["RAW"]] == Decimal("6")
        assert balances[warehouse_ids["SITE"]] == Decimal("4")
        assert connection.execute(
            text("SELECT count(*) FROM stock_movements WHERE organization_id = :org"), {"org": org_id}
        ).scalar_one() == 3
    finally:
        outer_transaction.rollback()
        connection.close()
