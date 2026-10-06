from uuid import UUID

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import paginate


def get_receipt(db: Session, org: UUID, receipt_id: UUID,
                *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, purchase_order_id, warehouse_id,
               document_date, status, remark, is_opening_reference,
               created_at, updated_at
        FROM purchase_receipts WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": receipt_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT id, purchase_order_line_id, item_id, unit_id, quantity,
               conversion_factor, quantity_base, unit_price, amount
        FROM purchase_receipt_lines WHERE receipt_id = :id ORDER BY sort_order, id
    """), {"id": receipt_id}).mappings()]
    return result


def list_receipts(db: Session, org: UUID, order_id: UUID | None,
                  limit: int, offset: int, response: Response) -> list[dict]:
    extra = " AND purchase_order_id = :order_id" if order_id is not None else ""
    query = """
        SELECT id FROM purchase_receipts WHERE organization_id = :org
    """ + extra + " ORDER BY created_at DESC, document_no DESC"
    rows = paginate(db, query, {"org": org, "order_id": order_id},
                    limit=limit, offset=offset, response=response)
    return [receipt for row in rows
            if (receipt := get_receipt(db, org, row["id"])) is not None]


def get_return(db: Session, org: UUID, return_id: UUID,
               *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, original_receipt_id,
               warehouse_id, document_date, status, remark,
               created_at, updated_at
        FROM purchase_returns WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": return_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT id, purchase_receipt_line_id, item_id, unit_id, quantity,
               conversion_factor, quantity_base, amount
        FROM purchase_return_lines WHERE purchase_return_id = :id ORDER BY sort_order, id
    """), {"id": return_id}).mappings()]
    return result


def list_returns(db: Session, org: UUID, receipt_id: UUID | None,
                 limit: int, offset: int, response: Response) -> list[dict]:
    extra = " AND original_receipt_id = :receipt_id" if receipt_id is not None else ""
    query = """
        SELECT id FROM purchase_returns WHERE organization_id = :org
    """ + extra + " ORDER BY created_at DESC, document_no DESC"
    rows = paginate(db, query, {"org": org, "receipt_id": receipt_id},
                    limit=limit, offset=offset, response=response)
    return [purchase_return for row in rows
            if (purchase_return := get_return(db, org, row["id"])) is not None]
