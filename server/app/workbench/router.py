from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.approval.workflow import list_my_tasks
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_permission
from app.production import repository as production_repository
from app.production.shortage import calculate_shortage

router = APIRouter(prefix="/api/workbench", tags=["workbench"])


class OverviewRead(BaseModel):
    pending_my_approvals: int
    approved_sales_orders: int
    open_purchase_orders: int
    open_production_plans: int
    open_production_orders: int
    open_outsourcing_orders: int
    counting_stocktakes: int


class AlertRead(BaseModel):
    code: str
    document_type: str | None = None
    document_id: UUID | None = None
    item_id: UUID | None = None
    demand_quantity_base: Decimal | None = None
    available_quantity_base: Decimal | None = None
    shortage_quantity_base: Decimal | None = None
    detail: str


@router.get("/tasks", response_model=list[dict])
def my_tasks(user: CurrentUser = Depends(require_permission("workbench.tasks", "view")),
             db: Session = Depends(get_db)) -> list[dict]:
    return list_my_tasks(db, user.organization_id, user.id, 100, 0)


@router.get("/overview", response_model=OverviewRead)
def overview(user: CurrentUser = Depends(require_permission("workbench.overview", "view")),
             db: Session = Depends(get_db)) -> dict:
    org = user.organization_id
    counts = {}
    for key, query in {
        "approved_sales_orders": "SELECT count(*) FROM sales_orders WHERE organization_id = :org AND status = 'approved'",
        "open_purchase_orders": "SELECT count(*) FROM purchase_orders WHERE organization_id = :org AND status = 'open'",
        "open_production_plans": "SELECT count(*) FROM production_plans WHERE organization_id = :org AND status = 'open'",
        "open_production_orders": "SELECT count(*) FROM production_orders WHERE organization_id = :org AND status = 'open'",
        "open_outsourcing_orders": "SELECT count(*) FROM outsourcing_orders WHERE organization_id = :org AND status = 'open'",
        "counting_stocktakes": "SELECT count(*) FROM stocktakes WHERE organization_id = :org AND status = 'counting'",
    }.items():
        counts[key] = db.execute(text(query), {"org": org}).scalar_one()
    counts["pending_my_approvals"] = db.execute(text("""
        SELECT count(*) FROM approval_tasks t
        JOIN approval_instances i ON i.id = t.instance_id
        WHERE i.organization_id = :org AND i.status = 'pending'
          AND i.current_step_no = t.step_no AND t.status = 'pending'
          AND (t.approver_user_id = :actor OR EXISTS (
              SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
              WHERE ur.user_id = :actor AND ur.role_id = t.approver_role_id
                AND r.organization_id = :org AND r.is_active
          ))
    """), {"org": org, "actor": user.id}).scalar_one()
    return counts


@router.get("/alerts", response_model=list[AlertRead])
def alerts(user: CurrentUser = Depends(require_permission("workbench.alerts", "view")),
           db: Session = Depends(get_db)) -> list[dict]:
    org = user.organization_id
    result: list[dict] = []
    # Sales does not reserve stock. These rows compare outstanding demand with
    # current on-hand quantity and are advisory only.
    for row in db.execute(text("""
        WITH demand AS (
            SELECT l.item_id,
                   sum(l.quantity_base - COALESCE((
                       SELECT sum(sl.quantity_base) FROM sales_shipment_lines sl
                       JOIN sales_shipments s ON s.id = sl.shipment_id
                       WHERE sl.sales_order_line_id = l.id AND s.status = 'posted'
                   ), 0) + COALESCE((
                       SELECT sum(rl.quantity_base) FROM sales_return_lines rl
                       JOIN sales_returns r ON r.id = rl.sales_return_id
                       JOIN sales_shipment_lines sl ON sl.id = rl.sales_shipment_line_id
                       WHERE sl.sales_order_line_id = l.id AND r.status = 'posted'
                   ), 0)) AS quantity
            FROM sales_order_lines l JOIN sales_orders o ON o.id = l.sales_order_id
            WHERE o.organization_id = :org AND o.status = 'approved'
            GROUP BY l.item_id
        ), stock AS (
            SELECT item_id, sum(quantity_base) AS quantity
            FROM stock_balances WHERE organization_id = :org GROUP BY item_id
        )
        SELECT d.item_id, d.quantity AS demand_quantity_base,
               COALESCE(s.quantity, 0) AS available_quantity_base
        FROM demand d LEFT JOIN stock s ON s.item_id = d.item_id
        WHERE d.quantity > COALESCE(s.quantity, 0)
        ORDER BY d.item_id
    """), {"org": org}).mappings():
        result.append({
            "code": "sales_stock_shortage", "item_id": row["item_id"],
            "demand_quantity_base": row["demand_quantity_base"],
            "available_quantity_base": row["available_quantity_base"],
            "shortage_quantity_base": row["demand_quantity_base"] - row["available_quantity_base"],
            "detail": "已审批销售订单的未发数量超过当前库存；此提醒不占用库存",
        })
    for row in db.execute(text("""
        WITH outstanding AS (
        SELECT o.id AS order_id, o.document_date, l.id AS line_id, l.item_id,
               l.quantity_base - COALESCE((
                   SELECT sum(sl.quantity_base) FROM sales_shipment_lines sl
                   JOIN sales_shipments s ON s.id = sl.shipment_id
                   WHERE sl.sales_order_line_id = l.id AND s.status = 'posted'
               ), 0) + COALESCE((
                   SELECT sum(rl.quantity_base) FROM sales_return_lines rl
                   JOIN sales_returns r ON r.id = rl.sales_return_id
                   JOIN sales_shipment_lines sl ON sl.id = rl.sales_shipment_line_id
                   WHERE sl.sales_order_line_id = l.id AND r.status = 'posted'
               ), 0) AS remaining
        FROM sales_order_lines l JOIN sales_orders o ON o.id = l.sales_order_id
        WHERE o.organization_id = :org AND o.status = 'approved'
        ) SELECT order_id, item_id, remaining FROM outstanding
        WHERE remaining > 0
        ORDER BY document_date, order_id, line_id LIMIT 100
    """), {"org": org}).mappings():
        if row["remaining"] > 0:
            result.append({
                "code": "sales_unshipped", "document_type": "sales_order",
                "document_id": row["order_id"], "item_id": row["item_id"],
                "demand_quantity_base": row["remaining"],
                "detail": "销售订单仍有未发数量",
            })
    for row in db.execute(text("""
        WITH outstanding AS (
        SELECT o.id AS order_id, o.document_date, l.id AS line_id, l.item_id,
               l.quantity_base - COALESCE((
                   SELECT sum(rl.quantity_base) FROM purchase_receipt_lines rl
                   JOIN purchase_receipts r ON r.id = rl.receipt_id
                   WHERE rl.purchase_order_line_id = l.id AND r.status = 'posted'
               ), 0) + COALESCE((
                   SELECT sum(prl.quantity_base) FROM purchase_return_lines prl
                   JOIN purchase_returns pr ON pr.id = prl.purchase_return_id
                   JOIN purchase_receipt_lines rl ON rl.id = prl.purchase_receipt_line_id
                   WHERE rl.purchase_order_line_id = l.id AND pr.status = 'posted'
               ), 0) AS remaining
        FROM purchase_order_lines l JOIN purchase_orders o ON o.id = l.purchase_order_id
        WHERE o.organization_id = :org AND o.status = 'open'
        ) SELECT order_id, item_id, remaining FROM outstanding
        WHERE remaining > 0
        ORDER BY document_date, order_id, line_id LIMIT 100
    """), {"org": org}).mappings():
        if row["remaining"] > 0:
            result.append({
                "code": "purchase_unreceived", "document_type": "purchase_order",
                "document_id": row["order_id"], "item_id": row["item_id"],
                "demand_quantity_base": row["remaining"],
                "detail": "采购订单仍有未入库数量",
            })
    plan_ids = db.execute(text("""
        SELECT id FROM production_plans
        WHERE organization_id = :org AND status = 'open'
        ORDER BY document_date, id LIMIT 100
    """), {"org": org}).scalars()
    for plan_id in plan_ids:
        plan = production_repository.get_plan(db, org, plan_id)
        assert plan is not None
        try:
            shortage = calculate_shortage(db, org, plan)
        except HTTPException as exc:
            result.append({"code": "production_bom_issue",
                           "document_type": "production_plan",
                           "document_id": plan_id,
                           "detail": f"生产计划缺料无法计算：{exc.detail}"})
            continue
        for line in shortage["lines"]:
            if line["shortage_quantity_base"] > 0:
                result.append({
                    "code": "production_shortage",
                    "document_type": "production_plan", "document_id": plan_id,
                    "item_id": line["item_id"],
                    "demand_quantity_base": line["demand_quantity_base"],
                    "available_quantity_base": line["available_quantity_base"],
                    "shortage_quantity_base": line["shortage_quantity_base"],
                    "detail": "生产计划多级用料缺口；仅供决策参考，不扣减或预留库存",
                })
    return result
