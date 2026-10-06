from uuid import UUID

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import paginate


def get_plan(db: Session, org: UUID, plan_id: UUID,
             *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, document_date, status, remark,
               created_at, updated_at
        FROM production_plans WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": plan_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["lines"] = [dict(line) for line in db.execute(text("""
        SELECT l.id, l.item_id, l.planned_quantity_base,
               -- 计划数量是基本单位下的整数，带上单位编码，列表/详情里数字才不孤立。
               u.code AS unit_code,
               COALESCE((
                   SELECT sum(o.planned_quantity_base)
                   FROM production_order_outputs o
                   JOIN production_orders po ON po.id = o.production_order_id
                   WHERE o.production_plan_line_id = l.id AND po.status <> 'cancelled'
               ), 0) AS allocated_quantity_base,
               l.planned_quantity_base - COALESCE((
                   SELECT sum(o.planned_quantity_base)
                   FROM production_order_outputs o
                   JOIN production_orders po ON po.id = o.production_order_id
                   WHERE o.production_plan_line_id = l.id AND po.status <> 'cancelled'
               ), 0) AS remaining_quantity_base
        FROM production_plan_lines l
        JOIN items i ON i.id = l.item_id
        LEFT JOIN units u ON u.id = i.base_unit_id
        WHERE l.production_plan_id = :id ORDER BY l.sort_order, l.id
    """), {"id": plan_id}).mappings()]
    for line in result["lines"]:
        line["allocated_quantity_base"] = int(line["allocated_quantity_base"])
        line["remaining_quantity_base"] = int(line["remaining_quantity_base"])
    return result


def list_plans(db: Session, org: UUID, status: str | None,
               limit: int, offset: int, response: Response) -> list[dict]:
    extra = " AND status = :status" if status else ""
    # 计数与取页共用这一个字符串，过滤条件不会两边漂移。
    query = """
        SELECT id FROM production_plans WHERE organization_id = :org
    """ + extra + " ORDER BY created_at DESC, document_no DESC"
    ids = paginate(db, query, {"org": org, "status": status},
                   limit=limit, offset=offset, response=response)
    return [plan for row in ids
            if (plan := get_plan(db, org, row["id"])) is not None]


def get_order(db: Session, org: UUID, order_id: UUID,
              *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    row = db.execute(text("""
        SELECT id, organization_id, document_no, production_plan_id,
               document_date, status, remark, created_at, updated_at
        FROM production_orders WHERE id = :id AND organization_id = :org
    """ + suffix), {"id": order_id, "org": org}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["outputs"] = [dict(line) for line in db.execute(text("""
        SELECT o.id, o.production_plan_line_id, o.item_id, o.planned_quantity_base,
               -- 产出数量按物料的基本单位计，带上单位编码，详情里数字才不孤立。
               u.code AS unit_code
        FROM production_order_outputs o
        JOIN items i ON i.id = o.item_id
        LEFT JOIN units u ON u.id = i.base_unit_id
        WHERE o.production_order_id = :id ORDER BY o.sort_order, o.id
    """), {"id": order_id}).mappings()]
    return result


def list_orders(db: Session, org: UUID, plan_id: UUID | None,
                limit: int, offset: int, response: Response) -> list[dict]:
    extra = " AND production_plan_id = :plan_id" if plan_id else ""
    query = """
        SELECT id FROM production_orders WHERE organization_id = :org
    """ + extra + " ORDER BY created_at DESC, document_no DESC"
    ids = paginate(db, query, {"org": org, "plan_id": plan_id},
                   limit=limit, offset=offset, response=response)
    return [order for row in ids
            if (order := get_order(db, org, row["id"])) is not None]
