from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.document_numbers import next_document_number
from app.production import repository
from app.production.schemas import ManualOrderWrite, PlanWrite


def _audit(db: Session, org: UUID, actor: UUID, action: str,
           document_type: str, document_id: UUID) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id)
        VALUES (:org, :actor, :action, :document_type, :id)
    """), {"org": org, "actor": actor, "action": action,
           "document_type": document_type, "id": document_id})


def _validate_plan_lines(db: Session, org: UUID, data: PlanWrite) -> None:
    if len({line.item_id for line in data.lines}) != len(data.lines):
        raise HTTPException(status_code=422, detail="计划产出物料重复")
    for line in data.lines:
        item_type = db.execute(text("""
            SELECT item_type FROM items WHERE id = :id AND organization_id = :org AND is_active
        """), {"id": line.item_id, "org": org}).scalar_one_or_none()
        if item_type not in ("semi_finished", "finished"):
            raise HTTPException(status_code=422, detail="计划产出必须是启用中的半成品或成品")


def _write_plan_lines(db: Session, plan_id: UUID, data: PlanWrite) -> None:
    for index, line in enumerate(data.lines):
        db.execute(text("""
            INSERT INTO production_plan_lines (production_plan_id, item_id, planned_quantity_base, sort_order)
            VALUES (:plan_id, :item_id, :quantity, :sort_order)
        """), {"plan_id": plan_id, "item_id": line.item_id,
               "quantity": line.planned_quantity_base, "sort_order": index})


def create_plan(db: Session, org: UUID, actor: UUID, data: PlanWrite) -> dict:
    _validate_plan_lines(db, org, data)
    try:
        # 同组织内串行取号，避免并发下生成重复单号（与销售/采购/调拨同一套）。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="SC", table="production_plans",
            counter="production_plan_number_counters")
        plan_id = db.execute(text("""
            INSERT INTO production_plans (
                organization_id, document_no, document_date, remark, created_by
            ) VALUES (:org, :document_no, :document_date, :remark, :actor)
            RETURNING id
        """), {"org": org, "document_no": document_no,
               "document_date": data.document_date,
               "remark": data.remark, "actor": actor}).scalar_one()
        _write_plan_lines(db, plan_id, data)
        _audit(db, org, actor, "production_plan.create", "production_plan", plan_id)
        result = repository.get_plan(db, org, plan_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="生产计划单号已存在") from exc


def update_plan(db: Session, org: UUID, actor: UUID, plan_id: UUID,
                data: PlanWrite) -> dict:
    current = repository.get_plan(db, org, plan_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的生产计划可以修改")
    _validate_plan_lines(db, org, data)
    try:
        db.execute(text("""
            UPDATE production_plans SET document_no = :document_no,
                document_date = :document_date, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"id": plan_id, "org": org,
               # 编辑时留空保留原单号，不会被清掉。
               "document_no": (data.document_no or current["document_no"]).strip(),
               "document_date": data.document_date, "remark": data.remark})
        db.execute(text("DELETE FROM production_plan_lines WHERE production_plan_id = :id"),
                   {"id": plan_id})
        _write_plan_lines(db, plan_id, data)
        _audit(db, org, actor, "production_plan.update", "production_plan", plan_id)
        result = repository.get_plan(db, org, plan_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="生产计划单号已存在") from exc


def delete_plan(db: Session, org: UUID, actor: UUID, plan_id: UUID) -> None:
    current = repository.get_plan(db, org, plan_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的生产计划可以删除")
    db.execute(text("DELETE FROM production_plans WHERE id = :id AND organization_id = :org"),
               {"id": plan_id, "org": org})
    _audit(db, org, actor, "production_plan.delete", "production_plan", plan_id)
    db.commit()


def open_plan(db: Session, org: UUID, actor: UUID, plan_id: UUID) -> dict:
    current = repository.get_plan(db, org, plan_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    if current["status"] != "draft" or not current["lines"]:
        raise HTTPException(status_code=409, detail="生产计划不能开单")
    db.execute(text("UPDATE production_plans SET status = 'open' WHERE id = :id AND organization_id = :org"),
               {"id": plan_id, "org": org})
    _audit(db, org, actor, "production_plan.open", "production_plan", plan_id)
    result = repository.get_plan(db, org, plan_id)
    db.commit()
    assert result is not None
    return result


def close_plan(db: Session, org: UUID, actor: UUID, plan_id: UUID) -> dict:
    current = repository.get_plan(db, org, plan_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    if current["status"] != "open":
        raise HTTPException(status_code=409, detail="生产计划不是进行中状态")
    if any(line["remaining_quantity_base"] for line in current["lines"]):
        raise HTTPException(status_code=409, detail="生产计划尚未全部分配")
    db.execute(text("UPDATE production_plans SET status = 'closed' WHERE id = :id AND organization_id = :org"),
               {"id": plan_id, "org": org})
    _audit(db, org, actor, "production_plan.close", "production_plan", plan_id)
    result = repository.get_plan(db, org, plan_id)
    db.commit()
    assert result is not None
    return result


def _create_orders(db: Session, org: UUID, actor: UUID, plan: dict,
                   specs: list[tuple[str, str | None, dict[UUID, int]]]) -> list[dict]:
    plan_lines = {line["id"]: line for line in plan["lines"]}
    totals: dict[UUID, int] = defaultdict(int)
    for _, _, outputs in specs:
        if not outputs:
            raise HTTPException(status_code=422, detail="生产订单没有产出项")
        for line_id, quantity in outputs.items():
            if line_id not in plan_lines or quantity <= 0:
                raise HTTPException(status_code=422, detail="生产产出无效")
            totals[line_id] += quantity
    for line_id, total in totals.items():
        if total > plan_lines[line_id]["remaining_quantity_base"]:
            raise HTTPException(status_code=409, detail="拆分数量超过计划剩余数量")
    try:
        order_ids = []
        for document_no, remark, outputs in specs:
            order_id = db.execute(text("""
                INSERT INTO production_orders (
                    organization_id, document_no, production_plan_id,
                    document_date, remark, created_by
                ) VALUES (:org, :document_no, :plan_id, :document_date, :remark, :actor)
                RETURNING id
            """), {"org": org, "document_no": document_no.strip(),
                   "plan_id": plan["id"], "document_date": plan["document_date"],
                   "remark": remark, "actor": actor}).scalar_one()
            for index, (line_id, quantity) in enumerate(outputs.items()):
                db.execute(text("""
                    INSERT INTO production_order_outputs (
                        production_order_id, production_plan_line_id,
                        item_id, planned_quantity_base, sort_order
                    ) VALUES (:order_id, :plan_line_id, :item_id, :quantity, :sort_order)
                """), {"order_id": order_id, "plan_line_id": line_id,
                       "item_id": plan_lines[line_id]["item_id"],
                       "quantity": quantity, "sort_order": index})
            _audit(db, org, actor, "production_order.create", "production_order", order_id)
            order_ids.append(order_id)
        results = [repository.get_order(db, org, order_id) for order_id in order_ids]
        db.commit()
        return [result for result in results if result is not None]
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="生产订单号已存在") from exc


def auto_split(db: Session, org: UUID, actor: UUID, plan_id: UUID,
               order_count: int) -> list[dict]:
    plan = repository.get_plan(db, org, plan_id, lock=True)
    if plan is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    if plan["status"] != "open":
        raise HTTPException(status_code=409, detail="生产计划不是进行中状态")
    remaining = [line for line in plan["lines"] if line["remaining_quantity_base"]]
    if sum(line["remaining_quantity_base"] for line in remaining) < order_count:
        raise HTTPException(status_code=422, detail="按剩余数量拆不出这么多生产订单")
    allocations: list[dict[UUID, int]] = [dict() for _ in range(order_count)]
    loads = [0] * order_count
    for line in remaining:
        base, remainder = divmod(line["remaining_quantity_base"], order_count)
        for index in range(order_count):
            if base:
                allocations[index][line["id"]] = base
                loads[index] += base
        for index in sorted(range(order_count), key=lambda index: (loads[index], index))[:remainder]:
            allocations[index][line["id"]] = allocations[index].get(line["id"], 0) + 1
            loads[index] += 1
    if any(not outputs for outputs in allocations):
        raise HTTPException(status_code=422, detail="这样拆分会产生没有产出的生产订单")
    specs = []
    number = 1
    reserved: set[str] = set()
    for outputs in allocations:
        number, document_no = _reserve_order_number(db, org, plan["document_no"], number, reserved)
        reserved.add(document_no)
        specs.append((document_no, None, outputs))
    return _create_orders(db, org, actor, plan, specs)


def _reserve_order_number(db: Session, org: UUID, plan_no: str, start: int,
                          reserved: set[str]) -> tuple[int, str]:
    """顺序取一个没被占用的生产订单号（「计划单号-P001」形式）。

    均分拆单和手动拆单留空编号时共用这一个取号口径，两边不会漂移。
    返回下一个可用序号与本次取到的单号。
    """
    number = start
    while True:
        candidate = f"{plan_no}-P{number:03d}"
        number += 1
        if candidate in reserved:
            continue
        used = db.execute(text("""
            SELECT 1 FROM production_orders
            WHERE organization_id = :org AND document_no = :document_no
        """), {"org": org, "document_no": candidate}).scalar_one_or_none()
        if not used:
            return number, candidate


def manual_split(db: Session, org: UUID, actor: UUID, plan_id: UUID,
                 orders: list[ManualOrderWrite]) -> list[dict]:
    plan = repository.get_plan(db, org, plan_id, lock=True)
    if plan is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    if plan["status"] != "open":
        raise HTTPException(status_code=409, detail="生产计划不是进行中状态")
    provided = [(order.document_no or "").strip() for order in orders]
    filled = [number for number in provided if number]
    if len(set(filled)) != len(filled):
        raise HTTPException(status_code=422, detail="生产订单号重复")
    specs = []
    reserved: set[str] = set(filled)
    next_number = 1
    for order, document_no in zip(orders, provided, strict=True):
        if not document_no:     # 留空：按计划单号接着取号（跳过已用掉的号）
            next_number, document_no = _reserve_order_number(
                db, org, plan["document_no"], next_number, reserved)
        reserved.add(document_no)
        outputs = {}
        for line in order.outputs:
            if line.production_plan_line_id in outputs:
                raise HTTPException(status_code=422, detail="同一订单内计划行重复")
            outputs[line.production_plan_line_id] = line.planned_quantity_base
        specs.append((document_no, order.remark, outputs))
    return _create_orders(db, org, actor, plan, specs)


def open_order(db: Session, org: UUID, actor: UUID, order_id: UUID) -> dict:
    order = repository.get_order(db, org, order_id, lock=True)
    if order is None:
        raise HTTPException(status_code=404, detail="生产订单不存在")
    if order["status"] != "draft" or not order["outputs"]:
        raise HTTPException(status_code=409, detail="生产订单不能开单")
    db.execute(text("UPDATE production_orders SET status = 'open' WHERE id = :id AND organization_id = :org"),
               {"id": order_id, "org": org})
    _audit(db, org, actor, "production_order.open", "production_order", order_id)
    result = repository.get_order(db, org, order_id)
    db.commit()
    assert result is not None
    return result


def delete_order(db: Session, org: UUID, actor: UUID, order_id: UUID) -> None:
    reference = repository.get_order(db, org, order_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="生产订单不存在")
    plan = repository.get_plan(db, org, reference["production_plan_id"], lock=True)
    order = repository.get_order(db, org, order_id, lock=True)
    assert plan is not None and order is not None
    if order["status"] not in ("draft", "open"):
        raise HTTPException(status_code=409, detail="生产订单不能删除")
    issues = db.execute(text("""
        SELECT status FROM production_issues WHERE production_order_id = :id
    """), {"id": order_id}).scalars().all()
    consumptions = db.execute(text("""
        SELECT status FROM production_consumptions WHERE production_order_id = :id
    """), {"id": order_id}).scalars().all()
    receipts = db.execute(text("""
        SELECT status FROM production_receipts WHERE production_order_id = :id
    """), {"id": order_id}).scalars().all()
    references = [*issues, *consumptions, *receipts]
    if any(status != "reversed" for status in references):
        raise HTTPException(status_code=409, detail="生产订单还有未冲销的领料、消耗或入库单")
    if references:
        # Keep the order and its reversed documents as an audit trail. Cancelled
        # outputs no longer count toward the plan's allocated quantity.
        db.execute(text("""
            UPDATE production_orders SET status = 'cancelled'
            WHERE id = :id AND organization_id = :org
        """), {"id": order_id, "org": org})
    else:
        db.execute(text("DELETE FROM production_orders WHERE id = :id AND organization_id = :org"),
                   {"id": order_id, "org": org})
    if plan["status"] == "closed":
        db.execute(text("UPDATE production_plans SET status = 'open' WHERE id = :id"),
                   {"id": plan["id"]})
    _audit(db, org, actor, "production_order.cancel" if references else "production_order.delete",
           "production_order", order_id)
    db.commit()
