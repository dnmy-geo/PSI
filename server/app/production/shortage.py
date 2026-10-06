"""Multilevel BOM shortage analysis without stock reservation."""

from collections import defaultdict
from decimal import Decimal, ROUND_UP
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


def calculate_shortage(db: Session, organization_id: UUID,
                       plan: dict) -> dict:
    items = {row["id"]: dict(row) for row in db.execute(text("""
        SELECT i.id, i.code, i.name, i.item_type, i.base_unit_id, i.is_active,
               u.precision_scale
        FROM items i JOIN units u ON u.id = i.base_unit_id
        WHERE i.organization_id = :org
    """), {"org": organization_id}).mappings()}
    stock = dict(db.execute(text("""
        SELECT item_id, sum(quantity_base) FROM stock_balances
        WHERE organization_id = :org GROUP BY item_id
    """), {"org": organization_id}).all())
    graph: dict[UUID, list[tuple[UUID, Decimal]]] = defaultdict(list)
    versions: dict[UUID, int] = {}
    for row in db.execute(text("""
        SELECT h.parent_item_id, h.version, l.child_item_id, l.quantity_base
        FROM bom_headers h JOIN bom_lines l ON l.bom_id = h.id
        WHERE h.organization_id = :org AND h.is_active
        ORDER BY h.parent_item_id, l.sort_order, l.id
    """), {"org": organization_id}).mappings():
        graph[row["parent_item_id"]].append((row["child_item_id"], row["quantity_base"]))
        versions[row["parent_item_id"]] = row["version"]

    reachable: set[UUID] = set()
    visiting: set[UUID] = set()

    def visit(item_id: UUID) -> None:
        if item_id in visiting:
            raise HTTPException(status_code=409, detail="启用中的用料清单存在循环引用")
        if item_id in reachable:
            return
        item = items.get(item_id)
        if item is None or not item["is_active"]:
            raise HTTPException(status_code=409, detail="计划或用料清单中的物料不可用")
        visiting.add(item_id)
        for child_id, _ in graph.get(item_id, []):
            visit(child_id)
        visiting.remove(item_id)
        reachable.add(item_id)

    demand: dict[UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for line in plan["lines"]:
        demand[line["item_id"]] += Decimal(line["planned_quantity_base"])
        visit(line["item_id"])

    indegree = {item_id: 0 for item_id in reachable}
    for parent_id in reachable:
        for child_id, _ in graph.get(parent_id, []):
            indegree[child_id] += 1
    ready = sorted((item_id for item_id, degree in indegree.items() if degree == 0),
                   key=str)
    result = []
    processed = 0
    while ready:
        item_id = ready.pop(0)
        processed += 1
        item = items[item_id]
        quantity = demand[item_id]
        available = stock.get(item_id, Decimal("0"))
        precision = item["precision_scale"]
        quantum = Decimal("1").scaleb(-precision)
        shortage = max(quantity - available, Decimal("0")).quantize(
            quantum, rounding=ROUND_UP)
        if shortage and item["item_type"] != "raw_material" and item_id not in graph:
            raise HTTPException(status_code=409, detail="缺料物料缺少启用中的用料清单")
        if quantity:
            result.append({
                "item_id": item_id, "item_type": item["item_type"],
                "item_code": item["code"], "item_name": item["name"],
                "base_unit_id": item["base_unit_id"],
                "demand_quantity_base": quantity,
                "available_quantity_base": available,
                "shortage_quantity_base": shortage,
                "bom_version": versions.get(item_id),
            })
        for child_id, ratio in graph.get(item_id, []):
            demand[child_id] += shortage * ratio
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(child_id)
                ready.sort(key=str)
    if processed != len(reachable):
        raise HTTPException(status_code=409, detail="启用中的用料清单存在循环引用")
    return {"plan_id": plan["id"], "lines": result}
