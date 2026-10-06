from uuid import UUID

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import paginate


def get_issue(db: Session, org: UUID, issue_id: UUID,
              *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, production_order_id,
               source_warehouse_id, target_warehouse_id, document_date,
               status, remark, created_at, updated_at
        FROM production_issues WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": issue_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT id, item_id, unit_id, quantity, bom_quantity_base,
               loss_quantity_base, conversion_factor, quantity_base
        FROM production_issue_lines WHERE issue_id = :id ORDER BY sort_order, id
    """), {"id": issue_id}).mappings()]
    return result


def get_consumption(db: Session, org: UUID, consumption_id: UUID,
                    *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, production_order_id,
               warehouse_id, document_date, status, remark,
               created_at, updated_at
        FROM production_consumptions WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": consumption_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT id, item_id, unit_id, quantity, conversion_factor, quantity_base
        FROM production_consumption_lines WHERE consumption_id = :id ORDER BY sort_order, id
    """), {"id": consumption_id}).mappings()]
    return result


def get_receipt(db: Session, org: UUID, receipt_id: UUID,
                *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, production_order_id,
               document_date, status, remark, created_at, updated_at
        FROM production_receipts WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": receipt_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT id, production_order_output_id, item_id,
               target_warehouse_id, quantity_base
        FROM production_receipt_lines WHERE receipt_id = :id ORDER BY sort_order, id
    """), {"id": receipt_id}).mappings()]
    return result


def list_documents(db: Session, org: UUID, table: str, order_id: UUID | None,
                   limit: int, offset: int, response: Response) -> list[dict]:
    if table not in {"production_issues", "production_consumptions", "production_receipts"}:
        raise ValueError("unsupported production document table")
    extra = " AND production_order_id = :order_id" if order_id else ""
    # 表名来自上面的白名单，不是调用方直接传入的字符串。
    query = f"""
        SELECT id FROM {table} WHERE organization_id = :org
    """ + extra + " ORDER BY created_at DESC, document_no DESC"
    return paginate(db, query, {"org": org, "order_id": order_id},
                    limit=limit, offset=offset, response=response)
