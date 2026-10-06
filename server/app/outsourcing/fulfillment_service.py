"""Outsourced material issues and partial output receipts."""

from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.inventory.posting import StockChange, post_stock_changes
from app.inventory.quantities import quantity_snapshot
from app.outsourcing import repository, service
from app.core.document_numbers import next_document_number
from app.outsourcing.fulfillment_repository import TABLES, get_document

# 自动单号前缀与计数表：发料 WWFL、入库 WWRK（与委外单 WW 同一套流水规则）。
PREFIXES = {"issue": "WWFL", "receipt": "WWRK"}
COUNTERS = {"issue": "outsourcing_issue_number_counters",
            "receipt": "outsourcing_receipt_number_counters"}
from app.outsourcing.fulfillment_schemas import IssueWrite, ReceiptWrite

Write = IssueWrite | ReceiptWrite
CENT = Decimal("0.01")


def _required(db: Session, org: UUID, kind: str, doc_id: UUID,
              *, lock: bool = False) -> dict:
    result = get_document(db, org, kind, doc_id, lock=lock)
    if result is None:
        raise HTTPException(status_code=404, detail=f"outsourcing {kind} not found")
    return result


def _snapshots(db: Session, org: UUID, kind: str,
               data: Write) -> list[tuple[Decimal, Decimal, Decimal]]:
    order = repository.get_order(db, org, data.outsourcing_order_id)
    if order is None or order["status"] != "open":
        raise HTTPException(status_code=409, detail="委外单不是进行中状态")
    warehouse = db.execute(text("""
        SELECT is_active FROM warehouses WHERE id = :id AND organization_id = :org
    """), {"id": data.warehouse_id, "org": org}).scalar_one_or_none()
    if not warehouse:
        raise HTTPException(status_code=422, detail="仓库不可用")
    sources = {line["id"]: line for line in (
        order["materials"] if kind == "issue" else order["outputs"])}
    source_attr = "outsourcing_material_line_id" if kind == "issue" else "outsourcing_output_line_id"
    ids = [getattr(line, source_attr) for line in data.lines]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="委外来源明细重复")
    result = []
    for line in data.lines:
        source = sources.get(getattr(line, source_attr))
        if source is None or source["item_id"] != line.item_id:
            raise HTTPException(status_code=422, detail="委外来源明细无效")
        if kind == "issue" and source["supply_party"] != "self":
            raise HTTPException(status_code=422, detail="加工商包料的物料不能由我方发料")
        factor, base = quantity_snapshot(db, org, line.item_id, line.unit_id,
                                         line.quantity)
        result.append((factor, base,
                       source["unit_price"] if kind == "receipt" else Decimal("0")))
    return result


def _write_lines(db: Session, kind: str, doc_id: UUID,
                 data: Write, snapshots: list[tuple[Decimal, Decimal, Decimal]]) -> None:
    if kind == "issue":
        for index, (line, (factor, base, _)) in enumerate(zip(data.lines, snapshots, strict=True)):
            db.execute(text("""
                INSERT INTO outsourcing_issue_lines (
                    issue_id, outsourcing_material_line_id, item_id, quantity,
                    unit_id, conversion_factor, quantity_base, sort_order
                ) VALUES (:doc, :source, :item, :quantity, :unit, :factor, :base, :sort_order)
            """), {"doc": doc_id, "source": line.outsourcing_material_line_id,
                   "item": line.item_id, "quantity": line.quantity,
                   "unit": line.unit_id, "factor": factor, "base": base,
                   "sort_order": index})
    else:
        for index, (line, (factor, base, price)) in enumerate(zip(data.lines, snapshots, strict=True)):
            db.execute(text("""
                INSERT INTO outsourcing_receipt_lines (
                    receipt_id, outsourcing_output_line_id, item_id, quantity,
                    unit_id, conversion_factor, quantity_base, unit_price, amount, sort_order
                ) VALUES (:doc, :source, :item, :quantity, :unit, :factor,
                          :base, :price, 0, :sort_order)
            """), {"doc": doc_id, "source": line.outsourcing_output_line_id,
                   "item": line.item_id, "quantity": line.quantity,
                   "unit": line.unit_id, "factor": factor, "base": base,
                   "price": price, "sort_order": index})


def create_document(db: Session, org: UUID, actor: UUID,
                    kind: str, data: Write) -> dict:
    snapshots = _snapshots(db, org, kind, data)
    table = TABLES[kind][0]
    try:
        # 同组织内串行取号，避免并发下生成重复单号（与销售/采购/调拨同一套）。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix=PREFIXES[kind], table=table,
            counter=COUNTERS[kind])
        doc_id = db.execute(text(f"""
            INSERT INTO {table} (organization_id, document_no,
                outsourcing_order_id, warehouse_id, document_date, remark, created_by)
            VALUES (:org, :number, :order_id, :warehouse, :date, :remark, :actor)
            RETURNING id
        """), {"org": org, "number": document_no,
               "order_id": data.outsourcing_order_id,
               "warehouse": data.warehouse_id,
               "date": data.document_date, "remark": data.remark,
               "actor": actor}).scalar_one()
        _write_lines(db, kind, doc_id, data, snapshots)
        service.audit(db, org, actor, f"outsourcing_{kind}.create",
                      f"outsourcing_{kind}", doc_id)
        result = _required(db, org, kind, doc_id)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"outsourcing {kind} number already exists") from exc


def update_document(db: Session, org: UUID, actor: UUID,
                    kind: str, doc_id: UUID, data: Write) -> dict:
    doc = _required(db, org, kind, doc_id, lock=True)
    if doc["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的单据可以修改")
    if data.outsourcing_order_id != doc["outsourcing_order_id"]:
        raise HTTPException(status_code=422, detail="委外单不能变更")
    snapshots = _snapshots(db, org, kind, data)
    table, lines, fk = TABLES[kind]
    try:
        db.execute(text(f"""
            UPDATE {table} SET document_no = :number, warehouse_id = :warehouse,
                document_date = :date, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"id": doc_id, "org": org,
               # 编辑时留空保留原单号，不会被清掉。
               "number": (data.document_no or doc["document_no"]).strip(),
               "warehouse": data.warehouse_id, "date": data.document_date,
               "remark": data.remark})
        db.execute(text(f"DELETE FROM {lines} WHERE {fk} = :id"), {"id": doc_id})
        _write_lines(db, kind, doc_id, data, snapshots)
        service.audit(db, org, actor, f"outsourcing_{kind}.update",
                      f"outsourcing_{kind}", doc_id)
        result = _required(db, org, kind, doc_id)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"outsourcing {kind} number already exists") from exc


def delete_document(db: Session, org: UUID, actor: UUID,
                    kind: str, doc_id: UUID) -> None:
    doc = _required(db, org, kind, doc_id, lock=True)
    if doc["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的单据可以删除")
    table = TABLES[kind][0]
    db.execute(text(f"DELETE FROM {table} WHERE id = :id AND organization_id = :org"),
               {"id": doc_id, "org": org})
    service.audit(db, org, actor, f"outsourcing_{kind}.delete",
                  f"outsourcing_{kind}", doc_id)
    db.commit()


def post_document(db: Session, org: UUID, actor: UUID,
                  kind: str, doc_id: UUID) -> dict:
    reference = _required(db, org, kind, doc_id)
    order = repository.get_order(db, org, reference["outsourcing_order_id"], lock=True)
    doc = _required(db, org, kind, doc_id, lock=True)
    assert order is not None
    if doc["status"] == "posted":
        return doc
    if doc["status"] != "draft" or order["status"] != "open":
        raise HTTPException(status_code=409, detail="委外单据不能过账")
    sources = {line["id"]: line for line in (
        order["materials"] if kind == "issue" else order["outputs"])}
    source_key = "outsourcing_material_line_id" if kind == "issue" else "outsourcing_output_line_id"
    changes = []
    amount_entries = []
    for line in doc["lines"]:
        source = sources.get(line[source_key])
        if source is None or source["item_id"] != line["item_id"]:
            raise HTTPException(status_code=409, detail="委外来源明细已变更")
        if kind == "issue" and source["supply_party"] != "self":
            raise HTTPException(status_code=409, detail="加工商包料的物料不能由我方发料")
        if line["quantity_base"] > source["remaining_quantity_base"]:
            raise HTTPException(status_code=409, detail="委外数量超过剩余可执行数量")
        changes.append(StockChange(
            warehouse_id=doc["warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=line["quantity_base"] * (-1 if kind == "issue" else 1),
            source_type=f"outsourcing_{kind}", source_id=doc_id,
            source_line_id=line["id"],
            movement_kind=f"outsourcing_{kind}_{'out' if kind == 'issue' else 'in'}"))
        if kind == "receipt":
            previous = source["received_quantity_base"]
            price = source["unit_price"]
            amount = ((previous + line["quantity_base"]) * price).quantize(
                CENT, rounding=ROUND_HALF_UP) - (previous * price).quantize(
                    CENT, rounding=ROUND_HALF_UP)
            if amount >= Decimal("10000000000000000"):
                raise HTTPException(status_code=422, detail="入库金额过大")
            amount_entries.append((line["id"], amount))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    if kind == "receipt":
        for line_id, amount in amount_entries:
            db.execute(text("""
                UPDATE outsourcing_receipt_lines SET amount = :amount WHERE id = :id
            """), {"amount": amount, "id": line_id})
            if amount:
                db.execute(text("""
                    INSERT INTO business_amount_entries (
                        organization_id, party_id, direction, amount_delta,
                        source_type, source_id, source_line_id
                    ) VALUES (:org, :party, 'payable', :amount,
                              'outsourcing_receipt', :doc, :line)
                """), {"org": org, "party": order["processor_id"],
                       "amount": amount, "doc": doc_id, "line": line_id})
    table = TABLES[kind][0]
    db.execute(text(f"""
        UPDATE {table} SET status = 'posted', posted_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": doc_id, "org": org})
    service.audit(db, org, actor, f"outsourcing_{kind}.post",
                  f"outsourcing_{kind}", doc_id)
    result = _required(db, org, kind, doc_id)
    db.commit()
    return result


def reverse_document(db: Session, org: UUID, actor: UUID,
                     kind: str, doc_id: UUID, reason: str) -> dict:
    reference = _required(db, org, kind, doc_id)
    order = repository.get_order(db, org, reference["outsourcing_order_id"], lock=True)
    doc = _required(db, org, kind, doc_id, lock=True)
    assert order is not None
    if doc["status"] == "reversed":
        return doc
    if doc["status"] != "posted":
        raise HTTPException(status_code=409, detail="只有已过账的单据可以冲销")
    if kind == "issue":
        downstream = db.execute(text("""
            SELECT 1 FROM outsourcing_receipts
            WHERE outsourcing_order_id = :order_id AND status = 'posted'
            LIMIT 1
        """), {"order_id": order["id"]}).scalar_one_or_none()
        if downstream:
            raise HTTPException(status_code=409, detail="请先冲销已过账的委外入库单")
    changes = []
    for line in doc["lines"]:
        original_movement = db.execute(text("""
            SELECT id FROM stock_movements
            WHERE organization_id = :org AND source_type = :source_type
              AND source_id = :doc_id AND source_line_id = :line_id
        """), {"org": org, "source_type": f"outsourcing_{kind}",
               "doc_id": doc_id, "line_id": line["id"]}).scalar_one()
        changes.append(StockChange(
            warehouse_id=doc["warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=line["quantity_base"] * (1 if kind == "issue" else -1),
            source_type=f"outsourcing_{kind}_reversal", source_id=doc_id,
            source_line_id=line["id"], movement_kind=f"outsourcing_{kind}_reverse",
            reversal_of_id=original_movement))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    if kind == "receipt":
        for line in doc["lines"]:
            if not line["amount"]:
                continue
            original_entry = db.execute(text("""
                SELECT id FROM business_amount_entries
                WHERE organization_id = :org AND source_type = 'outsourcing_receipt'
                  AND source_id = :doc_id AND source_line_id = :line_id
            """), {"org": org, "doc_id": doc_id,
                   "line_id": line["id"]}).scalar_one()
            db.execute(text("""
                INSERT INTO business_amount_entries (
                    organization_id, party_id, direction, amount_delta,
                    source_type, source_id, source_line_id, reversal_of_id
                ) VALUES (:org, :party, 'payable', :amount,
                          'outsourcing_receipt_reversal', :doc_id, :line_id,
                          :original_id)
            """), {"org": org, "party": order["processor_id"],
                   "amount": -line["amount"], "doc_id": doc_id,
                   "line_id": line["id"], "original_id": original_entry})
    table = TABLES[kind][0]
    db.execute(text(f"""
        UPDATE {table} SET status = 'reversed'
        WHERE id = :id AND organization_id = :org
    """), {"id": doc_id, "org": org})
    service.audit(db, org, actor, f"outsourcing_{kind}.reverse",
                  f"outsourcing_{kind}", doc_id, reason.strip())
    result = _required(db, org, kind, doc_id)
    db.commit()
    return result
