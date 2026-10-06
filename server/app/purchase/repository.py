from decimal import Decimal
from uuid import UUID

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import paginate


def get_order(db: Session, org: UUID, order_id: UUID, *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, supplier_id, document_date,
               status, close_remark, remark, created_at, updated_at
        FROM purchase_orders WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": order_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT l.id, l.item_id, l.unit_id, l.quantity, l.unit_price,
               l.conversion_factor, l.quantity_base, l.amount,
               COALESCE((
                   SELECT sum(rl.quantity_base) FROM purchase_receipt_lines rl
                   JOIN purchase_receipts r ON r.id = rl.receipt_id
                   WHERE rl.purchase_order_line_id = l.id AND r.status = 'posted'
               ), 0) - COALESCE((
                   SELECT sum(prl.quantity_base) FROM purchase_return_lines prl
                   JOIN purchase_returns pr ON pr.id = prl.purchase_return_id
                   JOIN purchase_receipt_lines rl ON rl.id = prl.purchase_receipt_line_id
                   WHERE rl.purchase_order_line_id = l.id AND pr.status = 'posted'
               ), 0) AS received_quantity_base,
               l.quantity_base - COALESCE((
                   SELECT sum(rl.quantity_base) FROM purchase_receipt_lines rl
                   JOIN purchase_receipts r ON r.id = rl.receipt_id
                   WHERE rl.purchase_order_line_id = l.id AND r.status = 'posted'
               ), 0) + COALESCE((
                   SELECT sum(prl.quantity_base) FROM purchase_return_lines prl
                   JOIN purchase_returns pr ON pr.id = prl.purchase_return_id
                   JOIN purchase_receipt_lines rl ON rl.id = prl.purchase_receipt_line_id
                   WHERE rl.purchase_order_line_id = l.id AND pr.status = 'posted'
               ), 0) AS unreceived_quantity_base
        FROM purchase_order_lines l WHERE l.purchase_order_id = :id ORDER BY l.sort_order, l.id
    """), {"id": order_id}).mappings()]
    # 未入库数量合计（逐行「订购 − 净入库」之和）：0 = 已入完。
    # 列表的「入库状态」列据此显示；单据状态不随入库进度变化，满额也只说明还能不能继续收货。
    result["unreceived_quantity_base"] = sum(
        (line["unreceived_quantity_base"] for line in result["lines"]), Decimal("0"))
    return result


def list_orders(db: Session, org: UUID, status: str | None,
                limit: int, offset: int, response: Response) -> list[dict]:
    extra = " AND status = :status" if status else ""
    query = """
        SELECT id, organization_id, document_no, supplier_id, document_date,
               status, close_remark, remark
        FROM purchase_orders WHERE organization_id = :org
    """ + extra + " ORDER BY created_at DESC, document_no DESC"
    return paginate(db, query, {"org": org, "status": status},
                    limit=limit, offset=offset, response=response)
