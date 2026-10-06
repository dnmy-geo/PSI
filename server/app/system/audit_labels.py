"""把审计日志里的 document_id 解析成人类可读的单号。

审计表只存 `document_type` + `document_id`，直接显示就是一串 UUID，看日志的人没法据此
找到那张单。这里按类型反查各自的单号字段（多数是 `document_no`，少数是组织/岗位/菜单/
账号的 `code`/`username`）。

表名与列名全部来自本模块的固定映射，不接受调用方传入，因此可以安全地拼进 SQL。
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# document_type -> (表名, 单号列名)
_DOCUMENT_NUMBER_COLUMNS: dict[str, tuple[str, str]] = {
    "sales_order": ("sales_orders", "document_no"),
    "sales_shipment": ("sales_shipments", "document_no"),
    "sales_return": ("sales_returns", "document_no"),
    "purchase_order": ("purchase_orders", "document_no"),
    "purchase_receipt": ("purchase_receipts", "document_no"),
    "production_plan": ("production_plans", "document_no"),
    "production_order": ("production_orders", "document_no"),
    "production_issue": ("production_issues", "document_no"),
    "production_consumption": ("production_consumptions", "document_no"),
    "production_receipt": ("production_receipts", "document_no"),
    "outsourcing_order": ("outsourcing_orders", "document_no"),
    "outsourcing_issue": ("outsourcing_issues", "document_no"),
    "outsourcing_receipt": ("outsourcing_receipts", "document_no"),
    "stocktake": ("stocktakes", "document_no"),
    "stock_adjustment": ("stock_adjustments", "document_no"),
    "cash_record": ("cash_records", "document_no"),
    "department": ("departments", "code"),
    "role": ("roles", "code"),
    "menu": ("menus", "code"),
    "user": ("users", "username"),
    "organization": ("organizations", "code"),
}

# 全局表没有 organization_id，不能按组织过滤：菜单目录是全库共用，organizations 自身即组织。
_GLOBAL_TABLES = {"menus", "organizations"}

# 期初往来没有单号，退而显示往来单位名称。
_PARTY_OPENING_QUERY = """
    SELECT b.id, p.name AS label
    FROM party_opening_balances b JOIN parties p ON p.id = b.party_id
    WHERE b.organization_id = :org AND b.id = ANY(:ids)
"""


def document_labels(db: Session, organization_id: UUID,
                    rows: list[dict]) -> dict[UUID, str]:
    """为一批审计行解析单号；解析不到的条目不会出现在结果里。"""
    by_type: dict[str, list[UUID]] = {}
    for row in rows:
        if row.get("document_type") and row.get("document_id"):
            by_type.setdefault(row["document_type"], []).append(row["document_id"])
    labels: dict[UUID, str] = {}
    for document_type, ids in by_type.items():
        params: dict[str, object] = {"ids": list(set(ids))}
        if document_type == "party_opening_balance":
            query, params["org"] = _PARTY_OPENING_QUERY, organization_id
        else:
            source = _DOCUMENT_NUMBER_COLUMNS.get(document_type)
            if source is None:
                continue                  # 未登记的类型保持原样，不猜
            table, column = source
            scope = "" if table in _GLOBAL_TABLES else "organization_id = :org AND "
            if table not in _GLOBAL_TABLES:
                params["org"] = organization_id
            query = f"SELECT id, {column} AS label FROM {table} WHERE {scope}id = ANY(:ids)"
        for row in db.execute(text(query), params).mappings():
            labels[row["id"]] = row["label"]
    return labels
