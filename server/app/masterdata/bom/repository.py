from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import paginate


def get_bom(db: Session, organization_id: UUID, bom_id: UUID, *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(
        text("""
            SELECT id, organization_id, parent_item_id, version, is_active
            FROM bom_headers WHERE id = :id AND organization_id = :org
        """ + suffix),
        {"id": bom_id, "org": organization_id},
    ).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(
        text("""
            SELECT id, child_item_id, quantity_base, sort_order
            FROM bom_lines WHERE bom_id = :id ORDER BY sort_order, id
        """),
        {"id": bom_id},
    ).mappings()]
    return result


def _active_bom_graph(db: Session, organization_id: UUID) -> dict[UUID, list[tuple[UUID, Decimal, UUID]]]:
    """父物料 -> [(子物料, 用量, 行 id)]，只取启用中的版本。整个组织一次载入，供展开树复用。"""
    graph: dict[UUID, list[tuple[UUID, Decimal, UUID]]] = defaultdict(list)
    for row in db.execute(text("""
        SELECT h.parent_item_id, l.child_item_id, l.quantity_base, l.id AS line_id
        FROM bom_headers h JOIN bom_lines l ON l.bom_id = h.id
        WHERE h.organization_id = :org AND h.is_active
        ORDER BY l.sort_order, l.id
    """), {"org": organization_id}).mappings():
        graph[row["parent_item_id"]].append((row["child_item_id"], row["quantity_base"], row["line_id"]))
    return graph


def _base_unit_codes(db: Session, organization_id: UUID) -> dict[UUID, str]:
    """物料 -> 基本单位编码。用量是按基本单位存的，不带单位就没法读。"""
    return {row["id"]: row["code"] for row in db.execute(text("""
        SELECT i.id, u.code FROM items i JOIN units u ON u.id = i.base_unit_id
        WHERE i.organization_id = :org
    """), {"org": organization_id}).mappings()}


def _explode(graph: dict[UUID, list[tuple[UUID, Decimal, UUID]]], units: dict[UUID, str],
             item_id: UUID, path: frozenset[UUID], prefix: str) -> list[dict]:
    """把某个物料的用料逐级展开。

    path 记录当前路径，兜底防止自引用（启用时会校验，这里不重复报错）。
    prefix 是父节点的 path_key：同一个半成品的用料会在多个父节点下重复出现，
    行键必须带上路径才不会撞车。
    """
    if item_id in path:
        return []
    path = path | {item_id}
    nodes = []
    for child_id, quantity, line_id in graph.get(item_id, []):
        path_key = f"{prefix}/{line_id}"
        nodes.append({"id": line_id, "path_key": path_key, "item_id": child_id,
                      "quantity_base": quantity, "unit_code": units.get(child_id),
                      "children": _explode(graph, units, child_id, path, path_key)})
    return nodes


def list_boms(db: Session, organization_id: UUID, parent_item_id: UUID | None, *,
              limit: int, offset: int, response: Response) -> list[dict]:
    extra = " AND parent_item_id = :parent_item_id" if parent_item_id else ""
    query = """
        SELECT id, organization_id, parent_item_id, version, is_active, created_at, updated_at
        FROM bom_headers WHERE organization_id = :org
    """ + extra + " ORDER BY created_at DESC, parent_item_id, version DESC"
    rows = paginate(db, query, {"org": organization_id, "parent_item_id": parent_item_id},
                    limit=limit, offset=offset, response=response)
    graph = _active_bom_graph(db, organization_id)
    units = _base_unit_codes(db, organization_id)
    for row in rows:
        row["row_kind"] = "bom"
        row["item_id"] = row["parent_item_id"]
        row["unit_code"] = units.get(row["parent_item_id"])
        row["path_key"] = str(row["id"])
        row["children"] = _explode(graph, units, row["parent_item_id"], frozenset(), row["path_key"])
    return rows

