from uuid import UUID

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import paginate


def get_order(db: Session, org: UUID, order_id: UUID, *, lock: bool = False) -> dict | None:
    row = db.execute(text("""
        SELECT id, organization_id, document_no, processor_id, document_date,
               status, remark, created_at, updated_at FROM outsourcing_orders
        WHERE id = :id AND organization_id = :org
    """ + (" FOR UPDATE" if lock else "")),
        {"id": order_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["materials"] = [dict(line) for line in db.execute(text("""
        SELECT l.id, l.item_id, l.supply_party, l.expected_quantity_base,
               COALESCE((SELECT sum(il.quantity_base)
                         FROM outsourcing_issue_lines il
                         JOIN outsourcing_issues i ON i.id = il.issue_id
                         WHERE il.outsourcing_material_line_id = l.id
                           AND i.status = 'posted'), 0) AS issued_quantity_base,
               l.expected_quantity_base - COALESCE((
                   SELECT sum(il.quantity_base) FROM outsourcing_issue_lines il
                   JOIN outsourcing_issues i ON i.id = il.issue_id
                   WHERE il.outsourcing_material_line_id = l.id
                     AND i.status = 'posted'), 0) AS remaining_quantity_base
        FROM outsourcing_material_lines l
        WHERE l.outsourcing_order_id = :id ORDER BY l.sort_order, l.id
    """), {"id": order_id}).mappings()]
    result["outputs"] = [dict(line) for line in db.execute(text("""
        SELECT l.id, l.item_id, l.expected_quantity_base, l.unit_price,
               COALESCE((SELECT sum(rl.quantity_base)
                         FROM outsourcing_receipt_lines rl
                         JOIN outsourcing_receipts r ON r.id = rl.receipt_id
                         WHERE rl.outsourcing_output_line_id = l.id
                           AND r.status = 'posted'), 0) AS received_quantity_base,
               l.expected_quantity_base - COALESCE((
                   SELECT sum(rl.quantity_base) FROM outsourcing_receipt_lines rl
                   JOIN outsourcing_receipts r ON r.id = rl.receipt_id
                   WHERE rl.outsourcing_output_line_id = l.id
                     AND r.status = 'posted'), 0) AS remaining_quantity_base
        FROM outsourcing_output_lines l
        WHERE l.outsourcing_order_id = :id ORDER BY l.sort_order, l.id
    """), {"id": order_id}).mappings()]
    return result


def list_order_ids(db: Session, org: UUID, status: str | None,
                   limit: int, offset: int, response: Response) -> list[dict]:
    query = """
        SELECT id FROM outsourcing_orders WHERE organization_id = :org
          AND (CAST(:status AS text) IS NULL OR status = :status)
        ORDER BY created_at DESC, document_no DESC
    """
    return paginate(db, query, {"org": org, "status": status},
                    limit=limit, offset=offset, response=response)
