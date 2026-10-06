from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_permission

router = APIRouter(prefix="/api/reports", tags=["reports"])
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
ZERO = Decimal("0")


class ItemSummary(BaseModel):
    item_id: UUID
    item_code: str
    item_name: str
    base_unit_code: str
    quantities: dict[str, Decimal]
    business_amount: Decimal | None = None


class WarehouseSummary(BaseModel):
    warehouse_id: UUID
    warehouse_code: str
    item_id: UUID
    item_code: str
    item_name: str
    base_unit_code: str
    period_in_base: Decimal
    period_out_base: Decimal
    period_net_base: Decimal
    current_balance_base: Decimal
    stocktake_difference_base: Decimal


def _bounds(date_from: date, date_to: date) -> dict:
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="结束日期不能早于开始日期")
    if date_to == date.max:
        raise HTTPException(status_code=422, detail="结束日期超出范围")
    end_date = date_to + timedelta(days=1)
    return {
        "date_from": date_from,
        "date_end": end_date,
        "posted_from": datetime.combine(date_from, time.min, LOCAL_TZ),
        "posted_end": datetime.combine(end_date, time.min, LOCAL_TZ),
    }


def _item_rows(db: Session, org: UUID, metric_sql: dict[str, str],
               params: dict, *, amount_sql: str | None = None) -> list[dict]:
    totals: dict[UUID, dict[str, Decimal]] = {}
    for metric, query in metric_sql.items():
        for row in db.execute(text(query), {"org": org, **params}).mappings():
            totals.setdefault(row["item_id"], {})[metric] = row["quantity"]
    amounts: dict[UUID, Decimal] = {}
    if amount_sql is not None:
        amounts = {row["item_id"]: row["amount"] for row in db.execute(
            text(amount_sql), {"org": org, **params}).mappings()}
    if not totals and not amounts:
        return []
    ids = list(set(totals) | set(amounts))
    metadata = db.execute(text("""
        SELECT i.id, i.code, i.name, u.code AS unit_code
        FROM items i JOIN units u ON u.id = i.base_unit_id
        WHERE i.organization_id = :org AND i.id IN :ids
        ORDER BY i.code
    """).bindparams(bindparam("ids", expanding=True)),
        {"org": org, "ids": ids}).mappings()
    return [{
        "item_id": row["id"], "item_code": row["code"],
        "item_name": row["name"], "base_unit_code": row["unit_code"],
        "quantities": {metric: totals.get(row["id"], {}).get(metric, ZERO)
                       for metric in metric_sql},
        "business_amount": amounts.get(row["id"], ZERO) if amount_sql else None,
    } for row in metadata]


@router.get("/sales", response_model=list[ItemSummary])
def sales_report(date_from: date, date_to: date,
                 user: CurrentUser = Depends(require_permission("reports.sales", "view")),
                 db: Session = Depends(get_db)) -> list[dict]:
    params = _bounds(date_from, date_to)
    queries = {
        "ordered_base": """
            SELECT l.item_id, sum(l.quantity_base) AS quantity
            FROM sales_order_lines l JOIN sales_orders o ON o.id = l.sales_order_id
            WHERE o.organization_id = :org AND o.status IN ('approved','closed')
              AND o.document_date >= :date_from AND o.document_date < :date_end
            GROUP BY l.item_id
        """,
        "shipped_base": """
            SELECT m.item_id, sum(-m.quantity_delta_base) AS quantity
            FROM stock_movements m JOIN sales_shipments s ON s.id = m.source_id
            WHERE m.organization_id = :org
              AND m.source_type IN ('sales_shipment','sales_shipment_reversal')
              AND s.shipment_type = 'normal'
              AND m.posted_at >= :posted_from AND m.posted_at < :posted_end
            GROUP BY m.item_id
        """,
        "returned_base": """
            SELECT m.item_id, sum(m.quantity_delta_base) AS quantity
            FROM stock_movements m
            WHERE m.organization_id = :org
              AND m.source_type IN ('sales_return','sales_return_reversal')
              AND m.posted_at >= :posted_from AND m.posted_at < :posted_end
            GROUP BY m.item_id
        """,
        "replacement_base": """
            SELECT m.item_id, sum(-m.quantity_delta_base) AS quantity
            FROM stock_movements m JOIN sales_shipments s ON s.id = m.source_id
            WHERE m.organization_id = :org
              AND m.source_type IN ('sales_shipment','sales_shipment_reversal')
              AND s.shipment_type = 'replacement'
              AND m.posted_at >= :posted_from AND m.posted_at < :posted_end
            GROUP BY m.item_id
        """,
        "unshipped_base": """
            SELECT l.item_id, sum(l.quantity_base +
                COALESCE((SELECT sum(m.quantity_delta_base)
                    FROM stock_movements m
                    JOIN sales_shipment_lines sl ON sl.id = m.source_line_id
                    WHERE sl.sales_order_line_id = l.id
                      AND m.source_type IN ('sales_shipment','sales_shipment_reversal')
                      AND m.posted_at < :posted_end), 0) +
                COALESCE((SELECT sum(m.quantity_delta_base)
                    FROM stock_movements m
                    JOIN sales_return_lines rl ON rl.id = m.source_line_id
                    JOIN sales_shipment_lines sl ON sl.id = rl.sales_shipment_line_id
                    WHERE sl.sales_order_line_id = l.id
                      AND m.source_type IN ('sales_return','sales_return_reversal')
                      AND m.posted_at < :posted_end), 0) -
                COALESCE((SELECT sum(sl.quantity_base)
                    FROM sales_shipment_lines sl JOIN sales_shipments s ON s.id = sl.shipment_id
                    WHERE sl.sales_order_line_id = l.id AND s.is_opening_reference
                      AND s.posted_at < :posted_end), 0)) AS quantity
            FROM sales_order_lines l JOIN sales_orders o ON o.id = l.sales_order_id
            WHERE o.organization_id = :org AND o.status IN ('approved','closed')
              AND o.document_date < :date_end
              AND (EXISTS (SELECT 1 FROM approval_instances ai
                  WHERE ai.organization_id = :org AND ai.document_type = 'sales_order'
                    AND ai.document_id = o.id AND ai.status = 'approved'
                    AND ai.finished_at < :posted_end)
                OR EXISTS (SELECT 1 FROM carryover_documents c
                  WHERE c.organization_id = :org AND c.historical_order_id = o.id
                    AND c.effective_date < :date_end))
              AND NOT EXISTS (SELECT 1 FROM audit_logs a
                  WHERE a.organization_id = :org AND a.document_type = 'sales_order'
                    AND a.document_id = o.id AND a.action_code = 'sales_order.force_close'
                    AND a.occurred_at < :posted_end)
            GROUP BY l.item_id
        """,
    }
    amount = """
        SELECT l.item_id, sum(e.amount_delta) AS amount
        FROM business_amount_entries e
        JOIN sales_shipment_lines l ON l.id = e.source_line_id
        WHERE e.organization_id = :org
          AND e.source_type IN ('sales_shipment','sales_shipment_reversal')
          AND e.posted_at >= :posted_from AND e.posted_at < :posted_end
        GROUP BY l.item_id
    """
    return _item_rows(db, user.organization_id, queries, params, amount_sql=amount)


@router.get("/purchase", response_model=list[ItemSummary])
def purchase_report(date_from: date, date_to: date,
                    user: CurrentUser = Depends(require_permission("reports.purchase", "view")),
                    db: Session = Depends(get_db)) -> list[dict]:
    params = _bounds(date_from, date_to)
    queries = {
        "ordered_base": """
            SELECT l.item_id, sum(l.quantity_base) AS quantity
            FROM purchase_order_lines l JOIN purchase_orders o ON o.id = l.purchase_order_id
            WHERE o.organization_id = :org AND o.status IN ('open','closed')
              AND o.document_date >= :date_from AND o.document_date < :date_end
            GROUP BY l.item_id
        """,
        "received_base": """
            SELECT m.item_id, sum(m.quantity_delta_base) AS quantity
            FROM stock_movements m
            WHERE m.organization_id = :org
              AND m.source_type IN ('purchase_receipt','purchase_receipt_reversal')
              AND m.posted_at >= :posted_from AND m.posted_at < :posted_end
            GROUP BY m.item_id
        """,
        "returned_base": """
            SELECT m.item_id, sum(-m.quantity_delta_base) AS quantity
            FROM stock_movements m
            WHERE m.organization_id = :org
              AND m.source_type IN ('purchase_return','purchase_return_reversal')
              AND m.posted_at >= :posted_from AND m.posted_at < :posted_end
            GROUP BY m.item_id
        """,
        "unreceived_base": """
            SELECT l.item_id, sum(l.quantity_base -
                COALESCE((SELECT sum(m.quantity_delta_base)
                    FROM stock_movements m
                    JOIN purchase_receipt_lines rl ON rl.id = m.source_line_id
                    WHERE rl.purchase_order_line_id = l.id
                      AND m.source_type IN ('purchase_receipt','purchase_receipt_reversal')
                      AND m.posted_at < :posted_end), 0) -
                COALESCE((SELECT sum(m.quantity_delta_base)
                    FROM stock_movements m
                    JOIN purchase_return_lines prl ON prl.id = m.source_line_id
                    JOIN purchase_receipt_lines rl ON rl.id = prl.purchase_receipt_line_id
                    WHERE rl.purchase_order_line_id = l.id
                      AND m.source_type IN ('purchase_return','purchase_return_reversal')
                      AND m.posted_at < :posted_end), 0) -
                COALESCE((SELECT sum(rl.quantity_base)
                    FROM purchase_receipt_lines rl JOIN purchase_receipts r ON r.id = rl.receipt_id
                    WHERE rl.purchase_order_line_id = l.id AND r.is_opening_reference
                      AND r.posted_at < :posted_end), 0)) AS quantity
            FROM purchase_order_lines l JOIN purchase_orders o ON o.id = l.purchase_order_id
            WHERE o.organization_id = :org AND o.status IN ('open','closed')
              AND o.document_date < :date_end
              AND (EXISTS (SELECT 1 FROM audit_logs opened
                  WHERE opened.organization_id = :org AND opened.document_type = 'purchase_order'
                    AND opened.document_id = o.id AND opened.action_code = 'purchase_order.open'
                    AND opened.occurred_at < :posted_end)
                OR EXISTS (SELECT 1 FROM carryover_documents c
                  WHERE c.organization_id = :org AND c.historical_order_id = o.id
                    AND c.effective_date < :date_end))
              AND NOT EXISTS (SELECT 1 FROM audit_logs a
                  WHERE a.organization_id = :org AND a.document_type = 'purchase_order'
                    AND a.document_id = o.id AND a.action_code = 'purchase_order.force_close'
                    AND a.occurred_at < :posted_end)
            GROUP BY l.item_id
        """,
    }
    amount = """
        SELECT COALESCE(prl.item_id, ptl.item_id) AS item_id,
               sum(e.amount_delta) AS amount
        FROM business_amount_entries e
        LEFT JOIN purchase_receipt_lines prl
          ON prl.id = e.source_line_id
         AND e.source_type IN ('purchase_receipt','purchase_receipt_reversal')
        LEFT JOIN purchase_return_lines ptl
          ON ptl.id = e.source_line_id
         AND e.source_type IN ('purchase_return','purchase_return_reversal')
        WHERE e.organization_id = :org
          AND e.source_type IN ('purchase_receipt','purchase_return',
                                'purchase_receipt_reversal','purchase_return_reversal')
          AND e.posted_at >= :posted_from AND e.posted_at < :posted_end
        GROUP BY COALESCE(prl.item_id, ptl.item_id)
    """
    return _item_rows(db, user.organization_id, queries, params, amount_sql=amount)


@router.get("/inventory", response_model=list[WarehouseSummary])
def inventory_report(date_from: date, date_to: date,
                     user: CurrentUser = Depends(require_permission("reports.inventory", "view")),
                     db: Session = Depends(get_db)) -> list[dict]:
    params = _bounds(date_from, date_to)
    return [dict(row) for row in db.execute(text("""
        WITH movement AS (
            SELECT warehouse_id, item_id,
                   sum(GREATEST(quantity_delta_base, 0)) AS inbound,
                   sum(GREATEST(-quantity_delta_base, 0)) AS outbound
            FROM stock_movements WHERE organization_id = :org
              AND posted_at >= :posted_from AND posted_at < :posted_end
            GROUP BY warehouse_id, item_id
        ), stocktake_difference AS (
            SELECT m.warehouse_id, m.item_id, sum(m.quantity_delta_base) AS quantity
            FROM stock_movements m JOIN stock_adjustments a ON a.id = m.source_id
            WHERE m.organization_id = :org AND a.stocktake_id IS NOT NULL
              AND m.source_type IN ('stock_adjustment', 'stock_adjustment_reversal')
              AND m.posted_at >= :posted_from AND m.posted_at < :posted_end
            GROUP BY m.warehouse_id, m.item_id
        ), keys AS (
            SELECT warehouse_id, item_id FROM movement
            UNION SELECT warehouse_id, item_id FROM stock_balances
              WHERE organization_id = :org
            UNION SELECT warehouse_id, item_id FROM stocktake_difference
        )
        SELECT k.warehouse_id, w.code AS warehouse_code,
               k.item_id, i.code AS item_code, i.name AS item_name,
               u.code AS base_unit_code,
               COALESCE(m.inbound, 0) AS period_in_base,
               COALESCE(m.outbound, 0) AS period_out_base,
               COALESCE(m.inbound, 0) - COALESCE(m.outbound, 0) AS period_net_base,
               COALESCE(b.quantity_base, 0) AS current_balance_base,
               COALESCE(d.quantity, 0) AS stocktake_difference_base
        FROM keys k
        JOIN warehouses w ON w.id = k.warehouse_id AND w.organization_id = :org
        JOIN items i ON i.id = k.item_id AND i.organization_id = :org
        JOIN units u ON u.id = i.base_unit_id
        LEFT JOIN movement m ON m.warehouse_id = k.warehouse_id AND m.item_id = k.item_id
        LEFT JOIN stocktake_difference d ON d.warehouse_id = k.warehouse_id AND d.item_id = k.item_id
        LEFT JOIN stock_balances b ON b.organization_id = :org
          AND b.warehouse_id = k.warehouse_id AND b.item_id = k.item_id
        ORDER BY w.code, i.code
    """), {"org": user.organization_id, **params}).mappings()]


@router.get("/production", response_model=list[ItemSummary])
def production_report(date_from: date, date_to: date,
                      user: CurrentUser = Depends(require_permission("reports.production", "view")),
                      db: Session = Depends(get_db)) -> list[dict]:
    params = _bounds(date_from, date_to)
    queries = {
        "planned_base": """
            SELECT l.item_id, sum(l.planned_quantity_base) AS quantity
            FROM production_plan_lines l JOIN production_plans p ON p.id = l.production_plan_id
            WHERE p.organization_id = :org AND p.status IN ('open','closed')
              AND p.document_date >= :date_from AND p.document_date < :date_end
            GROUP BY l.item_id
        """,
        "ordered_base": """
            SELECT l.item_id, sum(l.planned_quantity_base) AS quantity
            FROM production_order_outputs l JOIN production_orders o ON o.id = l.production_order_id
            WHERE o.organization_id = :org AND o.status <> 'cancelled'
              AND o.document_date >= :date_from AND o.document_date < :date_end
            GROUP BY l.item_id
        """,
        "produced_base": """
            SELECT item_id, sum(quantity_delta_base) AS quantity
            FROM stock_movements WHERE organization_id = :org
              AND source_type IN ('production_receipt','production_receipt_reversal')
              AND posted_at >= :posted_from AND posted_at < :posted_end
            GROUP BY item_id
        """,
        "issued_base": """
            SELECT item_id, sum(-quantity_delta_base) AS quantity
            FROM stock_movements WHERE organization_id = :org
              AND movement_kind IN ('production_issue_out','production_issue_reverse_in')
              AND posted_at >= :posted_from AND posted_at < :posted_end
            GROUP BY item_id
        """,
        "consumed_base": """
            SELECT item_id, sum(-quantity_delta_base) AS quantity
            FROM stock_movements WHERE organization_id = :org
              AND source_type IN ('production_consumption',
                                  'production_consumption_reversal')
              AND posted_at >= :posted_from AND posted_at < :posted_end
            GROUP BY item_id
        """,
    }
    return _item_rows(db, user.organization_id, queries, params)


@router.get("/outsourcing", response_model=list[ItemSummary])
def outsourcing_report(date_from: date, date_to: date,
                       user: CurrentUser = Depends(require_permission("reports.outsourcing", "view")),
                       db: Session = Depends(get_db)) -> list[dict]:
    params = _bounds(date_from, date_to)
    queries = {
        "self_material_expected_base": """
            SELECT l.item_id, sum(l.expected_quantity_base) AS quantity
            FROM outsourcing_material_lines l
            JOIN outsourcing_orders o ON o.id = l.outsourcing_order_id
            WHERE o.organization_id = :org AND o.status IN ('open','closed')
              AND l.supply_party = 'self'
              AND o.document_date >= :date_from AND o.document_date < :date_end
            GROUP BY l.item_id
        """,
        "output_expected_base": """
            SELECT l.item_id, sum(l.expected_quantity_base) AS quantity
            FROM outsourcing_output_lines l
            JOIN outsourcing_orders o ON o.id = l.outsourcing_order_id
            WHERE o.organization_id = :org AND o.status IN ('open','closed')
              AND o.document_date >= :date_from AND o.document_date < :date_end
            GROUP BY l.item_id
        """,
        "issued_base": """
            SELECT item_id, sum(-quantity_delta_base) AS quantity
            FROM stock_movements WHERE organization_id = :org
              AND source_type IN ('outsourcing_issue','outsourcing_issue_reversal')
              AND posted_at >= :posted_from AND posted_at < :posted_end
            GROUP BY item_id
        """,
        "received_base": """
            SELECT item_id, sum(quantity_delta_base) AS quantity
            FROM stock_movements WHERE organization_id = :org
              AND source_type IN ('outsourcing_receipt','outsourcing_receipt_reversal')
              AND posted_at >= :posted_from AND posted_at < :posted_end
            GROUP BY item_id
        """,
    }
    amount = """
        SELECT l.item_id, sum(e.amount_delta) AS amount
        FROM business_amount_entries e
        JOIN outsourcing_receipt_lines l ON l.id = e.source_line_id
        WHERE e.organization_id = :org
          AND e.source_type IN ('outsourcing_receipt','outsourcing_receipt_reversal')
          AND e.posted_at >= :posted_from AND e.posted_at < :posted_end
        GROUP BY l.item_id
    """
    return _item_rows(db, user.organization_id, queries, params, amount_sql=amount)
