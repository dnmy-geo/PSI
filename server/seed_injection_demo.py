"""Seed an existing local PSI organization with injection molding demo data.

Run from server/: .venv/Scripts/python.exe seed_injection_demo.py --org-code FACTORY
The DEMO-prefixed records are inserted once; existing records are not overwritten.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.inventory.posting import StockChange, post_stock_changes


def existing_or_insert(db: Session, table: str, org_id, key: str, values: dict):
    """The table names below are fixed by this script, never supplied by a caller."""
    columns = ["organization_id", *values]
    parameters = {"organization_id": org_id, **values}
    db.execute(text(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + name for name in columns)}) "
        f"ON CONFLICT (organization_id, {key}) DO NOTHING"
    ), parameters)
    return db.execute(text(f"SELECT id FROM {table} WHERE organization_id = :org AND {key} = :value"),
                      {"org": org_id, "value": values[key]}).scalar_one()


def document(db: Session, table: str, org_id, user_id, number: str, when: date, **fields):
    columns = ["organization_id", "document_no", "document_date", "created_by", *fields]
    values = {"organization_id": org_id, "document_no": number, "document_date": when,
              "created_by": user_id, **fields}
    inserted = db.execute(text(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + name for name in columns)}) "
        "ON CONFLICT (organization_id, document_no) DO NOTHING RETURNING id"
    ), values).scalar_one_or_none()
    record_id = inserted or db.execute(text(
        f"SELECT id FROM {table} WHERE organization_id = :org AND document_no = :number"
    ), {"org": org_id, "number": number}).scalar_one()
    return record_id, inserted is not None


def seed(db: Session, org_code: str) -> dict[str, int]:
    org = db.execute(text("SELECT id FROM organizations WHERE code = :code"), {"code": org_code}).scalar_one_or_none()
    if org is None:
        raise RuntimeError(f"Organization {org_code!r} does not exist; run bootstrap first")
    user = db.execute(text("""
        SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id
        JOIN roles r ON r.id = ur.role_id
        WHERE u.organization_id = :org AND r.code = 'system_admin' AND u.is_active
        ORDER BY u.username LIMIT 1
    """), {"org": org}).scalar_one()
    warehouses = dict(db.execute(text("SELECT code, id FROM warehouses WHERE organization_id = :org"),
                                 {"org": org}).all())
    for code in ("RAW", "FINISHED", "SITE"):
        if code not in warehouses:
            raise RuntimeError(f"Required warehouse {code} is missing")

    counts = {name: 0 for name in ("units", "categories", "items", "parties", "boms", "opening_stock",
                                  "sales_orders", "purchase_orders", "production_plans", "production_orders",
                                  "outsourcing_orders", "departments")}
    for code, name in (("DEMO-INJECTION", "注塑车间"), ("DEMO-QUALITY", "品质部"),
                       ("DEMO-PURCHASE", "采购部"), ("DEMO-WAREHOUSE", "仓储部")):
        before = db.execute(text("SELECT 1 FROM departments WHERE organization_id = :org AND code = :code"),
                            {"org": org, "code": code}).scalar_one_or_none()
        existing_or_insert(db, "departments", org, "code", {"code": code, "name": name})
        counts["departments"] += before is None

    units = {}
    for code, name, precision in (("KG", "千克", 3), ("PCS", "件", 0), ("BAG", "袋", 0)):
        before = db.execute(text("SELECT 1 FROM units WHERE organization_id = :org AND code = :code"),
                            {"org": org, "code": code}).scalar_one_or_none()
        units[code] = existing_or_insert(db, "units", org, "code", {"code": code, "name": name,
                                                                        "precision_scale": precision})
        counts["units"] += before is None

    categories = {}
    for code, name in (("DEMO-RESIN", "塑胶原料"), ("DEMO-ADDITIVE", "色母与辅料"),
                       ("DEMO-INSERT", "五金嵌件"), ("DEMO-PACK", "包装材料"),
                       ("DEMO-SEMI", "注塑半成品"), ("DEMO-FINISHED", "注塑成品")):
        before = db.execute(text("SELECT 1 FROM item_categories WHERE organization_id = :org AND code = :code"),
                            {"org": org, "code": code}).scalar_one_or_none()
        categories[code] = existing_or_insert(db, "item_categories", org, "code", {"code": code, "name": name})
        counts["categories"] += before is None

    item_specs = [
        ("DEMO-RM-PP", "PP 高流动注塑料", "raw_material", "KG", "DEMO-RESIN"),
        ("DEMO-RM-ABS", "ABS 757 树脂", "raw_material", "KG", "DEMO-RESIN"),
        ("DEMO-RM-TPE", "TPE 软胶料", "raw_material", "KG", "DEMO-RESIN"),
        ("DEMO-AUX-BLACK", "黑色色母粒", "raw_material", "KG", "DEMO-ADDITIVE"),
        ("DEMO-AUX-WHITE", "白色色母粒", "raw_material", "KG", "DEMO-ADDITIVE"),
        ("DEMO-INS-M4", "M4 铜螺母嵌件", "raw_material", "PCS", "DEMO-INSERT"),
        ("DEMO-PKG-BAG", "防静电包装袋", "raw_material", "BAG", "DEMO-PACK"),
        ("DEMO-SF-SHELL", "设备外壳注塑半成品", "semi_finished", "PCS", "DEMO-SEMI"),
        ("DEMO-FG-BLACK", "智能设备外壳·黑", "finished", "PCS", "DEMO-FINISHED"),
        ("DEMO-FG-WHITE", "智能设备外壳·白", "finished", "PCS", "DEMO-FINISHED"),
        ("DEMO-FG-CONTROL", "控制盒壳体", "finished", "PCS", "DEMO-FINISHED"),
    ]
    items = {}
    for code, name, kind, unit, category in item_specs:
        before = db.execute(text("SELECT 1 FROM items WHERE organization_id = :org AND code = :code"),
                            {"org": org, "code": code}).scalar_one_or_none()
        items[code] = existing_or_insert(db, "items", org, "code", {"code": code, "name": name,
            "item_type": kind, "base_unit_id": units[unit], "category_id": categories[category]})
        counts["items"] += before is None

    party_specs = [
        ("DEMO-CUST-A", "苏州智联电子有限公司", "customer", "陈经理", "13800001001"),
        ("DEMO-CUST-B", "南京精工设备有限公司", "customer", "王主管", "13800001002"),
        ("DEMO-SUP-RESIN", "昆山新材塑胶有限公司", "supplier", "李经理", "13800001003"),
        ("DEMO-SUP-HARD", "东莞精密五金有限公司", "supplier", "周经理", "13800001004"),
        ("DEMO-PROC-COAT", "无锡华彩喷涂有限公司", "processor", "吴经理", "13800001005"),
    ]
    parties = {}
    for code, name, kind, contact, phone in party_specs:
        before = db.execute(text("SELECT 1 FROM parties WHERE organization_id = :org AND code = :code"),
                            {"org": org, "code": code}).scalar_one_or_none()
        party_id = existing_or_insert(db, "parties", org, "code", {"code": code, "name": name,
            "contact_name": contact, "contact_phone": phone})
        parties[code] = party_id
        db.execute(text("INSERT INTO party_types (party_id, party_type) VALUES (:id, :kind) ON CONFLICT DO NOTHING"),
                   {"id": party_id, "kind": kind})
        counts["parties"] += before is None

    bom_specs = [
        ("DEMO-SF-SHELL", [("DEMO-RM-PP", "0.180"), ("DEMO-AUX-BLACK", "0.004")]),
        ("DEMO-FG-BLACK", [("DEMO-SF-SHELL", "1"), ("DEMO-INS-M4", "4"), ("DEMO-PKG-BAG", "1")]),
        ("DEMO-FG-WHITE", [("DEMO-RM-ABS", "0.220"), ("DEMO-AUX-WHITE", "0.005"),
                           ("DEMO-INS-M4", "4"), ("DEMO-PKG-BAG", "1")]),
        ("DEMO-FG-CONTROL", [("DEMO-RM-PP", "0.300"), ("DEMO-AUX-BLACK", "0.006"),
                             ("DEMO-INS-M4", "6"), ("DEMO-PKG-BAG", "1")]),
    ]
    for parent, lines in bom_specs:
        bom = db.execute(text("""
            SELECT id FROM bom_headers WHERE organization_id = :org AND parent_item_id = :item AND version = 1
        """), {"org": org, "item": items[parent]}).scalar_one_or_none()
        if bom is None:
            bom = db.execute(text("""
                INSERT INTO bom_headers (organization_id, parent_item_id, version, is_active)
                VALUES (:org, :item, 1, true) RETURNING id
            """), {"org": org, "item": items[parent]}).scalar_one()
            for index, (child, quantity) in enumerate(lines, start=1):
                db.execute(text("""
                    INSERT INTO bom_lines (bom_id, child_item_id, quantity_base, sort_order)
                    VALUES (:bom, :child, :quantity, :sort_order)
                """), {"bom": bom, "child": items[child], "quantity": Decimal(quantity), "sort_order": index})
            counts["boms"] += 1

    today = date.today()
    opening_number = "DEMO-OPEN-001"
    opening = db.execute(text("SELECT id, status FROM opening_stock_docs WHERE organization_id = :org AND document_no = :number"),
                         {"org": org, "number": opening_number}).mappings().first()
    if opening is not None and opening["status"] != "posted":
        raise RuntimeError("Existing demo opening stock document is not posted")
    if opening is None:
        stock_specs = [
            ("RAW", "DEMO-RM-PP", "1250"), ("RAW", "DEMO-RM-ABS", "780"),
            ("RAW", "DEMO-RM-TPE", "240"), ("RAW", "DEMO-AUX-BLACK", "65"),
            ("RAW", "DEMO-AUX-WHITE", "48"), ("RAW", "DEMO-INS-M4", "4500"),
            ("RAW", "DEMO-PKG-BAG", "1800"), ("SITE", "DEMO-SF-SHELL", "220"),
            ("FINISHED", "DEMO-FG-BLACK", "160"), ("FINISHED", "DEMO-FG-WHITE", "95"),
            ("FINISHED", "DEMO-FG-CONTROL", "75"),
        ]
        for warehouse, item, _ in stock_specs:
            if db.execute(text("""
                SELECT 1 FROM stock_movements WHERE organization_id = :org
                AND warehouse_id = :warehouse AND item_id = :item LIMIT 1
            """), {"org": org, "warehouse": warehouses[warehouse], "item": items[item]}).scalar_one_or_none():
                raise RuntimeError(f"Cannot post demo opening stock: {warehouse}/{item} already has movements")
        opening_id = db.execute(text("""
            INSERT INTO opening_stock_docs (organization_id, document_no, effective_date, import_batch_no,
                                            status, remark, created_by, posted_at)
            VALUES (:org, :number, :effective_date, '注塑厂演示数据', 'posted', '模拟期初库存', :user, now())
            RETURNING id
        """), {"org": org, "number": opening_number, "effective_date": today - timedelta(days=45),
               "user": user}).scalar_one()
        changes = []
        unit_by_item = {code: units[unit] for code, _, _, unit, _ in item_specs}
        for warehouse, item, quantity in stock_specs:
            amount = Decimal(quantity)
            line_id = db.execute(text("""
                INSERT INTO opening_stock_lines (opening_doc_id, warehouse_id, item_id, quantity,
                                                 unit_id, conversion_factor, quantity_base)
                VALUES (:doc, :warehouse, :item, :quantity, :unit, 1, :quantity) RETURNING id
            """), {"doc": opening_id, "warehouse": warehouses[warehouse], "item": items[item],
                   "quantity": amount, "unit": unit_by_item[item]}).scalar_one()
            changes.append(StockChange(warehouses[warehouse], items[item], amount,
                                       "opening_stock", opening_id, line_id, "in"))
        post_stock_changes(db, organization_id=org, actor_id=user, changes=changes)
        counts["opening_stock"] = len(stock_specs)

    sales_specs = [
        ("DEMO-SO-001", "DEMO-CUST-A", 14, 12, [("DEMO-FG-BLACK", "300", "12.80"),
                                                  ("DEMO-FG-WHITE", "100", "14.50")]),
        ("DEMO-SO-002", "DEMO-CUST-B", 10, 18, [("DEMO-FG-BLACK", "500", "12.30")]),
        ("DEMO-SO-003", "DEMO-CUST-A", 4, 24, [("DEMO-FG-CONTROL", "220", "18.60")]),
    ]
    for number, customer, age, lead, lines in sales_specs:
        order_id, created = document(db, "sales_orders", org, user, number, today - timedelta(days=age),
            customer_id=parties[customer], delivery_date=today + timedelta(days=lead), remark="注塑厂演示订单")
        if created:
            for item, quantity, price in lines:
                amount = Decimal(quantity) * Decimal(price)
                db.execute(text("""
                    INSERT INTO sales_order_lines (sales_order_id, item_id, quantity, unit_id,
                        conversion_factor, quantity_base, unit_price, amount)
                    VALUES (:order, :item, :quantity, :unit, 1, :quantity, :price, :amount)
                """), {"order": order_id, "item": items[item], "quantity": Decimal(quantity),
                       "unit": units["PCS"], "price": Decimal(price), "amount": amount})
            counts["sales_orders"] += 1

    purchase_specs = [
        ("DEMO-PO-001", "DEMO-SUP-RESIN", 12, "open", [("DEMO-RM-PP", "800", "8.60"),
                                                        ("DEMO-AUX-BLACK", "30", "34.00")]),
        ("DEMO-PO-002", "DEMO-SUP-RESIN", 6, "open", [("DEMO-RM-ABS", "500", "13.20"),
                                                       ("DEMO-AUX-WHITE", "20", "38.00")]),
        ("DEMO-PO-003", "DEMO-SUP-HARD", 2, "draft", [("DEMO-INS-M4", "3000", "0.15"),
                                                       ("DEMO-PKG-BAG", "1000", "0.20")]),
    ]
    for number, supplier, age, status, lines in purchase_specs:
        order_id, created = document(db, "purchase_orders", org, user, number, today - timedelta(days=age),
            supplier_id=parties[supplier], status=status, remark="注塑生产备料")
        if created:
            for item, quantity, price in lines:
                unit = units["KG"] if item.startswith(("DEMO-RM", "DEMO-AUX")) else units["PCS"] if item == "DEMO-INS-M4" else units["BAG"]
                amount = Decimal(quantity) * Decimal(price)
                db.execute(text("""
                    INSERT INTO purchase_order_lines (purchase_order_id, item_id, quantity, unit_id,
                        conversion_factor, quantity_base, unit_price, amount)
                    VALUES (:order, :item, :quantity, :unit, 1, :quantity, :price, :amount)
                """), {"order": order_id, "item": items[item], "quantity": Decimal(quantity),
                       "unit": unit, "price": Decimal(price), "amount": amount})
            counts["purchase_orders"] += 1

    plan_specs = [
        ("DEMO-PLAN-001", 8, "open", [("DEMO-FG-BLACK", 600)]),
        ("DEMO-PLAN-002", 3, "open", [("DEMO-FG-WHITE", 300), ("DEMO-FG-CONTROL", 200)]),
    ]
    plan_lines = {}
    for number, age, status, lines in plan_specs:
        plan_id, created = document(db, "production_plans", org, user, number, today - timedelta(days=age),
            status=status, remark="注塑车间排产演示")
        if created:
            for item, quantity in lines:
                line_id = db.execute(text("""
                    INSERT INTO production_plan_lines (production_plan_id, item_id, planned_quantity_base)
                    VALUES (:plan, :item, :quantity) RETURNING id
                """), {"plan": plan_id, "item": items[item], "quantity": quantity}).scalar_one()
                plan_lines[(number, item)] = line_id
            counts["production_plans"] += 1
        else:
            for item, _ in lines:
                plan_lines[(number, item)] = db.execute(text("""
                    SELECT id FROM production_plan_lines WHERE production_plan_id = :plan AND item_id = :item
                """), {"plan": plan_id, "item": items[item]}).scalar_one()
        if number == "DEMO-PLAN-001":
            for sequence, quantity in ((1, 300), (2, 300)):
                order_id, new_order = document(db, "production_orders", org, user,
                    f"DEMO-MO-00{sequence}", today - timedelta(days=7-sequence),
                    production_plan_id=plan_id, status="open" if sequence == 1 else "draft",
                    remark="设备外壳分批注塑")
                if new_order:
                    db.execute(text("""
                        INSERT INTO production_order_outputs (production_order_id, production_plan_line_id,
                                                              item_id, planned_quantity_base)
                        VALUES (:order, :line, :item, :quantity)
                    """), {"order": order_id, "line": plan_lines[(number, "DEMO-FG-BLACK")],
                           "item": items["DEMO-FG-BLACK"], "quantity": quantity})
                    counts["production_orders"] += 1

    out_id, new_out = document(db, "outsourcing_orders", org, user, "DEMO-OUT-001",
        today - timedelta(days=5), processor_id=parties["DEMO-PROC-COAT"], status="open",
        remark="黑色设备外壳喷涂加工")
    if new_out:
        db.execute(text("""
            INSERT INTO outsourcing_material_lines (outsourcing_order_id, item_id, supply_party, expected_quantity_base)
            VALUES (:order, :item, 'self', 200)
        """), {"order": out_id, "item": items["DEMO-SF-SHELL"]})
        db.execute(text("""
            INSERT INTO outsourcing_output_lines (outsourcing_order_id, item_id, expected_quantity_base, unit_price)
            VALUES (:order, :item, 200, 1.80)
        """), {"order": out_id, "item": items["DEMO-FG-BLACK"]})
        counts["outsourcing_orders"] += 1

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-code", default="FACTORY", help="Existing organization code")
    args = parser.parse_args()
    engine = get_engine()
    if engine.url.host not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError("Demo seeding is restricted to a local PostgreSQL server")
    with Session(engine) as db:
        try:
            counts = seed(db, args.org_code)
            db.commit()
        except Exception:
            db.rollback()
            raise
    print("注塑厂演示数据已写入：" + "，".join(f"{name} {count}" for name, count in counts.items()))


if __name__ == "__main__":
    main()
