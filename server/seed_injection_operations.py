"""Seed the injection molding demo with execution documents.

Run from server/: .venv/Scripts/python.exe seed_injection_operations.py --org-code FACTORY

seed_injection_demo.py only creates master data and order headers, so every flow stops at
"order placed, nothing fulfilled". This script drives the same service layer the UI uses to
produce receipts, issues, consumptions, production/outsourcing receipts, shipments, a return
with replacement, cash records and a stocktake.

Inventory and business amounts are therefore written by the application itself
(app/inventory/posting.py and each document service), never by raw SQL, so stock_balances,
stock_movements and business_amount_entries stay consistent.

Documents are keyed by document_no and skipped when they already exist, so the script is
safe to re-run. Run it after seed_injection_demo.py.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.approval.workflow import decide_task, list_document_instances
from app.core.db import get_engine
from app.core.security import CurrentUser
from app.inventory.stocktake import (CountLineWrite, CountWrite, StocktakeCreate, create_stocktake,
                                     record_counts, start_stocktake, submit_stocktake)
from app.outsourcing.fulfillment_schemas import IssueWrite as OutIssue, ReceiptWrite as OutReceipt
from app.outsourcing.fulfillment_schemas import IssueLineWrite as OutIssueLine
from app.outsourcing.fulfillment_schemas import ReceiptLineWrite as OutReceiptLine
from app.outsourcing.fulfillment_service import create_document as create_out_doc
from app.outsourcing.fulfillment_service import post_document as post_out_doc
from app.production.operations_schemas import ConsumptionLineWrite, ConsumptionWrite
from app.production.operations_schemas import IssueLineWrite as ProdIssueLine
from app.production.operations_schemas import IssueWrite as ProdIssue
from app.production.operations_schemas import ReceiptLineWrite as ProdReceiptLine
from app.production.operations_schemas import ReceiptWrite as ProdReceipt
from app.production.operations_service import (create_consumption, create_issue,
                                               create_receipt as create_prod_receipt)
from app.production.operations_service import (post_consumption, post_issue,
                                               post_receipt as post_prod_receipt)
from app.production.schemas import PlanLineWrite, PlanWrite
from app.production.service import auto_split, create_plan, open_order, open_plan
from app.purchase.fulfillment_schemas import ReceiptLineWrite, ReceiptWrite
from app.purchase.fulfillment_service import create_receipt, post_receipt
from app.purchase.service import open_order as open_purchase_order
from app.reconciliation.records import CashWrite, OpeningWrite, create_cash_record, create_opening_balance
from app.sales.fulfillment_schemas import (ReturnLineWrite, ReturnWrite, ShipmentLineWrite,
                                           ShipmentWrite)
from app.sales.fulfillment_service import create_return, create_shipment, post_return, post_shipment
from app.sales.service import submit_order


@dataclass
class Ctx:
    org: UUID
    user: CurrentUser
    warehouses: dict[str, UUID]
    items: dict[str, UUID]
    units: dict[str, UUID]
    parties: dict[str, UUID]
    today: date


def load_context(db: Session, org_code: str) -> Ctx:
    org = db.execute(text("SELECT id FROM organizations WHERE code = :code"), {"code": org_code}).scalar_one()
    admin = db.execute(text("""
        SELECT u.id, u.username, u.display_name FROM users u
        JOIN user_roles ur ON ur.user_id = u.id
        JOIN roles r ON r.id = ur.role_id
        WHERE u.organization_id = :org AND r.code = 'system_admin' AND u.is_active
        ORDER BY u.username LIMIT 1
    """), {"org": org}).mappings().one()
    lookup = lambda table: dict(db.execute(  # noqa: E731 - fixed table names below
        text(f"SELECT code, id FROM {table} WHERE organization_id = :org"), {"org": org}).all())
    return Ctx(org=org,
               user=CurrentUser(id=admin["id"], organization_id=org, username=admin["username"],
                                display_name=admin["display_name"], session_token="seed"),
               warehouses=lookup("warehouses"), items=lookup("items"),
               units=lookup("units"), parties=lookup("parties"), today=date.today())


def exists(db: Session, table: str, ctx: Ctx, number: str) -> bool:
    return db.execute(text(f"SELECT 1 FROM {table} WHERE organization_id = :org AND document_no = :n"),
                      {"org": ctx.org, "n": number}).scalar_one_or_none() is not None


def doc_id(db: Session, table: str, ctx: Ctx, number: str) -> UUID:
    return db.execute(text(f"SELECT id FROM {table} WHERE organization_id = :org AND document_no = :n"),
                      {"org": ctx.org, "n": number}).scalar_one()


def order_lines(db: Session, table: str, owner_column: str, owner_id: UUID) -> dict[str, dict]:
    """Order lines keyed by item code, with the quantities the posting rules need."""
    rows = db.execute(text(f"""
        SELECT l.id, l.item_id, l.unit_id, l.quantity_base, i.code AS item_code, l.unit_price
        FROM {table} l JOIN items i ON i.id = l.item_id WHERE l.{owner_column} = :owner
    """), {"owner": owner_id}).mappings().all()
    return {row["item_code"]: dict(row) for row in rows}


def approve(db: Session, ctx: Ctx, document_type: str, document_id: UUID) -> None:
    for instance in list_document_instances(db, ctx.org, document_type, document_id):
        for task in instance["tasks"]:
            if task["status"] == "pending":
                decide_task(db, ctx.user, task["id"], "approve", None)


def purchase_receipts(db: Session, ctx: Ctx) -> list[str]:
    """PO-001 arrives in two batches, PO-002 in one; PO-003 is opened first."""
    done = []
    if not exists(db, "purchase_receipts", ctx, "DEMO-GR-001"):
        po = doc_id(db, "purchase_orders", ctx, "DEMO-PO-001")
        lines = order_lines(db, "purchase_order_lines", "purchase_order_id", po)
        raw = ctx.warehouses["RAW"]
        batch = [("DEMO-GR-001", {k: lines[k] for k in ("DEMO-RM-PP", "DEMO-AUX-BLACK")},
                  {"DEMO-RM-PP": Decimal("500"), "DEMO-AUX-BLACK": Decimal("30")}),
                 ("DEMO-GR-002", {k: lines[k] for k in ("DEMO-RM-PP",)},
                  {"DEMO-RM-PP": Decimal("300")})]
        for number, batch_lines, quantities in batch:
            receipt = create_receipt(db, ctx.org, ctx.user.id, ReceiptWrite(
                document_no=number, purchase_order_id=po, warehouse_id=raw,
                document_date=ctx.today - timedelta(days=6), remark="注塑原料分批到货",
                lines=[ReceiptLineWrite(purchase_order_line_id=line["id"], item_id=line["item_id"],
                                        unit_id=line["unit_id"], quantity=quantities[code])
                       for code, line in batch_lines.items()]))
            post_receipt(db, ctx.org, ctx.user.id, receipt["id"])
            done.append(number)
    if not exists(db, "purchase_receipts", ctx, "DEMO-GR-003"):
        po = doc_id(db, "purchase_orders", ctx, "DEMO-PO-002")
        lines = order_lines(db, "purchase_order_lines", "purchase_order_id", po)
        receipt = create_receipt(db, ctx.org, ctx.user.id, ReceiptWrite(
            document_no="DEMO-GR-003", purchase_order_id=po, warehouse_id=ctx.warehouses["RAW"],
            document_date=ctx.today - timedelta(days=4), remark="ABS 与白色色母入库",
            lines=[ReceiptLineWrite(purchase_order_line_id=line["id"], item_id=line["item_id"],
                                    unit_id=line["unit_id"], quantity=line["quantity_base"])
                   for line in lines.values()]))
        post_receipt(db, ctx.org, ctx.user.id, receipt["id"])
        done.append("DEMO-GR-003")
    if not exists(db, "purchase_receipts", ctx, "DEMO-GR-004"):
        po = doc_id(db, "purchase_orders", ctx, "DEMO-PO-003")
        open_purchase_order(db, ctx.org, ctx.user.id, po)      # 草稿订单先打开才能收货
        lines = order_lines(db, "purchase_order_lines", "purchase_order_id", po)
        receipt = create_receipt(db, ctx.org, ctx.user.id, ReceiptWrite(
            document_no="DEMO-GR-004", purchase_order_id=po, warehouse_id=ctx.warehouses["RAW"],
            document_date=ctx.today - timedelta(days=2), remark="嵌件与包装袋入库",
            lines=[ReceiptLineWrite(purchase_order_line_id=line["id"], item_id=line["item_id"],
                                    unit_id=line["unit_id"], quantity=line["quantity_base"])
                   for line in lines.values()]))
        post_receipt(db, ctx.org, ctx.user.id, receipt["id"])
        done.append("DEMO-GR-004")
    return done


def produce_shells(db: Session, ctx: Ctx) -> list[str]:
    """New plan: injection-mould 400 semi-finished shells into the site warehouse."""
    if exists(db, "production_plans", ctx, "DEMO-PLAN-003"):
        return []
    plan = create_plan(db, ctx.org, ctx.user.id, PlanWrite(
        document_no="DEMO-PLAN-003", document_date=ctx.today - timedelta(days=5),
        remark="外壳注塑排产", lines=[PlanLineWrite(item_id=ctx.items["DEMO-SF-SHELL"],
                                                    planned_quantity_base=400)]))
    open_plan(db, ctx.org, ctx.user.id, plan["id"])
    orders = auto_split(db, ctx.org, ctx.user.id, plan["id"], 1)
    order = orders[0]
    open_order(db, ctx.org, ctx.user.id, order["id"])

    issue = create_issue(db, ctx.org, ctx.user.id, ProdIssue(
        document_no="DEMO-MI-001", production_order_id=order["id"],
        source_warehouse_id=ctx.warehouses["RAW"], target_warehouse_id=ctx.warehouses["SITE"],
        document_date=ctx.today - timedelta(days=5), remark="PP 与黑色色母领至注塑现场",
        lines=[ProdIssueLine(item_id=ctx.items["DEMO-RM-PP"], unit_id=ctx.units["KG"],
                             quantity=Decimal("72"), loss_quantity_base=Decimal("0")),
               ProdIssueLine(item_id=ctx.items["DEMO-AUX-BLACK"], unit_id=ctx.units["KG"],
                             quantity=Decimal("1.6"), loss_quantity_base=Decimal("0"))]))
    post_issue(db, ctx.org, ctx.user.id, issue["id"])

    consumption = create_consumption(db, ctx.org, ctx.user.id, ConsumptionWrite(
        document_no="DEMO-MC-001", production_order_id=order["id"], warehouse_id=ctx.warehouses["SITE"],
        document_date=ctx.today - timedelta(days=4), remark="注塑机台实际耗用",
        lines=[ConsumptionLineWrite(item_id=ctx.items["DEMO-RM-PP"], unit_id=ctx.units["KG"],
                                    quantity=Decimal("72")),
               ConsumptionLineWrite(item_id=ctx.items["DEMO-AUX-BLACK"], unit_id=ctx.units["KG"],
                                    quantity=Decimal("1.6"))]))
    post_consumption(db, ctx.org, ctx.user.id, consumption["id"])

    outputs = db.execute(text("""
        SELECT id, item_id, planned_quantity_base FROM production_order_outputs
        WHERE production_order_id = :order
    """), {"order": order["id"]}).mappings().all()
    receipt = create_prod_receipt(db, ctx.org, ctx.user.id, ProdReceipt(
        document_no="DEMO-MR-001", production_order_id=order["id"],
        document_date=ctx.today - timedelta(days=4), remark="外壳半成品入现场仓",
        lines=[ProdReceiptLine(production_order_output_id=row["id"], item_id=row["item_id"],
                               target_warehouse_id=ctx.warehouses["SITE"],
                               quantity_base=int(row["planned_quantity_base"])) for row in outputs]))
    post_prod_receipt(db, ctx.org, ctx.user.id, receipt["id"])
    return ["DEMO-PLAN-003", "DEMO-MI-001", "DEMO-MC-001", "DEMO-MR-001"]


def assemble_finished(db: Session, ctx: Ctx) -> list[str]:
    """MO-002: issue inserts and bags, consume shells plus inserts, receive finished black shells."""
    if exists(db, "production_receipts", ctx, "DEMO-MR-002"):
        return []
    order = doc_id(db, "production_orders", ctx, "DEMO-MO-002")
    # 拆单产生的订单是草稿，领料前必须先开单；已开单的保持原状。
    if db.execute(text("SELECT status FROM production_orders WHERE id = :id"),
                  {"id": order}).scalar_one() == "draft":
        open_order(db, ctx.org, ctx.user.id, order)

    issue = create_issue(db, ctx.org, ctx.user.id, ProdIssue(
        document_no="DEMO-MI-002", production_order_id=order,
        source_warehouse_id=ctx.warehouses["RAW"], target_warehouse_id=ctx.warehouses["SITE"],
        document_date=ctx.today - timedelta(days=3), remark="嵌件与包装袋领至组装线",
        lines=[ProdIssueLine(item_id=ctx.items["DEMO-INS-M4"], unit_id=ctx.units["PCS"],
                             quantity=Decimal("880"), loss_quantity_base=Decimal("0")),
               ProdIssueLine(item_id=ctx.items["DEMO-PKG-BAG"], unit_id=ctx.units["BAG"],
                             quantity=Decimal("220"), loss_quantity_base=Decimal("0"))]))
    post_issue(db, ctx.org, ctx.user.id, issue["id"])

    consumption = create_consumption(db, ctx.org, ctx.user.id, ConsumptionWrite(
        document_no="DEMO-MC-002", production_order_id=order, warehouse_id=ctx.warehouses["SITE"],
        document_date=ctx.today - timedelta(days=2), remark="组装黑色外壳实际耗用",
        lines=[ConsumptionLineWrite(item_id=ctx.items["DEMO-SF-SHELL"], unit_id=ctx.units["PCS"],
                                    quantity=Decimal("220")),
               ConsumptionLineWrite(item_id=ctx.items["DEMO-INS-M4"], unit_id=ctx.units["PCS"],
                                    quantity=Decimal("880")),
               ConsumptionLineWrite(item_id=ctx.items["DEMO-PKG-BAG"], unit_id=ctx.units["BAG"],
                                    quantity=Decimal("220"))]))
    post_consumption(db, ctx.org, ctx.user.id, consumption["id"])

    outputs = db.execute(text("""
        SELECT id, item_id, planned_quantity_base FROM production_order_outputs
        WHERE production_order_id = :order
    """), {"order": order}).mappings().all()
    # 计划 300，本批只完成 220，余量下批继续；短产必须填写备注。
    receipt = create_prod_receipt(db, ctx.org, ctx.user.id, ProdReceipt(
        document_no="DEMO-MR-002", production_order_id=order,
        document_date=ctx.today - timedelta(days=2), remark="本批完成 220 只，余 80 只待下批",
        lines=[ProdReceiptLine(production_order_output_id=row["id"], item_id=row["item_id"],
                               target_warehouse_id=ctx.warehouses["FINISHED"],
                               quantity_base=220) for row in outputs]))
    post_prod_receipt(db, ctx.org, ctx.user.id, receipt["id"])
    return ["DEMO-MI-002", "DEMO-MC-002", "DEMO-MR-002"]


def outsource_coating(db: Session, ctx: Ctx) -> list[str]:
    """OUT-001: send 200 shells to the painter, receive 200 finished black shells back."""
    if exists(db, "outsourcing_receipts", ctx, "DEMO-OR-001"):
        return []
    order = doc_id(db, "outsourcing_orders", ctx, "DEMO-OUT-001")
    material = db.execute(text("""
        SELECT id, item_id FROM outsourcing_material_lines
        WHERE outsourcing_order_id = :order AND supply_party = 'self'
    """), {"order": order}).mappings().one()
    output = db.execute(text("SELECT id, item_id FROM outsourcing_output_lines WHERE outsourcing_order_id = :order"),
                        {"order": order}).mappings().one()

    issue = create_out_doc(db, ctx.org, ctx.user.id, "issue", OutIssue(
        document_no="DEMO-OI-001", outsourcing_order_id=order, warehouse_id=ctx.warehouses["SITE"],
        document_date=ctx.today - timedelta(days=2), remark="外壳发外喷涂",
        lines=[OutIssueLine(outsourcing_material_line_id=material["id"], item_id=material["item_id"],
                            quantity=Decimal("200"), unit_id=ctx.units["PCS"])]))
    post_out_doc(db, ctx.org, ctx.user.id, "issue", issue["id"])

    receipt = create_out_doc(db, ctx.org, ctx.user.id, "receipt", OutReceipt(
        document_no="DEMO-OR-001", outsourcing_order_id=order, warehouse_id=ctx.warehouses["FINISHED"],
        document_date=ctx.today - timedelta(days=1), remark="喷涂完成入库",
        lines=[OutReceiptLine(outsourcing_output_line_id=output["id"], item_id=output["item_id"],
                              quantity=Decimal("200"), unit_id=ctx.units["PCS"])]))
    post_out_doc(db, ctx.org, ctx.user.id, "receipt", receipt["id"])
    return ["DEMO-OI-001", "DEMO-OR-001"]


def ship_sales(db: Session, ctx: Ctx) -> list[str]:
    """Approve the three orders, ship what stock allows, then return and replace part of SO-001."""
    done = []
    specs = [("DEMO-SO-001", "DEMO-SD-001", ctx.today - timedelta(days=3),
              {"DEMO-FG-BLACK": Decimal("200"), "DEMO-FG-WHITE": Decimal("95")}, "首批发货"),
             ("DEMO-SO-002", "DEMO-SD-002", ctx.today - timedelta(days=2),
              {"DEMO-FG-BLACK": Decimal("280")}, "按现有库存先发一部分"),
             ("DEMO-SO-003", "DEMO-SD-003", ctx.today - timedelta(days=1),
              {"DEMO-FG-CONTROL": Decimal("75")}, "控制盒壳体部分发货")]
    for order_no, shipment_no, when, quantities, remark in specs:
        order = doc_id(db, "sales_orders", ctx, order_no)
        status = db.execute(text("SELECT status FROM sales_orders WHERE id = :id"), {"id": order}).scalar_one()
        if status in ("draft", "rejected"):
            submit_order(db, ctx.org, ctx.user.id, order)
            approve(db, ctx, "sales_order", order)          # 未审批的订单不能出库
        if exists(db, "sales_shipments", ctx, shipment_no):
            continue
        lines = order_lines(db, "sales_order_lines", "sales_order_id", order)
        shipment = create_shipment(db, ctx.org, ctx.user.id, ShipmentWrite(
            document_no=shipment_no, sales_order_id=order, warehouse_id=ctx.warehouses["FINISHED"],
            document_date=when, shipment_type="normal", remark=remark,
            lines=[ShipmentLineWrite(sales_order_line_id=line["id"], item_id=line["item_id"],
                                     unit_id=line["unit_id"], quantity=quantities[code])
                   for code, line in lines.items() if code in quantities]))
        post_shipment(db, ctx.org, ctx.user.id, shipment["id"])
        done.append(shipment_no)

    shipment = doc_id(db, "sales_shipments", ctx, "DEMO-SD-001")
    shipment_lines = db.execute(text("""
        SELECT l.id, l.sales_order_line_id, l.item_id, l.unit_id, i.code AS item_code
        FROM sales_shipment_lines l JOIN items i ON i.id = l.item_id WHERE l.shipment_id = :id
    """), {"id": shipment}).mappings().all()
    black = next(row for row in shipment_lines if row["item_code"] == "DEMO-FG-BLACK")

    if not exists(db, "sales_returns", ctx, "DEMO-SR-001"):
        returned = create_return(db, ctx.org, ctx.user.id, ReturnWrite(
            document_no="DEMO-SR-001", original_shipment_id=shipment,
            target_warehouse_id=ctx.warehouses["FINISHED"], document_date=ctx.today - timedelta(days=2),
            remark="客户反馈 20 只外壳缩水，退回",
            lines=[ReturnLineWrite(sales_shipment_line_id=black["id"], item_id=black["item_id"],
                                   unit_id=black["unit_id"], quantity=Decimal("20"))]))
        post_return(db, ctx.org, ctx.user.id, returned["id"])
        done.append("DEMO-SR-001")

    if not exists(db, "sales_shipments", ctx, "DEMO-SD-004"):
        return_lines = db.execute(text("""
            SELECT l.id, l.item_id, l.unit_id FROM sales_return_lines l
            JOIN sales_returns r ON r.id = l.sales_return_id
            WHERE r.organization_id = :org AND r.document_no = 'DEMO-SR-001'
        """), {"org": ctx.org}).mappings().all()
        replacement = create_shipment(db, ctx.org, ctx.user.id, ShipmentWrite(
            document_no="DEMO-SD-004", sales_order_id=doc_id(db, "sales_orders", ctx, "DEMO-SO-001"),
            warehouse_id=ctx.warehouses["FINISHED"], document_date=ctx.today - timedelta(days=1),
            shipment_type="replacement", remark="退回 20 只的补发",
            lines=[ShipmentLineWrite(sales_order_line_id=black["sales_order_line_id"],
                                     item_id=return_lines[0]["item_id"], unit_id=return_lines[0]["unit_id"],
                                     quantity=Decimal("20"),
                                     replacement_return_line_id=return_lines[0]["id"])]))
        post_shipment(db, ctx.org, ctx.user.id, replacement["id"])
        done.append("DEMO-SD-004")
    return done


def settle_accounts(db: Session, ctx: Ctx) -> list[str]:
    """Opening balances plus the receipts and payments made during the month."""
    done = []
    openings = [("DEMO-CUST-A", "customer", "12000.00"), ("DEMO-CUST-B", "customer", "8600.00"),
                ("DEMO-SUP-RESIN", "supplier", "15000.00"), ("DEMO-SUP-HARD", "supplier", "3200.00"),
                ("DEMO-PROC-COAT", "processor", "2400.00")]
    for code, account_type, amount in openings:
        already = db.execute(text("""
            SELECT 1 FROM party_opening_balances
            WHERE organization_id = :org AND party_id = :party AND account_type = :kind
        """), {"org": ctx.org, "party": ctx.parties[code], "kind": account_type}).scalar_one_or_none()
        if already:
            continue
        create_opening_balance(OpeningWrite(
            party_id=ctx.parties[code], account_type=account_type,
            effective_date=ctx.today - timedelta(days=45), amount=Decimal(amount)), ctx.user, db)
        done.append(f"opening:{code}")

    # 收款额留在 期初 + 本期业务额 之内，避免演示数据出现负的期末余额（即客户预付款）。
    cash = [("DEMO-CR-001", "DEMO-CUST-A", "customer", "receipt", "15000.00", "sales_order", "DEMO-SO-001"),
            ("DEMO-CR-002", "DEMO-CUST-B", "customer", "receipt", "9000.00", None, None),
            ("DEMO-CP-001", "DEMO-SUP-RESIN", "supplier", "payment", "12000.00", "purchase_order", "DEMO-PO-001"),
            ("DEMO-CP-002", "DEMO-SUP-HARD", "supplier", "payment", "2500.00", None, None),
            ("DEMO-CP-003", "DEMO-PROC-COAT", "processor", "payment", "1800.00", "outsourcing_order", "DEMO-OUT-001")]
    for number, party, account_type, record_type, amount, source_type, source_no in cash:
        if exists(db, "cash_records", ctx, number):
            continue
        source_id = None
        if source_type and source_no:
            table = {"sales_order": "sales_orders", "purchase_order": "purchase_orders",
                     "outsourcing_order": "outsourcing_orders"}[source_type]
            source_id = doc_id(db, table, ctx, source_no)
        create_cash_record(CashWrite(
            document_no=number, party_id=ctx.parties[party], account_type=account_type,
            record_type=record_type, document_date=ctx.today - timedelta(days=2),
            amount=Decimal(amount), source_type=source_type, source_id=source_id,
            remark="注塑厂演示收付款"), ctx.user, db)
        done.append(number)
    return done


def count_raw_warehouse(db: Session, ctx: Ctx) -> list[str]:
    """Last: starting a stocktake freezes the warehouse, so nothing may post into it afterwards."""
    if exists(db, "stocktakes", ctx, "DEMO-STK-001"):
        return []
    doc = create_stocktake(StocktakeCreate(
        document_no="DEMO-STK-001", document_date=ctx.today, warehouse_id=ctx.warehouses["RAW"],
        remark="原料仓月末盘点"), ctx.user, db)
    started = start_stocktake(doc["id"], ctx.user, db)
    # 塑胶原料有吸湿与损耗，PP 实盘比账面少 8 公斤，其余账实相符。
    loss = Decimal("8")
    counts = [CountLineWrite(
        item_id=line["item_id"],
        counted_quantity_base=Decimal(line["book_quantity_base"]) - (loss if line["item_id"] == ctx.items["DEMO-RM-PP"] else Decimal("0")))
        for line in started["lines"]]
    record_counts(doc["id"], CountWrite(lines=counts), ctx.user, db)
    submit_stocktake(doc["id"], ctx.user, db)
    approve(db, ctx, "stocktake", doc["id"])          # 审批后自动生成盘盈亏调整单
    return ["DEMO-STK-001"]


def seed(db: Session, org_code: str) -> dict[str, list[str]]:
    ctx = load_context(db, org_code)
    return {
        "采购入库": purchase_receipts(db, ctx),
        "注塑半成品": produce_shells(db, ctx),
        "成品组装": assemble_finished(db, ctx),
        "委外喷涂": outsource_coating(db, ctx),
        "销售发货": ship_sales(db, ctx),
        "往来结算": settle_accounts(db, ctx),
        "月末盘点": count_raw_warehouse(db, ctx),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-code", default="FACTORY", help="Existing organization code")
    args = parser.parse_args()
    engine = get_engine()
    if engine.url.host not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError("Demo seeding is restricted to a local PostgreSQL server")
    with Session(engine) as db:
        try:
            result = seed(db, args.org_code)
        except Exception:
            db.rollback()
            raise
    for phase, numbers in result.items():
        print(f"{phase}：{'、'.join(numbers) if numbers else '已存在，跳过'}")


if __name__ == "__main__":
    main()
