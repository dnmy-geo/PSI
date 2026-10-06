from uuid import UUID

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import paginate

TABLES = {
    "issue": ("outsourcing_issues", "outsourcing_issue_lines", "issue_id"),
    "receipt": ("outsourcing_receipts", "outsourcing_receipt_lines", "receipt_id"),
}


def get_document(db: Session, org: UUID, kind: str, doc_id: UUID,
                 *, lock: bool = False) -> dict | None:
    table, lines, fk = TABLES[kind]
    row = db.execute(text(f"""
        SELECT id, organization_id, document_no, outsourcing_order_id,
               warehouse_id, document_date, status, remark, posted_at,
               created_at, updated_at
        FROM {table} WHERE id = :id AND organization_id = :org
    """ + (" FOR UPDATE" if lock else "")),
        {"id": doc_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    extra = ", unit_price, amount" if kind == "receipt" else ""
    source = f"outsourcing_{'material' if kind == 'issue' else 'output'}_line_id"
    result["lines"] = [dict(line) for line in db.execute(text(f"""
        SELECT id, {source}, item_id, quantity, unit_id,
               conversion_factor, quantity_base{extra}
        FROM {lines} WHERE {fk} = :id ORDER BY sort_order, id
    """), {"id": doc_id}).mappings()]
    return result


def list_document_ids(db: Session, org: UUID, kind: str,
                      order_id: UUID | None, limit: int, offset: int,
                      response: Response) -> list[dict]:
    table = TABLES[kind][0]      # 表名来自 TABLES 白名单，不是调用方直接传入的字符串
    query = f"""
        SELECT id FROM {table} WHERE organization_id = :org
          AND (CAST(:order_id AS uuid) IS NULL OR outsourcing_order_id = :order_id)
        ORDER BY created_at DESC, document_no DESC
    """
    return paginate(db, query, {"org": org, "order_id": order_id},
                    limit=limit, offset=offset, response=response)
