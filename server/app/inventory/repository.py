from uuid import UUID
from datetime import datetime

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import paginate

# 来源类型 → 单据表。库存流水列表要显示「来源单据」单号而不是 UUID；
# 冲销流水把类型记为 `<来源>_reversal`，查表前先去掉这个后缀。
SOURCE_DOCUMENT_TABLES = {
    "sales_shipment": "sales_shipments",
    "sales_return": "sales_returns",
    "purchase_receipt": "purchase_receipts",
    "purchase_return": "purchase_returns",
    "production_issue": "production_issues",
    "production_consumption": "production_consumptions",
    "production_receipt": "production_receipts",
    "outsourcing_issue": "outsourcing_issues",
    "outsourcing_receipt": "outsourcing_receipts",
    "stock_transfer": "stock_transfers",
    "stock_adjustment": "stock_adjustments",
    "opening_stock": "opening_stock_docs",
}


def _source_table(source_type: object) -> str | None:
    return SOURCE_DOCUMENT_TABLES.get(str(source_type).removesuffix("_reversal"))


def attach_source_numbers(db: Session, rows: list[dict]) -> None:
    """按来源类型批量补上来源单据的单号（取不到就留空，前端显示「—」）。"""
    wanted: dict[str, set[UUID]] = {}
    for row in rows:
        table = _source_table(row["source_type"])
        if table is not None and row["source_id"] is not None:
            wanted.setdefault(table, set()).add(row["source_id"])
    numbers: dict[tuple[str, UUID], str] = {}
    for table, ids in wanted.items():
        numbers.update({(table, document_id): document_no for document_id, document_no in db.execute(
            text(f"SELECT id, document_no FROM {table} WHERE id = ANY(:ids)"), {"ids": list(ids)})})
    for row in rows:
        table = _source_table(row["source_type"])
        row["source_document_no"] = numbers.get((table, row["source_id"])) if table else None


def list_transfers(db: Session, organization_id: UUID, *, status: str | None,
                   limit: int, offset: int, response: Response) -> list[dict]:
    query = """
        SELECT id FROM stock_transfers
        WHERE organization_id = :org
          AND (CAST(:status AS text) IS NULL OR status = :status)
        ORDER BY created_at DESC, document_no DESC
    """
    ids = paginate(db, query, {"org": organization_id, "status": status},
                   limit=limit, offset=offset, response=response)
    return [get_transfer(db, organization_id, row["id"]) for row in ids]


def get_transfer(db: Session, organization_id: UUID, transfer_id: UUID, *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(
        text("""
            SELECT id, organization_id, document_no, document_date,
                   source_warehouse_id, target_warehouse_id, status, remark,
                   created_at, updated_at
            FROM stock_transfers WHERE id = :id AND organization_id = :organization_id
        """ + suffix),
        {"id": transfer_id, "organization_id": organization_id},
    ).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(
        text("""
            SELECT id, item_id, unit_id, quantity, conversion_factor, quantity_base
            FROM stock_transfer_lines WHERE transfer_id = :transfer_id ORDER BY sort_order, id
        """),
        {"transfer_id": transfer_id},
    ).mappings()]
    return result


def list_balances(db: Session, organization_id: UUID, warehouse_id: UUID | None) -> list[dict]:
    warehouse_filter = " AND b.warehouse_id = :warehouse_id" if warehouse_id is not None else ""
    # 带上物料的基本单位编码：结存数量按基本单位计量，列表要能直接显示单位。
    return [dict(row) for row in db.execute(
        text("""
            SELECT b.warehouse_id, b.item_id, b.quantity_base, u.code AS base_unit_code
            FROM stock_balances b
            JOIN items i ON i.id = b.item_id
            JOIN units u ON u.id = i.base_unit_id
            WHERE b.organization_id = :organization_id
        """ + warehouse_filter + """
            ORDER BY b.warehouse_id, b.item_id
        """),
        {"organization_id": organization_id, "warehouse_id": warehouse_id},
    ).mappings()]


def list_movements(
    db: Session, organization_id: UUID, *, warehouse_id: UUID | None,
    item_id: UUID | None, posted_from: datetime | None, posted_to: datetime | None,
    limit: int, offset: int, response: Response,
) -> list[dict]:
    query = """
        SELECT id, warehouse_id, item_id, quantity_delta_base, source_type,
               source_id, source_line_id, movement_kind, reversal_of_id,
               posted_by, posted_at
        FROM stock_movements
        WHERE organization_id = :org
          AND (CAST(:warehouse_id AS uuid) IS NULL OR warehouse_id = :warehouse_id)
          AND (CAST(:item_id AS uuid) IS NULL OR item_id = :item_id)
          AND (CAST(:posted_from AS timestamptz) IS NULL OR posted_at >= :posted_from)
          AND (CAST(:posted_to AS timestamptz) IS NULL OR posted_at < :posted_to)
        ORDER BY posted_at DESC, id DESC
    """
    rows = paginate(db, query, {
        "org": organization_id, "warehouse_id": warehouse_id, "item_id": item_id,
        "posted_from": posted_from, "posted_to": posted_to,
    }, limit=limit, offset=offset, response=response)
    attach_source_numbers(db, rows)
    return rows
