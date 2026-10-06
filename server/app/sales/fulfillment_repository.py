from uuid import UUID

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import paginate


def get_shipment(db: Session, org: UUID, shipment_id: UUID,
                 *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, sales_order_id, warehouse_id,
               document_date, shipment_type, status, remark, is_opening_reference,
               created_at, updated_at
        FROM sales_shipments WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": shipment_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT id, sales_order_line_id, item_id, unit_id, quantity,
               conversion_factor, quantity_base, replacement_return_line_id
        FROM sales_shipment_lines WHERE shipment_id = :id ORDER BY sort_order, id
    """), {"id": shipment_id}).mappings()]
    return result


def list_shipments(db: Session, org: UUID, sales_order_id: UUID | None,
                   limit: int, offset: int, response: Response) -> list[dict]:
    extra = " AND sales_order_id = :order_id" if sales_order_id is not None else ""
    query = """
        SELECT id FROM sales_shipments WHERE organization_id = :org
    """ + extra + " ORDER BY created_at DESC, document_no DESC"
    rows = paginate(db, query, {"org": org, "order_id": sales_order_id},
                    limit=limit, offset=offset, response=response)
    return [shipment for row in rows
            if (shipment := get_shipment(db, org, row["id"])) is not None]


def get_return(db: Session, org: UUID, return_id: UUID,
               *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, original_shipment_id,
               target_warehouse_id, document_date, status, remark,
               created_at, updated_at
        FROM sales_returns WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": return_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT id, sales_shipment_line_id, item_id, unit_id, quantity,
               conversion_factor, quantity_base
        FROM sales_return_lines WHERE sales_return_id = :id ORDER BY sort_order, id
    """), {"id": return_id}).mappings()]
    return result


def list_returns(db: Session, org: UUID, original_shipment_id: UUID | None,
                 limit: int, offset: int, response: Response) -> list[dict]:
    extra = " AND original_shipment_id = :shipment_id" if original_shipment_id is not None else ""
    query = """
        SELECT id FROM sales_returns WHERE organization_id = :org
    """ + extra + " ORDER BY created_at DESC, document_no DESC"
    rows = paginate(db, query, {"org": org, "shipment_id": original_shipment_id},
                    limit=limit, offset=offset, response=response)
    return [sales_return for row in rows
            if (sales_return := get_return(db, org, row["id"])) is not None]
