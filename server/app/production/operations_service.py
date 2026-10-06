from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.document_numbers import next_document_number
from app.inventory.posting import StockChange, post_stock_changes
from app.inventory.quantities import quantity_snapshot
from app.production import operations_repository as documents
from app.production import repository as orders
from app.production.operations_schemas import ConsumptionWrite, IssueWrite, ReceiptWrite
from app.production.service import _audit


def _warehouse_active(db: Session, org: UUID, warehouse_id: UUID) -> None:
    active = db.execute(text("""
        SELECT is_active FROM warehouses WHERE id = :id AND organization_id = :org
    """), {"id": warehouse_id, "org": org}).scalar_one_or_none()
    if not active:
        raise HTTPException(status_code=422, detail="仓库不可用")


def _open_order(db: Session, org: UUID, order_id: UUID) -> dict:
    order = orders.get_order(db, org, order_id)
    if order is None or order["status"] != "open":
        raise HTTPException(status_code=409, detail="生产订单不是进行中状态")
    return order


def _issue_snapshots(db: Session, org: UUID,
                     data: IssueWrite) -> list[tuple[Decimal, Decimal]]:
    _open_order(db, org, data.production_order_id)
    if data.source_warehouse_id == data.target_warehouse_id:
        raise HTTPException(status_code=422, detail="来源仓与目标仓不能相同")
    _warehouse_active(db, org, data.source_warehouse_id)
    _warehouse_active(db, org, data.target_warehouse_id)
    if len({line.item_id for line in data.lines}) != len(data.lines):
        raise HTTPException(status_code=422, detail="领料物料重复")
    result = []
    for line in data.lines:
        factor, base = quantity_snapshot(db, org, line.item_id, line.unit_id, line.quantity)
        if line.loss_quantity_base > base:
            raise HTTPException(status_code=422, detail="损耗量超过领料数量")
        if line.bom_quantity_base is not None and \
                line.bom_quantity_base + line.loss_quantity_base != base:
            raise HTTPException(status_code=422, detail="领料数量必须等于 BOM 用量加损耗量")
        result.append((factor, base))
    return result


def _write_issue_lines(db: Session, issue_id: UUID, data: IssueWrite,
                       snapshots: list[tuple[Decimal, Decimal]]) -> None:
    for index, (line, (factor, base)) in enumerate(zip(data.lines, snapshots, strict=True)):
        db.execute(text("""
            INSERT INTO production_issue_lines (
                issue_id, item_id, bom_quantity_base, loss_quantity_base,
                quantity, unit_id, conversion_factor, quantity_base, sort_order
            ) VALUES (:issue_id, :item_id, :bom, :loss,
                      :quantity, :unit_id, :factor, :base, :sort_order)
        """), {"issue_id": issue_id, "item_id": line.item_id,
               "bom": line.bom_quantity_base, "loss": line.loss_quantity_base,
               "quantity": line.quantity, "unit_id": line.unit_id,
               "factor": factor, "base": base, "sort_order": index})


def create_issue(db: Session, org: UUID, actor: UUID, data: IssueWrite) -> dict:
    snapshots = _issue_snapshots(db, org, data)
    try:
        # 同组织内串行取号，避免并发下生成重复单号（与销售/采购/调拨同一套）。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="SCLL", table="production_issues",
            counter="production_issue_number_counters")
        issue_id = db.execute(text("""
            INSERT INTO production_issues (
                organization_id, document_no, production_order_id,
                source_warehouse_id, target_warehouse_id, document_date,
                remark, created_by
            ) VALUES (:org, :document_no, :order_id, :source_id, :target_id,
                      :document_date, :remark, :actor) RETURNING id
        """), {"org": org, "document_no": document_no,
               "order_id": data.production_order_id,
               "source_id": data.source_warehouse_id,
               "target_id": data.target_warehouse_id,
               "document_date": data.document_date,
               "remark": data.remark, "actor": actor}).scalar_one()
        _write_issue_lines(db, issue_id, data, snapshots)
        _audit(db, org, actor, "production_issue.create", "production_issue", issue_id)
        result = documents.get_issue(db, org, issue_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="生产领料单号已存在") from exc


def update_issue(db: Session, org: UUID, actor: UUID, issue_id: UUID,
                 data: IssueWrite) -> dict:
    current = documents.get_issue(db, org, issue_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="生产领料单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的生产领料单可以修改")
    snapshots = _issue_snapshots(db, org, data)
    try:
        db.execute(text("""
            UPDATE production_issues SET document_no = :document_no,
                production_order_id = :order_id,
                source_warehouse_id = :source_id, target_warehouse_id = :target_id,
                document_date = :document_date, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"id": issue_id, "org": org,
               # 编辑时留空保留原单号，不会被清掉。
               "document_no": (data.document_no or current["document_no"]).strip(),
               "order_id": data.production_order_id,
               "source_id": data.source_warehouse_id,
               "target_id": data.target_warehouse_id,
               "document_date": data.document_date, "remark": data.remark})
        db.execute(text("DELETE FROM production_issue_lines WHERE issue_id = :id"),
                   {"id": issue_id})
        _write_issue_lines(db, issue_id, data, snapshots)
        _audit(db, org, actor, "production_issue.update", "production_issue", issue_id)
        result = documents.get_issue(db, org, issue_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="生产领料单号已存在") from exc


def delete_issue(db: Session, org: UUID, actor: UUID, issue_id: UUID) -> None:
    current = documents.get_issue(db, org, issue_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="生产领料单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的生产领料单可以删除")
    db.execute(text("DELETE FROM production_issues WHERE id = :id AND organization_id = :org"),
               {"id": issue_id, "org": org})
    _audit(db, org, actor, "production_issue.delete", "production_issue", issue_id)
    db.commit()


def post_issue(db: Session, org: UUID, actor: UUID, issue_id: UUID) -> dict:
    reference = documents.get_issue(db, org, issue_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="生产领料单不存在")
    order = orders.get_order(db, org, reference["production_order_id"], lock=True)
    issue = documents.get_issue(db, org, issue_id, lock=True)
    assert order is not None and issue is not None
    if issue["status"] == "posted":
        return issue
    if issue["status"] != "draft" or order["status"] != "open":
        raise HTTPException(status_code=409, detail="生产领料单不能过账")
    changes = []
    for line in issue["lines"]:
        for warehouse_id, sign, kind in (
            (issue["source_warehouse_id"], Decimal("-1"), "production_issue_out"),
            (issue["target_warehouse_id"], Decimal("1"), "production_issue_in"),
        ):
            changes.append(StockChange(
                warehouse_id=warehouse_id, item_id=line["item_id"],
                quantity_delta_base=line["quantity_base"] * sign,
                source_type="production_issue", source_id=issue_id,
                source_line_id=line["id"], movement_kind=kind,
            ))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    db.execute(text("""
        UPDATE production_issues SET status = 'posted', posted_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": issue_id, "org": org})
    _audit(db, org, actor, "production_issue.post", "production_issue", issue_id)
    result = documents.get_issue(db, org, issue_id)
    db.commit()
    assert result is not None
    return result


def reverse_issue(db: Session, org: UUID, actor: UUID, issue_id: UUID,
                  reason: str) -> dict:
    reference = documents.get_issue(db, org, issue_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="生产领料单不存在")
    order = orders.get_order(db, org, reference["production_order_id"], lock=True)
    issue = documents.get_issue(db, org, issue_id, lock=True)
    assert order is not None and issue is not None
    if issue["status"] == "reversed":
        return issue
    # 拆开两种原因：单据自身没到已过账，和所属订单已完工。合在一起写，用户不知道该先做什么。
    if issue["status"] != "posted":
        raise HTTPException(status_code=409, detail="只有已过账的生产领料单可以冲销")
    if order["status"] == "completed":
        raise HTTPException(status_code=409, detail="生产订单已完工，请先冲销生产入库单")
    active_consumption = db.execute(text("""
        SELECT 1 FROM production_consumptions
        WHERE production_order_id = :order_id AND status = 'posted' LIMIT 1
    """), {"order_id": order["id"]}).scalar_one_or_none()
    if active_consumption:
        raise HTTPException(status_code=409, detail="请先冲销生产消耗单")
    changes = []
    for line in issue["lines"]:
        for warehouse_id, sign, original_kind, reverse_kind in (
            (issue["source_warehouse_id"], Decimal("1"),
             "production_issue_out", "production_issue_reverse_in"),
            (issue["target_warehouse_id"], Decimal("-1"),
             "production_issue_in", "production_issue_reverse_out"),
        ):
            original_id = db.execute(text("""
                SELECT id FROM stock_movements
                WHERE organization_id = :org AND source_type = 'production_issue'
                  AND source_line_id = :line_id AND warehouse_id = :warehouse_id
                  AND movement_kind = :kind
            """), {"org": org, "line_id": line["id"],
                   "warehouse_id": warehouse_id, "kind": original_kind}).scalar_one()
            changes.append(StockChange(
                warehouse_id=warehouse_id, item_id=line["item_id"],
                quantity_delta_base=line["quantity_base"] * sign,
                source_type="production_issue_reversal", source_id=issue_id,
                source_line_id=line["id"], movement_kind=reverse_kind,
                reversal_of_id=original_id,
            ))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    db.execute(text("""
        UPDATE production_issues SET status = 'reversed'
        WHERE id = :id AND organization_id = :org
    """), {"id": issue_id, "org": org})
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, 'production_issue.reverse',
                'production_issue', :id, :reason)
    """), {"org": org, "actor": actor, "id": issue_id,
           "reason": reason.strip()})
    result = documents.get_issue(db, org, issue_id)
    db.commit()
    assert result is not None
    return result


def _consumption_snapshots(db: Session, org: UUID,
                           data: ConsumptionWrite) -> list[tuple[Decimal, Decimal]]:
    _open_order(db, org, data.production_order_id)
    _warehouse_active(db, org, data.warehouse_id)
    if len({line.item_id for line in data.lines}) != len(data.lines):
        raise HTTPException(status_code=422, detail="消耗物料重复")
    return [quantity_snapshot(db, org, line.item_id, line.unit_id, line.quantity)
            for line in data.lines]


def _write_consumption_lines(db: Session, consumption_id: UUID,
                             data: ConsumptionWrite,
                             snapshots: list[tuple[Decimal, Decimal]]) -> None:
    for index, (line, (factor, base)) in enumerate(zip(data.lines, snapshots, strict=True)):
        db.execute(text("""
            INSERT INTO production_consumption_lines (
                consumption_id, item_id, quantity, unit_id,
                conversion_factor, quantity_base, sort_order
            ) VALUES (:consumption_id, :item_id, :quantity,
                      :unit_id, :factor, :base, :sort_order)
        """), {"consumption_id": consumption_id,
               "item_id": line.item_id, "quantity": line.quantity,
               "unit_id": line.unit_id, "factor": factor, "base": base,
               "sort_order": index})


def create_consumption(db: Session, org: UUID, actor: UUID,
                       data: ConsumptionWrite) -> dict:
    snapshots = _consumption_snapshots(db, org, data)
    try:
        # 同组织内串行取号，避免并发下生成重复单号（与销售/采购/调拨同一套）。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="SCXH", table="production_consumptions",
            counter="production_consumption_number_counters")
        consumption_id = db.execute(text("""
            INSERT INTO production_consumptions (
                organization_id, document_no, production_order_id,
                warehouse_id, document_date, remark, created_by
            ) VALUES (:org, :document_no, :order_id, :warehouse_id,
                      :document_date, :remark, :actor) RETURNING id
        """), {"org": org, "document_no": document_no,
               "order_id": data.production_order_id,
               "warehouse_id": data.warehouse_id,
               "document_date": data.document_date,
               "remark": data.remark, "actor": actor}).scalar_one()
        _write_consumption_lines(db, consumption_id, data, snapshots)
        _audit(db, org, actor, "production_consumption.create",
               "production_consumption", consumption_id)
        result = documents.get_consumption(db, org, consumption_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="生产消耗单号已存在") from exc


def update_consumption(db: Session, org: UUID, actor: UUID, consumption_id: UUID,
                       data: ConsumptionWrite) -> dict:
    current = documents.get_consumption(db, org, consumption_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="生产消耗单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的消耗单可以修改")
    snapshots = _consumption_snapshots(db, org, data)
    try:
        db.execute(text("""
            UPDATE production_consumptions SET document_no = :document_no,
                production_order_id = :order_id, warehouse_id = :warehouse_id,
                document_date = :document_date, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"id": consumption_id, "org": org,
               # 编辑时留空保留原单号，不会被清掉。
               "document_no": (data.document_no or current["document_no"]).strip(),
               "order_id": data.production_order_id,
               "warehouse_id": data.warehouse_id,
               "document_date": data.document_date, "remark": data.remark})
        db.execute(text("DELETE FROM production_consumption_lines WHERE consumption_id = :id"),
                   {"id": consumption_id})
        _write_consumption_lines(db, consumption_id, data, snapshots)
        _audit(db, org, actor, "production_consumption.update",
               "production_consumption", consumption_id)
        result = documents.get_consumption(db, org, consumption_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="生产消耗单号已存在") from exc


def delete_consumption(db: Session, org: UUID, actor: UUID, consumption_id: UUID) -> None:
    current = documents.get_consumption(db, org, consumption_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="生产消耗单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的消耗单可以删除")
    db.execute(text("DELETE FROM production_consumptions WHERE id = :id AND organization_id = :org"),
               {"id": consumption_id, "org": org})
    _audit(db, org, actor, "production_consumption.delete",
           "production_consumption", consumption_id)
    db.commit()


def post_consumption(db: Session, org: UUID, actor: UUID, consumption_id: UUID) -> dict:
    reference = documents.get_consumption(db, org, consumption_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="生产消耗单不存在")
    order = orders.get_order(db, org, reference["production_order_id"], lock=True)
    consumption = documents.get_consumption(db, org, consumption_id, lock=True)
    assert order is not None and consumption is not None
    if consumption["status"] == "posted":
        return consumption
    if consumption["status"] != "draft" or order["status"] != "open":
        raise HTTPException(status_code=409, detail="生产消耗单不能过账")
    changes = [StockChange(
        warehouse_id=consumption["warehouse_id"], item_id=line["item_id"],
        quantity_delta_base=-line["quantity_base"],
        source_type="production_consumption", source_id=consumption_id,
        source_line_id=line["id"], movement_kind="production_consumption_out",
    ) for line in consumption["lines"]]
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    db.execute(text("""
        UPDATE production_consumptions SET status = 'posted', posted_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": consumption_id, "org": org})
    _audit(db, org, actor, "production_consumption.post",
           "production_consumption", consumption_id)
    result = documents.get_consumption(db, org, consumption_id)
    db.commit()
    assert result is not None
    return result


def reverse_consumption(db: Session, org: UUID, actor: UUID,
                        consumption_id: UUID, reason: str) -> dict:
    reference = documents.get_consumption(db, org, consumption_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="生产消耗单不存在")
    order = orders.get_order(db, org, reference["production_order_id"], lock=True)
    consumption = documents.get_consumption(db, org, consumption_id, lock=True)
    assert order is not None and consumption is not None
    if consumption["status"] == "reversed":
        return consumption
    if consumption["status"] != "posted":
        raise HTTPException(status_code=409, detail="只有已过账的生产消耗单可以冲销")
    if order["status"] != "open":
        raise HTTPException(status_code=409, detail="生产订单不在进行中，请先冲销生产入库单")
    changes = []
    for line in consumption["lines"]:
        original_id = db.execute(text("""
            SELECT id FROM stock_movements
            WHERE organization_id = :org AND source_type = 'production_consumption'
              AND source_id = :doc_id AND source_line_id = :line_id
        """), {"org": org, "doc_id": consumption_id,
               "line_id": line["id"]}).scalar_one()
        changes.append(StockChange(
            warehouse_id=consumption["warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=line["quantity_base"],
            source_type="production_consumption_reversal", source_id=consumption_id,
            source_line_id=line["id"], movement_kind="production_consumption_reverse_in",
            reversal_of_id=original_id))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    db.execute(text("""
        UPDATE production_consumptions SET status = 'reversed'
        WHERE id = :id AND organization_id = :org
    """), {"id": consumption_id, "org": org})
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, 'production_consumption.reverse',
                'production_consumption', :id, :reason)
    """), {"org": org, "actor": actor, "id": consumption_id,
           "reason": reason.strip()})
    result = documents.get_consumption(db, org, consumption_id)
    db.commit()
    assert result is not None
    return result


def _receipt_outputs(db: Session, org: UUID, data: ReceiptWrite) -> dict[UUID, int]:
    order = _open_order(db, org, data.production_order_id)
    outputs = {output["id"]: output for output in order["outputs"]}
    seen: set[tuple[UUID, UUID]] = set()
    totals: dict[UUID, int] = defaultdict(int)
    for line in data.lines:
        output = outputs.get(line.production_order_output_id)
        if output is None or output["item_id"] != line.item_id:
            raise HTTPException(status_code=422, detail="入库产出与生产订单不一致")
        _warehouse_active(db, org, line.target_warehouse_id)
        key = (line.production_order_output_id, line.target_warehouse_id)
        if key in seen:
            raise HTTPException(status_code=422, detail="同一产出的入库仓库重复")
        seen.add(key)
        totals[line.production_order_output_id] += line.quantity_base
    if set(totals) != set(outputs):
        raise HTTPException(status_code=422, detail="入库单必须包含生产订单的全部产出")
    for output_id, total in totals.items():
        if total > outputs[output_id]["planned_quantity_base"]:
            raise HTTPException(status_code=422, detail="入库数量超过计划产出")
    return totals


def _write_receipt_lines(db: Session, receipt_id: UUID, data: ReceiptWrite) -> None:
    for index, line in enumerate(data.lines):
        db.execute(text("""
            INSERT INTO production_receipt_lines (
                receipt_id, production_order_output_id, item_id,
                target_warehouse_id, quantity_base, sort_order
            ) VALUES (:receipt_id, :output_id, :item_id, :warehouse_id, :quantity, :sort_order)
        """), {"receipt_id": receipt_id,
               "output_id": line.production_order_output_id,
               "item_id": line.item_id,
               "warehouse_id": line.target_warehouse_id,
               "quantity": line.quantity_base, "sort_order": index})


def create_receipt(db: Session, org: UUID, actor: UUID, data: ReceiptWrite) -> dict:
    _receipt_outputs(db, org, data)
    try:
        # 同组织内串行取号，避免并发下生成重复单号（与销售/采购/调拨同一套）。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="SCRK", table="production_receipts",
            counter="production_receipt_number_counters")
        receipt_id = db.execute(text("""
            INSERT INTO production_receipts (
                organization_id, document_no, production_order_id,
                document_date, remark, created_by
            ) VALUES (:org, :document_no, :order_id, :document_date,
                      :remark, :actor) RETURNING id
        """), {"org": org, "document_no": document_no,
               "order_id": data.production_order_id,
               "document_date": data.document_date,
               "remark": data.remark, "actor": actor}).scalar_one()
        _write_receipt_lines(db, receipt_id, data)
        _audit(db, org, actor, "production_receipt.create",
               "production_receipt", receipt_id)
        result = documents.get_receipt(db, org, receipt_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该生产订单已有入库单，或单号已被占用") from exc


def update_receipt(db: Session, org: UUID, actor: UUID, receipt_id: UUID,
                   data: ReceiptWrite) -> dict:
    current = documents.get_receipt(db, org, receipt_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="生产入库单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的生产入库单可以修改")
    if data.production_order_id != current["production_order_id"]:
        raise HTTPException(status_code=422, detail="生产入库单不能更换所属生产订单")
    _receipt_outputs(db, org, data)
    try:
        db.execute(text("""
            UPDATE production_receipts SET document_no = :document_no,
                document_date = :document_date, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"id": receipt_id, "org": org,
               # 编辑时留空保留原单号，不会被清掉。
               "document_no": (data.document_no or current["document_no"]).strip(),
               "document_date": data.document_date, "remark": data.remark})
        db.execute(text("DELETE FROM production_receipt_lines WHERE receipt_id = :id"),
                   {"id": receipt_id})
        _write_receipt_lines(db, receipt_id, data)
        _audit(db, org, actor, "production_receipt.update",
               "production_receipt", receipt_id)
        result = documents.get_receipt(db, org, receipt_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="生产入库单号已存在") from exc


def delete_receipt(db: Session, org: UUID, actor: UUID, receipt_id: UUID) -> None:
    current = documents.get_receipt(db, org, receipt_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="生产入库单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的生产入库单可以删除")
    db.execute(text("DELETE FROM production_receipts WHERE id = :id AND organization_id = :org"),
               {"id": receipt_id, "org": org})
    _audit(db, org, actor, "production_receipt.delete",
           "production_receipt", receipt_id)
    db.commit()


def post_receipt(db: Session, org: UUID, actor: UUID, receipt_id: UUID) -> dict:
    reference = documents.get_receipt(db, org, receipt_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="生产入库单不存在")
    order = orders.get_order(db, org, reference["production_order_id"], lock=True)
    receipt = documents.get_receipt(db, org, receipt_id, lock=True)
    assert order is not None and receipt is not None
    if receipt["status"] == "posted":
        return receipt
    if receipt["status"] != "draft" or order["status"] != "open":
        raise HTTPException(status_code=409, detail="生产入库单不能过账")
    outputs = {output["id"]: output for output in order["outputs"]}
    totals: dict[UUID, int] = defaultdict(int)
    changes = []
    for line in receipt["lines"]:
        output = outputs.get(line["production_order_output_id"])
        if output is None or output["item_id"] != line["item_id"]:
            raise HTTPException(status_code=409, detail="生产产出无效")
        totals[output["id"]] += line["quantity_base"]
        changes.append(StockChange(
            warehouse_id=line["target_warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=Decimal(line["quantity_base"]),
            source_type="production_receipt", source_id=receipt_id,
            source_line_id=line["id"], movement_kind="production_receipt_in",
        ))
    if set(totals) != set(outputs):
        raise HTTPException(status_code=409, detail="入库单缺少生产订单的产出项")
    if any(totals[output_id] > output["planned_quantity_base"]
           for output_id, output in outputs.items()):
        raise HTTPException(status_code=409, detail="入库数量超过计划产出")
    short = any(totals[output_id] < output["planned_quantity_base"]
                for output_id, output in outputs.items())
    if short and not (receipt["remark"] or "").strip():
        raise HTTPException(status_code=409, detail="产出不足计划时必须填写备注")
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    db.execute(text("""
        UPDATE production_receipts SET status = 'posted', posted_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": receipt_id, "org": org})
    db.execute(text("""
        UPDATE production_orders SET status = 'completed'
        WHERE id = :id AND organization_id = :org
    """), {"id": order["id"], "org": org})
    _audit(db, org, actor, "production_receipt.post",
           "production_receipt", receipt_id)
    result = documents.get_receipt(db, org, receipt_id)
    db.commit()
    assert result is not None
    return result


def reverse_receipt(db: Session, org: UUID, actor: UUID,
                    receipt_id: UUID, reason: str) -> dict:
    reference = documents.get_receipt(db, org, receipt_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="生产入库单不存在")
    order = orders.get_order(db, org, reference["production_order_id"], lock=True)
    receipt = documents.get_receipt(db, org, receipt_id, lock=True)
    assert order is not None and receipt is not None
    if receipt["status"] == "reversed":
        return receipt
    if receipt["status"] != "posted":
        raise HTTPException(status_code=409, detail="只有已过账的生产入库单可以冲销")
    if order["status"] != "completed":
        raise HTTPException(status_code=409, detail="生产订单不在完工状态，入库单无法冲销")
    changes = []
    for line in receipt["lines"]:
        original_id = db.execute(text("""
            SELECT id FROM stock_movements
            WHERE organization_id = :org AND source_type = 'production_receipt'
              AND source_id = :doc_id AND source_line_id = :line_id
        """), {"org": org, "doc_id": receipt_id,
               "line_id": line["id"]}).scalar_one()
        changes.append(StockChange(
            warehouse_id=line["target_warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=-Decimal(line["quantity_base"]),
            source_type="production_receipt_reversal", source_id=receipt_id,
            source_line_id=line["id"], movement_kind="production_receipt_reverse_out",
            reversal_of_id=original_id))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    db.execute(text("""
        UPDATE production_receipts SET status = 'reversed'
        WHERE id = :id AND organization_id = :org
    """), {"id": receipt_id, "org": org})
    db.execute(text("""
        UPDATE production_orders SET status = 'open'
        WHERE id = :id AND organization_id = :org
    """), {"id": order["id"], "org": org})
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, 'production_receipt.reverse',
                'production_receipt', :id, :reason)
    """), {"org": org, "actor": actor, "id": receipt_id,
           "reason": reason.strip()})
    result = documents.get_receipt(db, org, receipt_id)
    db.commit()
    assert result is not None
    return result
