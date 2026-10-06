from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap
from app.core.db import get_db, get_engine
from app.main import app


def test_supplier_processor_accounts_cash_and_month_end() -> None:
    connection = get_engine().connect()
    outer = connection.begin()

    def test_db() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        code = f"reconcile_{uuid4().hex[:8]}"
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            bootstrap(db, org_code=code, org_name="Reconciliation factory",
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
            party = client.post("/api/parties", json={
                "code": "BOTH", "name": "Supplier and processor",
                "types": ["supplier", "processor"],
            }, headers=headers)
            assert party.status_code == 201, party.text
            party_id = party.json()["id"]
            for account, amount in (("supplier", "100"), ("processor", "50")):
                opening = client.post("/api/reconciliation/opening-balances", json={
                    "party_id": party_id, "account_type": account,
                    "effective_date": "2026-10-01", "amount": amount,
                }, headers=headers)
                assert opening.status_code == 201, opening.text
            assert len(client.get("/api/reconciliation/opening-balances").json()) == 2
            for account, amount in (("supplier", "20"), ("processor", "5")):
                payment = client.post("/api/reconciliation/cash-records", json={
                    "document_no": f"PAY-{account}", "party_id": party_id,
                    "account_type": account, "record_type": "payment",
                    "document_date": "2026-10-15", "amount": amount,
                }, headers=headers)
                assert payment.status_code == 201, payment.text
            assert client.post("/api/reconciliation/cash-records", json={
                "document_no": "BAD-RECEIPT", "party_id": party_id,
                "account_type": "supplier", "record_type": "receipt",
                "document_date": "2026-10-15", "amount": "1",
            }, headers=headers).status_code == 422
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                for source_type, amount in (("purchase_receipt", "30"),
                                            ("purchase_return", "-10"),
                                            ("outsourcing_receipt", "15")):
                    db.execute(text("""
                        INSERT INTO business_amount_entries (
                            organization_id, party_id, direction, amount_delta,
                            source_type, source_id, source_line_id, posted_at
                        ) VALUES (:org, :party, 'payable', :amount,
                                  :source, :source_id, :line_id, :posted_at)
                    """), {"org": org, "party": party_id,
                           "amount": Decimal(amount), "source": source_type,
                           "source_id": uuid4(), "line_id": uuid4(),
                           "posted_at": datetime(2026, 10, 20, 12, 0,
                                                 tzinfo=ZoneInfo("Asia/Shanghai"))})
                db.commit()
            supplier = client.get("/api/reconciliation/month-end", params={
                "month": "2026-10", "account_type": "supplier",
            })
            processor = client.get("/api/reconciliation/month-end", params={
                "month": "2026-10", "account_type": "processor",
            })
            assert supplier.status_code == processor.status_code == 200
            s, p = supplier.json()[0], processor.json()[0]
            assert Decimal(s["opening_balance"]) == 100
            assert Decimal(s["business_amount"]) == 20
            assert Decimal(s["cash_amount"]) == 20
            assert Decimal(s["closing_balance"]) == 100
            assert Decimal(p["opening_balance"]) == 50
            assert Decimal(p["business_amount"]) == 15
            assert Decimal(p["cash_amount"]) == 5
            assert Decimal(p["closing_balance"]) == 60
            detail = client.get(f"/api/reconciliation/supplier/parties/{party_id}/statement",
                                params={"month": "2026-10"})
            assert detail.status_code == 200, detail.text
            assert len(detail.json()["business_lines"]) == 2
            assert len(detail.json()["cash_lines"]) == 1
            november = client.get("/api/reconciliation/month-end", params={
                "month": "2026-11", "account_type": "processor",
            })
            assert Decimal(november.json()[0]["opening_balance"]) == 60
            assert Decimal(november.json()[0]["closing_balance"]) == 60
            assert client.get("/api/reconciliation/month-end", params={
                "month": "2026-13", "account_type": "supplier",
            }).status_code == 422
            customer = client.post("/api/parties", json={
                "code": "OPEN-CUST", "name": "Opening customer", "types": ["customer"],
            }, headers=headers)
            assert customer.status_code == 201, customer.text
            template = client.get("/api/reconciliation/opening-balances/template")
            assert template.status_code == 200
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(("往来单位编码", "账户类型", "启用日期", "期初金额"))
            sheet.append(("OPEN-CUST", "客户", "2026-10-01", 120))
            output = BytesIO()
            workbook.save(output)
            content = output.getvalue()
            files = {"file": ("opening.xlsx", content,
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            preview = client.post("/api/reconciliation/opening-balances/preview",
                                  files=files, headers=headers)
            assert preview.status_code == 200, preview.text
            assert preview.json()[0]["amount"] == "120"
            imported = client.post("/api/reconciliation/opening-balances/import",
                                   files=files, headers=headers)
            assert imported.status_code == 200, imported.text
            assert imported.json()["imported"] == 1
            assert client.post("/api/reconciliation/opening-balances/import",
                               files=files, headers=headers).status_code == 409
            customer_month = client.get("/api/reconciliation/month-end", params={
                "month": "2026-10", "account_type": "customer",
            })
            assert Decimal(customer_month.json()[0]["opening_balance"]) == 120
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()
