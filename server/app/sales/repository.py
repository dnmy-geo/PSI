from uuid import UUID

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import paginate


def get_order(db: Session, organization_id: UUID, order_id: UUID,
              *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, customer_id, document_date,
               delivery_date, status, close_remark, remark, created_at, updated_at
        FROM sales_orders WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": order_id, "org": organization_id}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT l.id, l.item_id, l.unit_id, l.quantity, l.unit_price,
               l.conversion_factor, l.quantity_base, l.amount,
               COALESCE((
                   SELECT sum(sl.quantity_base) FROM sales_shipment_lines sl
                   JOIN sales_shipments s ON s.id = sl.shipment_id
                   WHERE sl.sales_order_line_id = l.id AND s.status = 'posted'
               ), 0) - COALESCE((
                   SELECT sum(rl.quantity_base) FROM sales_return_lines rl
                   JOIN sales_returns r ON r.id = rl.sales_return_id
                   JOIN sales_shipment_lines sl ON sl.id = rl.sales_shipment_line_id
                   WHERE sl.sales_order_line_id = l.id AND r.status = 'posted'
               ), 0) AS shipped_quantity_base,
               l.quantity_base - COALESCE((
                   SELECT sum(sl.quantity_base) FROM sales_shipment_lines sl
                   JOIN sales_shipments s ON s.id = sl.shipment_id
                   WHERE sl.sales_order_line_id = l.id AND s.status = 'posted'
               ), 0) + COALESCE((
                   SELECT sum(rl.quantity_base) FROM sales_return_lines rl
                   JOIN sales_returns r ON r.id = rl.sales_return_id
                   JOIN sales_shipment_lines sl ON sl.id = rl.sales_shipment_line_id
                   WHERE sl.sales_order_line_id = l.id AND r.status = 'posted'
               ), 0) AS unshipped_quantity_base
        FROM sales_order_lines l WHERE l.sales_order_id = :id ORDER BY l.sort_order, l.id
    """), {"id": order_id}).mappings()]
    return result


def list_orders(db: Session, organization_id: UUID, status: str | None,
                limit: int, offset: int, response: Response) -> list[dict]:
    condition = " AND status = :status" if status is not None else ""
    # 摘要里带上未发数量（订单量 − 已出库 + 已退货，逐行合计）：
    # 出库单的订单下拉据此排除已发完的订单。
    query = """
        SELECT id, document_no, customer_id, document_date, status, created_at, updated_at,
               COALESCE((
                   SELECT sum(l.quantity_base
                       - COALESCE((SELECT sum(sl.quantity_base)
                           FROM sales_shipment_lines sl
                           JOIN sales_shipments s ON s.id = sl.shipment_id
                           WHERE sl.sales_order_line_id = l.id AND s.status = 'posted'), 0)
                       + COALESCE((SELECT sum(rl.quantity_base)
                           FROM sales_return_lines rl
                           JOIN sales_returns r ON r.id = rl.sales_return_id
                           JOIN sales_shipment_lines sl ON sl.id = rl.sales_shipment_line_id
                           WHERE sl.sales_order_line_id = l.id AND r.status = 'posted'), 0))
                   FROM sales_order_lines l WHERE l.sales_order_id = sales_orders.id), 0) AS unshipped_quantity_base
        FROM sales_orders WHERE organization_id = :org
    """ + condition + " ORDER BY created_at DESC, document_no DESC"
    return paginate(db, query, {"org": organization_id, "status": status},
                    limit=limit, offset=offset, response=response)
