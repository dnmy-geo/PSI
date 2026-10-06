from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.document_numbers import next_document_number
from app.inventory.posting import StockChange, post_stock_changes
from app.inventory.quantities import quantity_snapshot
from app.purchase import fulfillment_repository as repository
from app.purchase import repository as order_repository
from app.purchase.fulfillment_schemas import ReceiptWrite, ReturnWrite
from app.purchase.service import audit, order_line


def _warehouse_active(db: Session, org: UUID, warehouse_id: UUID) -> None:
    active = db.execute(text("""
        SELECT is_active FROM warehouses WHERE id = :id AND organization_id = :org
    """), {"id": warehouse_id, "org": org}).scalar_one_or_none()
    if not active:
        raise HTTPException(status_code=422, detail="仓库不可用")


def _receipt_snapshots(db: Session, org: UUID,
                       data: ReceiptWrite) -> list[tuple[Decimal, Decimal, Decimal, Decimal]]:
    order = order_repository.get_order(db, org, data.purchase_order_id)
    if order is None or order["status"] != "open":
        raise HTTPException(status_code=409, detail="采购订单不是进行中状态")
    _warehouse_active(db, org, data.warehouse_id)
    if len({line.purchase_order_line_id for line in data.lines}) != len(data.lines):
        raise HTTPException(status_code=422, detail="采购订单明细重复")
    snapshots = []
    for line in data.lines:
        source = order_line(db, data.purchase_order_id, line.purchase_order_line_id)
        if source["item_id"] != line.item_id:
            raise HTTPException(status_code=422, detail="入库物料与订单行不一致")
        factor, base = quantity_snapshot(db, org, line.item_id, line.unit_id, line.quantity)
        amount = (base / source["conversion_factor"] * source["unit_price"]).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount >= Decimal("10000000000000000"):
            raise HTTPException(status_code=422, detail="入库金额过大")
        snapshots.append((factor, base, source["unit_price"], amount))
    return snapshots


def _write_receipt_lines(db: Session, receipt_id: UUID, data: ReceiptWrite,
                         snapshots: list[tuple[Decimal, Decimal, Decimal, Decimal]]) -> None:
    for index, (line, (factor, base, price, amount)) in enumerate(zip(data.lines, snapshots, strict=True)):
        db.execute(text("""
            INSERT INTO purchase_receipt_lines (
                receipt_id, purchase_order_line_id, item_id, quantity, unit_id,
                conversion_factor, quantity_base, unit_price, amount, sort_order
            ) VALUES (:receipt_id, :order_line_id, :item_id, :quantity, :unit_id,
                      :factor, :base, :price, :amount, :sort_order)
        """), {"receipt_id": receipt_id, "sort_order": index,
               "order_line_id": line.purchase_order_line_id,
               "item_id": line.item_id, "quantity": line.quantity,
               "unit_id": line.unit_id, "factor": factor,
               "base": base, "price": price, "amount": amount})


def create_receipt(db: Session, org: UUID, actor: UUID, data: ReceiptWrite) -> dict:
    snapshots = _receipt_snapshots(db, org, data)
    try:
        # 同组织内串行取号，避免并发下生成重复单号。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="CR", table="purchase_receipts",
            counter="purchase_receipt_number_counters")
        receipt_id = db.execute(text("""
            INSERT INTO purchase_receipts (
                organization_id, document_no, purchase_order_id, warehouse_id,
                document_date, remark, created_by
            ) VALUES (:org, :document_no, :order_id, :warehouse_id,
                      :document_date, :remark, :actor) RETURNING id
        """), {"org": org, "document_no": document_no,
               "order_id": data.purchase_order_id,
               "warehouse_id": data.warehouse_id,
               "document_date": data.document_date,
               "remark": data.remark, "actor": actor}).scalar_one()
        _write_receipt_lines(db, receipt_id, data, snapshots)
        audit(db, org, actor, "purchase_receipt.create", "purchase_receipt", receipt_id)
        result = repository.get_receipt(db, org, receipt_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="入库单号已存在") from exc


def update_receipt(db: Session, org: UUID, actor: UUID, receipt_id: UUID,
                   data: ReceiptWrite) -> dict:
    current = repository.get_receipt(db, org, receipt_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="入库单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的入库单可以修改")
    snapshots = _receipt_snapshots(db, org, data)
    try:
        db.execute(text("""
            UPDATE purchase_receipts SET document_no = :document_no,
                purchase_order_id = :order_id, warehouse_id = :warehouse_id,
                document_date = :document_date, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"id": receipt_id, "org": org,
               "document_no": (data.document_no or current["document_no"]).strip(),
               "order_id": data.purchase_order_id,
               "warehouse_id": data.warehouse_id,
               "document_date": data.document_date,
               "remark": data.remark})
        db.execute(text("DELETE FROM purchase_receipt_lines WHERE receipt_id = :id"),
                   {"id": receipt_id})
        _write_receipt_lines(db, receipt_id, data, snapshots)
        audit(db, org, actor, "purchase_receipt.update", "purchase_receipt", receipt_id)
        result = repository.get_receipt(db, org, receipt_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="入库单号已存在") from exc


def delete_receipt(db: Session, org: UUID, actor: UUID, receipt_id: UUID) -> None:
    current = repository.get_receipt(db, org, receipt_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="入库单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的入库单可以删除")
    db.execute(text("DELETE FROM purchase_receipts WHERE id = :id AND organization_id = :org"),
               {"id": receipt_id, "org": org})
    audit(db, org, actor, "purchase_receipt.delete", "purchase_receipt", receipt_id)
    db.commit()


def _receipt_amount(db: Session, order_line_data: dict, order_line_id: UUID,
                    quantity_base: Decimal) -> Decimal:
    gross = db.execute(text("""
        SELECT COALESCE(sum(rl.quantity_base), 0)
        FROM purchase_receipt_lines rl JOIN purchase_receipts r ON r.id = rl.receipt_id
        WHERE rl.purchase_order_line_id = :id AND r.status = 'posted'
    """), {"id": order_line_id}).scalar_one()
    returned = db.execute(text("""
        SELECT COALESCE(sum(prl.quantity_base), 0)
        FROM purchase_return_lines prl JOIN purchase_returns pr ON pr.id = prl.purchase_return_id
        JOIN purchase_receipt_lines rl ON rl.id = prl.purchase_receipt_line_id
        WHERE rl.purchase_order_line_id = :id AND pr.status = 'posted'
    """), {"id": order_line_id}).scalar_one()
    if gross - returned + quantity_base > order_line_data["quantity_base"]:
        raise HTTPException(status_code=409, detail="入库数量超过订单未入库数量")
    prior_amount = db.execute(text("""
        SELECT COALESCE(sum(rl.amount), 0)
        FROM purchase_receipt_lines rl JOIN purchase_receipts r ON r.id = rl.receipt_id
        WHERE rl.purchase_order_line_id = :id AND r.status = 'posted'
    """), {"id": order_line_id}).scalar_one()
    target = ((gross + quantity_base) / order_line_data["conversion_factor"]
              * order_line_data["unit_price"]).quantize(Decimal("0.01"),
                                                       rounding=ROUND_HALF_UP)
    if gross + quantity_base == order_line_data["quantity_base"]:
        target = order_line_data["amount"]
    amount = target - prior_amount
    if amount < 0 or amount >= Decimal("10000000000000000"):
        raise HTTPException(status_code=409, detail="入库金额无效")
    return amount


def post_receipt(db: Session, org: UUID, actor: UUID, receipt_id: UUID) -> dict:
    reference = repository.get_receipt(db, org, receipt_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="入库单不存在")
    order = order_repository.get_order(db, org, reference["purchase_order_id"], lock=True)
    receipt = repository.get_receipt(db, org, receipt_id, lock=True)
    assert order is not None and receipt is not None
    if receipt["status"] == "posted":
        return receipt
    if receipt["status"] != "draft" or order["status"] != "open":
        raise HTTPException(status_code=409, detail="入库单不能过账")
    _warehouse_active(db, org, receipt["warehouse_id"])
    changes = []
    amounts = []
    for line in receipt["lines"]:
        source = order_line(db, order["id"], line["purchase_order_line_id"])
        if source["item_id"] != line["item_id"]:
            raise HTTPException(status_code=409, detail="入库物料与订单不一致")
        amount = _receipt_amount(db, source, line["purchase_order_line_id"],
                                 line["quantity_base"])
        amounts.append((line["id"], amount))
        changes.append(StockChange(
            warehouse_id=receipt["warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=line["quantity_base"],
            source_type="purchase_receipt", source_id=receipt_id,
            source_line_id=line["id"], movement_kind="purchase_in",
        ))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    for line_id, amount in amounts:
        db.execute(text("UPDATE purchase_receipt_lines SET amount = :amount WHERE id = :id"),
                   {"id": line_id, "amount": amount})
        if amount:
            db.execute(text("""
                INSERT INTO business_amount_entries (
                    organization_id, party_id, direction, amount_delta,
                    source_type, source_id, source_line_id
                ) VALUES (:org, :supplier_id, 'payable', :amount,
                          'purchase_receipt', :receipt_id, :line_id)
            """), {"org": org, "supplier_id": order["supplier_id"],
                   "amount": amount, "receipt_id": receipt_id, "line_id": line_id})
    db.execute(text("""
        UPDATE purchase_receipts SET status = 'posted', posted_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": receipt_id, "org": org})
    audit(db, org, actor, "purchase_receipt.post", "purchase_receipt", receipt_id)
    result = repository.get_receipt(db, org, receipt_id)
    db.commit()
    assert result is not None
    return result


def _return_snapshots(db: Session, org: UUID,
                      data: ReturnWrite) -> list[tuple[Decimal, Decimal, Decimal]]:
    receipt = repository.get_receipt(db, org, data.original_receipt_id)
    if receipt is None or receipt["status"] != "posted":
        raise HTTPException(status_code=409, detail="原入库单未过账")
    _warehouse_active(db, org, data.warehouse_id)
    if len({line.purchase_receipt_line_id for line in data.lines}) != len(data.lines):
        raise HTTPException(status_code=422, detail="入库明细重复")
    source_lines = {line["id"]: line for line in receipt["lines"]}
    snapshots = []
    for line in data.lines:
        source = source_lines.get(line.purchase_receipt_line_id)
        if source is None or source["item_id"] != line.item_id:
            raise HTTPException(status_code=422, detail="退货明细与原入库明细不一致")
        factor, base = quantity_snapshot(db, org, line.item_id, line.unit_id, line.quantity)
        amount = (base / source["quantity_base"] * source["amount"]).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        snapshots.append((factor, base, amount))
    return snapshots


def _write_return_lines(db: Session, return_id: UUID, data: ReturnWrite,
                        snapshots: list[tuple[Decimal, Decimal, Decimal]]) -> None:
    for index, (line, (factor, base, amount)) in enumerate(zip(data.lines, snapshots, strict=True)):
        db.execute(text("""
            INSERT INTO purchase_return_lines (
                purchase_return_id, purchase_receipt_line_id, item_id,
                quantity, unit_id, conversion_factor, quantity_base, amount, sort_order
            ) VALUES (:return_id, :receipt_line_id, :item_id,
                      :quantity, :unit_id, :factor, :base, :amount, :sort_order)
        """), {"return_id": return_id, "sort_order": index,
               "receipt_line_id": line.purchase_receipt_line_id,
               "item_id": line.item_id, "quantity": line.quantity,
               "unit_id": line.unit_id, "factor": factor,
               "base": base, "amount": amount})


def create_return(db: Session, org: UUID, actor: UUID, data: ReturnWrite) -> dict:
    snapshots = _return_snapshots(db, org, data)
    try:
        # 同组织内串行取号，避免并发下生成重复单号。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="CT", table="purchase_returns",
            counter="purchase_return_number_counters")
        return_id = db.execute(text("""
            INSERT INTO purchase_returns (
                organization_id, document_no, original_receipt_id,
                warehouse_id, document_date, remark, created_by
            ) VALUES (:org, :document_no, :receipt_id,
                      :warehouse_id, :document_date, :remark, :actor) RETURNING id
        """), {"org": org, "document_no": document_no,
               "receipt_id": data.original_receipt_id,
               "warehouse_id": data.warehouse_id,
               "document_date": data.document_date,
               "remark": data.remark, "actor": actor}).scalar_one()
        _write_return_lines(db, return_id, data, snapshots)
        audit(db, org, actor, "purchase_return.create", "purchase_return", return_id)
        result = repository.get_return(db, org, return_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="退货单号已存在") from exc


def update_return(db: Session, org: UUID, actor: UUID, return_id: UUID,
                  data: ReturnWrite) -> dict:
    current = repository.get_return(db, org, return_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的退货单可以修改")
    snapshots = _return_snapshots(db, org, data)
    try:
        db.execute(text("""
            UPDATE purchase_returns SET document_no = :document_no,
                original_receipt_id = :receipt_id, warehouse_id = :warehouse_id,
                document_date = :document_date, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"id": return_id, "org": org,
               "document_no": (data.document_no or current["document_no"]).strip(),
               "receipt_id": data.original_receipt_id,
               "warehouse_id": data.warehouse_id,
               "document_date": data.document_date,
               "remark": data.remark})
        db.execute(text("DELETE FROM purchase_return_lines WHERE purchase_return_id = :id"),
                   {"id": return_id})
        _write_return_lines(db, return_id, data, snapshots)
        audit(db, org, actor, "purchase_return.update", "purchase_return", return_id)
        result = repository.get_return(db, org, return_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="退货单号已存在") from exc


def delete_return(db: Session, org: UUID, actor: UUID, return_id: UUID) -> None:
    current = repository.get_return(db, org, return_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的退货单可以删除")
    db.execute(text("DELETE FROM purchase_returns WHERE id = :id AND organization_id = :org"),
               {"id": return_id, "org": org})
    audit(db, org, actor, "purchase_return.delete", "purchase_return", return_id)
    db.commit()


def _return_amount(db: Session, source: dict, receipt_line_id: UUID,
                   quantity_base: Decimal) -> Decimal:
    returned = db.execute(text("""
        SELECT COALESCE(sum(prl.quantity_base), 0)
        FROM purchase_return_lines prl JOIN purchase_returns pr ON pr.id = prl.purchase_return_id
        WHERE prl.purchase_receipt_line_id = :id AND pr.status = 'posted'
    """), {"id": receipt_line_id}).scalar_one()
    if returned + quantity_base > source["quantity_base"]:
        raise HTTPException(status_code=409, detail="退货数量超过已入库数量")
    prior_amount = db.execute(text("""
        SELECT COALESCE(sum(prl.amount), 0)
        FROM purchase_return_lines prl JOIN purchase_returns pr ON pr.id = prl.purchase_return_id
        WHERE prl.purchase_receipt_line_id = :id AND pr.status = 'posted'
    """), {"id": receipt_line_id}).scalar_one()
    target = ((returned + quantity_base) / source["quantity_base"] * source["amount"]).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    if returned + quantity_base == source["quantity_base"]:
        target = source["amount"]
    amount = target - prior_amount
    if amount < 0:
        raise HTTPException(status_code=409, detail="退货金额无效")
    return amount


def post_return(db: Session, org: UUID, actor: UUID, return_id: UUID) -> dict:
    reference = repository.get_return(db, org, return_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    original = repository.get_receipt(db, org, reference["original_receipt_id"])
    if original is None:
        raise HTTPException(status_code=409, detail="原入库单不可用")
    order = order_repository.get_order(db, org, original["purchase_order_id"], lock=True)
    receipt = repository.get_receipt(db, org, original["id"], lock=True)
    purchase_return = repository.get_return(db, org, return_id, lock=True)
    assert order is not None and receipt is not None and purchase_return is not None
    if purchase_return["status"] == "posted":
        return purchase_return
    if purchase_return["status"] != "draft" or receipt["status"] != "posted":
        raise HTTPException(status_code=409, detail="退货单不能过账")
    _warehouse_active(db, org, purchase_return["warehouse_id"])
    source_lines = {line["id"]: line for line in receipt["lines"]}
    changes = []
    amounts = []
    for line in purchase_return["lines"]:
        source = source_lines.get(line["purchase_receipt_line_id"])
        if source is None or source["item_id"] != line["item_id"]:
            raise HTTPException(status_code=409, detail="退货来源明细无效")
        amount = _return_amount(db, source, source["id"], line["quantity_base"])
        amounts.append((line["id"], amount))
        changes.append(StockChange(
            warehouse_id=purchase_return["warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=-line["quantity_base"],
            source_type="purchase_return", source_id=return_id,
            source_line_id=line["id"], movement_kind="purchase_return_out",
        ))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    for line_id, amount in amounts:
        db.execute(text("UPDATE purchase_return_lines SET amount = :amount WHERE id = :id"),
                   {"id": line_id, "amount": amount})
        if amount:
            db.execute(text("""
                INSERT INTO business_amount_entries (
                    organization_id, party_id, direction, amount_delta,
                    source_type, source_id, source_line_id
                ) VALUES (:org, :supplier_id, 'payable', :amount,
                          'purchase_return', :return_id, :line_id)
            """), {"org": org, "supplier_id": order["supplier_id"],
                   "amount": -amount, "return_id": return_id, "line_id": line_id})
    db.execute(text("""
        UPDATE purchase_returns SET status = 'posted', posted_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": return_id, "org": org})
    audit(db, org, actor, "purchase_return.post", "purchase_return", return_id)
    result = repository.get_return(db, org, return_id)
    db.commit()
    assert result is not None
    return result


def _reverse_amount(db: Session, org: UUID, party_id: UUID,
                    source_type: str, doc_id: UUID, line_id: UUID) -> None:
    original = db.execute(text("""
        SELECT id, amount_delta FROM business_amount_entries
        WHERE organization_id = :org AND source_type = :source_type
          AND source_id = :doc_id AND source_line_id = :line_id
    """), {"org": org, "source_type": source_type,
           "doc_id": doc_id, "line_id": line_id}).mappings().first()
    if original is None:
        return
    db.execute(text("""
        INSERT INTO business_amount_entries (
            organization_id, party_id, direction, amount_delta,
            source_type, source_id, source_line_id, reversal_of_id
        ) VALUES (:org, :party, 'payable', :amount,
                  :source_type, :doc_id, :line_id, :original_id)
    """), {"org": org, "party": party_id,
           "amount": -original["amount_delta"],
           "source_type": source_type + "_reversal",
           "doc_id": doc_id, "line_id": line_id,
           "original_id": original["id"]})


def reverse_return(db: Session, org: UUID, actor: UUID,
                   return_id: UUID, reason: str) -> dict:
    reference = repository.get_return(db, org, return_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    original = repository.get_receipt(db, org, reference["original_receipt_id"])
    assert original is not None
    order = order_repository.get_order(db, org, original["purchase_order_id"], lock=True)
    purchase_return = repository.get_return(db, org, return_id, lock=True)
    assert order is not None and purchase_return is not None
    if purchase_return["status"] == "reversed":
        return purchase_return
    if purchase_return["status"] != "posted":
        raise HTTPException(status_code=409, detail="只有已过账的退货单可以冲销")
    source_lines = {line["id"]: line for line in original["lines"]}
    order_lines = {line["id"]: line for line in order["lines"]}
    changes = []
    for line in purchase_return["lines"]:
        source_line = source_lines[line["purchase_receipt_line_id"]]
        order_line_data = order_lines[source_line["purchase_order_line_id"]]
        if line["quantity_base"] > order_line_data["unreceived_quantity_base"]:
            raise HTTPException(status_code=409, detail="请先冲销之后的采购入库单")
        original_id = db.execute(text("""
            SELECT id FROM stock_movements
            WHERE organization_id = :org AND source_type = 'purchase_return'
              AND source_id = :doc_id AND source_line_id = :line_id
        """), {"org": org, "doc_id": return_id,
               "line_id": line["id"]}).scalar_one()
        changes.append(StockChange(
            warehouse_id=purchase_return["warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=line["quantity_base"],
            source_type="purchase_return_reversal", source_id=return_id,
            source_line_id=line["id"], movement_kind="purchase_return_reverse_in",
            reversal_of_id=original_id))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    for line in purchase_return["lines"]:
        _reverse_amount(db, org, order["supplier_id"],
                        "purchase_return", return_id, line["id"])
    db.execute(text("""
        UPDATE purchase_returns SET status = 'reversed'
        WHERE id = :id AND organization_id = :org
    """), {"id": return_id, "org": org})
    audit(db, org, actor, "purchase_return.reverse", "purchase_return",
          return_id, reason.strip())
    result = repository.get_return(db, org, return_id)
    db.commit()
    assert result is not None
    return result


def reverse_receipt(db: Session, org: UUID, actor: UUID,
                    receipt_id: UUID, reason: str) -> dict:
    reference = repository.get_receipt(db, org, receipt_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="入库单不存在")
    order = order_repository.get_order(db, org, reference["purchase_order_id"], lock=True)
    receipt = repository.get_receipt(db, org, receipt_id, lock=True)
    assert order is not None and receipt is not None
    if receipt["is_opening_reference"]:
        raise HTTPException(status_code=409, detail="期初历史来源单据不能冲销")
    if receipt["status"] == "reversed":
        return receipt
    if receipt["status"] != "posted":
        raise HTTPException(status_code=409, detail="只有已过账的入库单可以冲销")
    active_return = db.execute(text("""
        SELECT 1 FROM purchase_returns WHERE original_receipt_id = :id
          AND status = 'posted' LIMIT 1
    """), {"id": receipt_id}).scalar_one_or_none()
    if active_return:
        raise HTTPException(status_code=409, detail="请先冲销采购退货单")
    changes = []
    for line in receipt["lines"]:
        original_id = db.execute(text("""
            SELECT id FROM stock_movements
            WHERE organization_id = :org AND source_type = 'purchase_receipt'
              AND source_id = :doc_id AND source_line_id = :line_id
        """), {"org": org, "doc_id": receipt_id,
               "line_id": line["id"]}).scalar_one()
        changes.append(StockChange(
            warehouse_id=receipt["warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=-line["quantity_base"],
            source_type="purchase_receipt_reversal", source_id=receipt_id,
            source_line_id=line["id"], movement_kind="purchase_receipt_reverse_out",
            reversal_of_id=original_id))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    for line in receipt["lines"]:
        _reverse_amount(db, org, order["supplier_id"],
                        "purchase_receipt", receipt_id, line["id"])
    db.execute(text("""
        UPDATE purchase_receipts SET status = 'reversed'
        WHERE id = :id AND organization_id = :org
    """), {"id": receipt_id, "org": org})
    audit(db, org, actor, "purchase_receipt.reverse", "purchase_receipt",
          receipt_id, reason.strip())
    result = repository.get_receipt(db, org, receipt_id)
    db.commit()
    assert result is not None
    return result
