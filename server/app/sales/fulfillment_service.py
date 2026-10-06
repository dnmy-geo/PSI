from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.document_numbers import next_document_number
from app.inventory.posting import StockChange, post_stock_changes
from app.inventory.quantities import quantity_snapshot
from app.sales import fulfillment_repository as repository
from app.sales import repository as order_repository
from app.sales.fulfillment_schemas import ReturnWrite, ShipmentWrite


def _audit(db: Session, org: UUID, actor: UUID, action: str,
           document_type: str, document_id: UUID) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id)
        VALUES (:org, :actor, :action, :document_type, :id)
    """), {"org": org, "actor": actor, "action": action,
           "document_type": document_type, "id": document_id})


def _warehouse_active(db: Session, org: UUID, warehouse_id: UUID) -> None:
    active = db.execute(text("""
        SELECT is_active FROM warehouses WHERE id = :id AND organization_id = :org
    """), {"id": warehouse_id, "org": org}).scalar_one_or_none()
    if not active:
        raise HTTPException(status_code=422, detail="仓库不可用")


def _order_line(db: Session, order_id: UUID, line_id: UUID) -> dict:
    row = db.execute(text("""
        SELECT id, item_id, quantity_base, conversion_factor, unit_price, amount
        FROM sales_order_lines WHERE id = :id AND sales_order_id = :order_id
    """), {"id": line_id, "order_id": order_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=422, detail="订单明细不属于该订单")
    return dict(row)


def _replacement_source(db: Session, org: UUID, return_line_id: UUID,
                        order_line_id: UUID, item_id: UUID) -> dict:
    row = db.execute(text("""
        SELECT rl.id, rl.quantity_base
        FROM sales_return_lines rl
        JOIN sales_returns r ON r.id = rl.sales_return_id
        JOIN sales_shipment_lines sl ON sl.id = rl.sales_shipment_line_id
        WHERE rl.id = :id AND r.organization_id = :org AND r.status = 'posted'
          AND sl.sales_order_line_id = :order_line_id AND rl.item_id = :item_id
    """), {"id": return_line_id, "org": org,
           "order_line_id": order_line_id, "item_id": item_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=422, detail="补发对应的退货明细不可用")
    return dict(row)


def _shipment_snapshots(db: Session, org: UUID, data: ShipmentWrite) -> list[tuple[Decimal, Decimal]]:
    order = order_repository.get_order(db, org, data.sales_order_id)
    if order is None or order["status"] != "approved":
        raise HTTPException(status_code=409, detail="销售订单未审批或已关闭")
    _warehouse_active(db, org, data.warehouse_id)
    if len({line.sales_order_line_id for line in data.lines}) != len(data.lines):
        raise HTTPException(status_code=422, detail="订单明细重复")
    result = []
    for line in data.lines:
        order_line = _order_line(db, data.sales_order_id, line.sales_order_line_id)
        if order_line["item_id"] != line.item_id:
            raise HTTPException(status_code=422, detail="出库物料与订单行不一致")
        if data.shipment_type == "replacement":
            if line.replacement_return_line_id is None:
                raise HTTPException(status_code=422, detail="补发必须关联退货明细")
            _replacement_source(db, org, line.replacement_return_line_id,
                                line.sales_order_line_id, line.item_id)
        elif line.replacement_return_line_id is not None:
            raise HTTPException(status_code=422, detail="普通出库不能关联退货明细")
        result.append(quantity_snapshot(db, org, line.item_id, line.unit_id, line.quantity))
    return result


def _write_shipment_lines(db: Session, shipment_id: UUID, data: ShipmentWrite,
                          snapshots: list[tuple[Decimal, Decimal]]) -> None:
    for index, (line, (factor, quantity_base)) in enumerate(zip(data.lines, snapshots, strict=True)):
        db.execute(text("""
            INSERT INTO sales_shipment_lines (
                shipment_id, sales_order_line_id, item_id, quantity, unit_id,
                conversion_factor, quantity_base, replacement_return_line_id, sort_order
            ) VALUES (:shipment_id, :order_line_id, :item_id, :quantity, :unit_id,
                      :factor, :quantity_base, :return_line_id, :sort_order)
        """), {"shipment_id": shipment_id, "order_line_id": line.sales_order_line_id,
               "sort_order": index,
               "item_id": line.item_id, "quantity": line.quantity,
               "unit_id": line.unit_id, "factor": factor,
               "quantity_base": quantity_base,
               "return_line_id": line.replacement_return_line_id})



def create_shipment(db: Session, org: UUID, actor: UUID, data: ShipmentWrite) -> dict:
    snapshots = _shipment_snapshots(db, org, data)
    try:
        # 同组织内串行取号，避免并发下生成重复单号。
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="XC", table="sales_shipments",
            counter="sales_shipment_number_counters")
        shipment_id = db.execute(text("""
            INSERT INTO sales_shipments (
                organization_id, document_no, sales_order_id, warehouse_id,
                document_date, shipment_type, remark, created_by
            ) VALUES (:org, :document_no, :order_id, :warehouse_id,
                      :document_date, :shipment_type, :remark, :actor) RETURNING id
        """), {"org": org, "document_no": document_no,
               "order_id": data.sales_order_id, "warehouse_id": data.warehouse_id,
               "document_date": data.document_date, "shipment_type": data.shipment_type,
               "remark": data.remark, "actor": actor}).scalar_one()
        _write_shipment_lines(db, shipment_id, data, snapshots)
        _audit(db, org, actor, "sales_shipment.create", "sales_shipment", shipment_id)
        result = repository.get_shipment(db, org, shipment_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="出库单号已存在") from exc


def update_shipment(db: Session, org: UUID, actor: UUID, shipment_id: UUID,
                    data: ShipmentWrite) -> dict:
    current = repository.get_shipment(db, org, shipment_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="出库单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的出库单可以修改")
    snapshots = _shipment_snapshots(db, org, data)
    try:
        db.execute(text("""
            UPDATE sales_shipments SET document_no = :document_no,
                sales_order_id = :order_id, warehouse_id = :warehouse_id,
                document_date = :document_date, shipment_type = :shipment_type,
                remark = :remark WHERE id = :id AND organization_id = :org
        """), {"id": shipment_id, "org": org,
               "document_no": (data.document_no or current["document_no"]).strip(),
               "order_id": data.sales_order_id, "warehouse_id": data.warehouse_id,
               "document_date": data.document_date,
               "shipment_type": data.shipment_type, "remark": data.remark})
        db.execute(text("DELETE FROM sales_shipment_lines WHERE shipment_id = :id"),
                   {"id": shipment_id})
        _write_shipment_lines(db, shipment_id, data, snapshots)
        _audit(db, org, actor, "sales_shipment.update", "sales_shipment", shipment_id)
        result = repository.get_shipment(db, org, shipment_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="出库单号已存在") from exc


def delete_shipment(db: Session, org: UUID, actor: UUID, shipment_id: UUID) -> None:
    current = repository.get_shipment(db, org, shipment_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="出库单不存在")
    if current["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有草稿状态的出库单可以删除")
    db.execute(text("DELETE FROM sales_shipments WHERE id = :id AND organization_id = :org"),
               {"id": shipment_id, "org": org})
    _audit(db, org, actor, "sales_shipment.delete", "sales_shipment", shipment_id)
    db.commit()


def _normal_amount(db: Session, order_line: dict, order_line_id: UUID,
                   quantity_base: Decimal) -> Decimal:
    gross_shipped = db.execute(text("""
        SELECT COALESCE(sum(sl.quantity_base), 0)
        FROM sales_shipment_lines sl JOIN sales_shipments s ON s.id = sl.shipment_id
        WHERE sl.sales_order_line_id = :id AND s.status = 'posted'
          AND s.shipment_type = 'normal'
    """), {"id": order_line_id}).scalar_one()
    if gross_shipped + quantity_base > order_line["quantity_base"]:
        raise HTTPException(status_code=409, detail="出库数量超过订单数量")
    prior_amount = db.execute(text("""
        SELECT COALESCE(sum(e.amount_delta), 0)
        FROM business_amount_entries e
        JOIN sales_shipment_lines sl ON sl.id = e.source_line_id
        JOIN sales_shipments s ON s.id = sl.shipment_id
        WHERE sl.sales_order_line_id = :id AND s.status = 'posted'
          AND s.shipment_type = 'normal'
          AND e.source_type = 'sales_shipment' AND e.direction = 'receivable'
    """), {"id": order_line_id}).scalar_one()
    target = ((gross_shipped + quantity_base) / order_line["conversion_factor"]
              * order_line["unit_price"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if gross_shipped + quantity_base == order_line["quantity_base"]:
        target = order_line["amount"]
    amount_delta = target - prior_amount
    if amount_delta < 0:
        raise HTTPException(status_code=409, detail="出库金额会变成负数")
    return amount_delta


def _replacement_capacity(db: Session, return_line_id: UUID,
                          return_quantity_base: Decimal) -> Decimal:
    replaced = db.execute(text("""
        SELECT COALESCE(sum(sl.quantity_base), 0)
        FROM sales_shipment_lines sl JOIN sales_shipments s ON s.id = sl.shipment_id
        WHERE sl.replacement_return_line_id = :id AND s.status = 'posted'
          AND s.shipment_type = 'replacement'
    """), {"id": return_line_id}).scalar_one()
    return return_quantity_base - replaced


def post_shipment(db: Session, org: UUID, actor: UUID, shipment_id: UUID) -> dict:
    reference = repository.get_shipment(db, org, shipment_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="出库单不存在")
    order = order_repository.get_order(db, org, reference["sales_order_id"], lock=True)
    shipment = repository.get_shipment(db, org, shipment_id, lock=True)
    assert order is not None and shipment is not None
    if shipment["status"] == "posted":
        return shipment
    if shipment["status"] != "draft" or order["status"] != "approved":
        raise HTTPException(status_code=409, detail="出库单不能过账")
    _warehouse_active(db, org, shipment["warehouse_id"])
    changes = []
    amount_lines: list[tuple[UUID, Decimal]] = []
    for line in shipment["lines"]:
        order_line = _order_line(db, order["id"], line["sales_order_line_id"])
        if order_line["item_id"] != line["item_id"]:
            raise HTTPException(status_code=409, detail="出库物料与订单不一致")
        if shipment["shipment_type"] == "normal":
            amount = _normal_amount(db, order_line, line["sales_order_line_id"],
                                    line["quantity_base"])
            if amount:
                amount_lines.append((line["id"], amount))
        else:
            return_line_id = line["replacement_return_line_id"]
            if return_line_id is None:
                raise HTTPException(status_code=409, detail="补发缺少退货明细")
            source = _replacement_source(db, org, return_line_id,
                                         line["sales_order_line_id"], line["item_id"])
            if line["quantity_base"] > _replacement_capacity(db, return_line_id,
                                                               source["quantity_base"]):
                raise HTTPException(status_code=409, detail="补发数量超过退货数量")
        changes.append(StockChange(
            warehouse_id=shipment["warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=-line["quantity_base"],
            source_type="sales_shipment", source_id=shipment_id,
            source_line_id=line["id"], movement_kind="sales_out",
        ))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    for line_id, amount in amount_lines:
        db.execute(text("""
            INSERT INTO business_amount_entries (
                organization_id, party_id, direction, amount_delta,
                source_type, source_id, source_line_id
            ) VALUES (:org, :customer_id, 'receivable', :amount,
                      'sales_shipment', :shipment_id, :line_id)
        """), {"org": org, "customer_id": order["customer_id"],
               "amount": amount, "shipment_id": shipment_id, "line_id": line_id})
    db.execute(text("""
        UPDATE sales_shipments SET status = 'posted', posted_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": shipment_id, "org": org})
    _audit(db, org, actor, "sales_shipment.post", "sales_shipment", shipment_id)
    result = repository.get_shipment(db, org, shipment_id)
    db.commit()
    assert result is not None
    return result


def _return_snapshots(db: Session, org: UUID, data: ReturnWrite) -> list[tuple[Decimal, Decimal]]:
    shipment = repository.get_shipment(db, org, data.original_shipment_id)
    if shipment is None or shipment["status"] != "posted":
        raise HTTPException(status_code=409, detail="原出库单未过账")
    _warehouse_active(db, org, data.target_warehouse_id)
    if len({line.sales_shipment_line_id for line in data.lines}) != len(data.lines):
        raise HTTPException(status_code=422, detail="出库明细重复")
    source_lines = {line["id"]: line for line in shipment["lines"]}
    result = []
    for line in data.lines:
        source = source_lines.get(line.sales_shipment_line_id)
        if source is None or source["item_id"] != line.item_id:
            raise HTTPException(status_code=422, detail="退货明细与原出库明细不一致")
        result.append(quantity_snapshot(db, org, line.item_id, line.unit_id, line.quantity))
    return result


def _write_return_lines(db: Session, return_id: UUID, data: ReturnWrite,
                        snapshots: list[tuple[Decimal, Decimal]]) -> None:
    for index, (line, (factor, quantity_base)) in enumerate(zip(data.lines, snapshots, strict=True)):
        db.execute(text("""
            INSERT INTO sales_return_lines (
                sales_return_id, sales_shipment_line_id, item_id, quantity,
                unit_id, conversion_factor, quantity_base, sort_order
            ) VALUES (:return_id, :shipment_line_id, :item_id, :quantity,
                      :unit_id, :factor, :quantity_base, :sort_order)
        """), {"return_id": return_id, "sort_order": index,
               "shipment_line_id": line.sales_shipment_line_id,
               "item_id": line.item_id, "quantity": line.quantity,
               "unit_id": line.unit_id, "factor": factor,
               "quantity_base": quantity_base})


def create_return(db: Session, org: UUID, actor: UUID, data: ReturnWrite) -> dict:
    snapshots = _return_snapshots(db, org, data)
    try:
        db.execute(text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"),
                   {"org": org}).scalar_one()
        document_no = data.document_no.strip() if data.document_no else next_document_number(
            db, org, data.document_date, prefix="XT", table="sales_returns",
            counter="sales_return_number_counters")
        return_id = db.execute(text("""
            INSERT INTO sales_returns (
                organization_id, document_no, original_shipment_id,
                target_warehouse_id, document_date, remark, created_by
            ) VALUES (:org, :document_no, :shipment_id,
                      :warehouse_id, :document_date, :remark, :actor) RETURNING id
        """), {"org": org, "document_no": document_no,
               "shipment_id": data.original_shipment_id,
               "warehouse_id": data.target_warehouse_id,
               "document_date": data.document_date, "remark": data.remark,
               "actor": actor}).scalar_one()
        _write_return_lines(db, return_id, data, snapshots)
        _audit(db, org, actor, "sales_return.create", "sales_return", return_id)
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
            UPDATE sales_returns SET document_no = :document_no,
                original_shipment_id = :shipment_id,
                target_warehouse_id = :warehouse_id,
                document_date = :document_date, remark = :remark
            WHERE id = :id AND organization_id = :org
        """), {"id": return_id, "org": org,
               "document_no": (data.document_no or current["document_no"]).strip(),
               "shipment_id": data.original_shipment_id,
               "warehouse_id": data.target_warehouse_id,
               "document_date": data.document_date, "remark": data.remark})
        db.execute(text("DELETE FROM sales_return_lines WHERE sales_return_id = :id"),
                   {"id": return_id})
        _write_return_lines(db, return_id, data, snapshots)
        _audit(db, org, actor, "sales_return.update", "sales_return", return_id)
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
    db.execute(text("DELETE FROM sales_returns WHERE id = :id AND organization_id = :org"),
               {"id": return_id, "org": org})
    _audit(db, org, actor, "sales_return.delete", "sales_return", return_id)
    db.commit()


def post_return(db: Session, org: UUID, actor: UUID, return_id: UUID) -> dict:
    reference = repository.get_return(db, org, return_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    original = repository.get_shipment(db, org, reference["original_shipment_id"])
    if original is None:
        raise HTTPException(status_code=409, detail="原出库单不可用")
    order = order_repository.get_order(db, org, original["sales_order_id"], lock=True)
    shipment = repository.get_shipment(db, org, original["id"], lock=True)
    sales_return = repository.get_return(db, org, return_id, lock=True)
    assert order is not None and shipment is not None and sales_return is not None
    if sales_return["status"] == "posted":
        return sales_return
    if sales_return["status"] != "draft" or shipment["status"] != "posted":
        raise HTTPException(status_code=409, detail="退货单不能过账")
    _warehouse_active(db, org, sales_return["target_warehouse_id"])
    source_lines = {line["id"]: line for line in shipment["lines"]}
    changes = []
    for line in sales_return["lines"]:
        source = source_lines.get(line["sales_shipment_line_id"])
        if source is None or source["item_id"] != line["item_id"]:
            raise HTTPException(status_code=409, detail="退货来源明细无效")
        returned = db.execute(text("""
            SELECT COALESCE(sum(rl.quantity_base), 0)
            FROM sales_return_lines rl JOIN sales_returns r ON r.id = rl.sales_return_id
            WHERE rl.sales_shipment_line_id = :line_id AND r.status = 'posted'
        """), {"line_id": source["id"]}).scalar_one()
        if returned + line["quantity_base"] > source["quantity_base"]:
            raise HTTPException(status_code=409, detail="退货数量超过已出库数量")
        changes.append(StockChange(
            warehouse_id=sales_return["target_warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=line["quantity_base"],
            source_type="sales_return", source_id=return_id,
            source_line_id=line["id"], movement_kind="sales_return_in",
        ))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    db.execute(text("""
        UPDATE sales_returns SET status = 'posted', posted_at = now()
        WHERE id = :id AND organization_id = :org
    """), {"id": return_id, "org": org})
    _audit(db, org, actor, "sales_return.post", "sales_return", return_id)
    result = repository.get_return(db, org, return_id)
    db.commit()
    assert result is not None
    return result


def _audit_reverse(db: Session, org: UUID, actor: UUID, action: str,
                   document_type: str, doc_id: UUID, reason: str) -> None:
    db.execute(text("""
        INSERT INTO audit_logs (organization_id, actor_id, action_code,
                                document_type, document_id, reason)
        VALUES (:org, :actor, :action, :type, :id, :reason)
    """), {"org": org, "actor": actor, "action": action,
           "type": document_type, "id": doc_id, "reason": reason.strip()})


def reverse_return(db: Session, org: UUID, actor: UUID,
                   return_id: UUID, reason: str) -> dict:
    reference = repository.get_return(db, org, return_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    source = repository.get_shipment(db, org, reference["original_shipment_id"])
    assert source is not None
    order = order_repository.get_order(db, org, source["sales_order_id"], lock=True)
    sales_return = repository.get_return(db, org, return_id, lock=True)
    assert order is not None and sales_return is not None
    if sales_return["status"] == "reversed":
        return sales_return
    if sales_return["status"] != "posted":
        raise HTTPException(status_code=409, detail="只有已过账的退货单可以冲销")
    replacement = db.execute(text("""
        SELECT 1 FROM sales_shipment_lines sl
        JOIN sales_shipments s ON s.id = sl.shipment_id
        JOIN sales_return_lines rl ON rl.id = sl.replacement_return_line_id
        WHERE rl.sales_return_id = :id AND s.status = 'posted'
        LIMIT 1
    """), {"id": return_id}).scalar_one_or_none()
    if replacement:
        raise HTTPException(status_code=409, detail="请先冲销补发出库单")
    changes = []
    for line in sales_return["lines"]:
        original_id = db.execute(text("""
            SELECT id FROM stock_movements
            WHERE organization_id = :org AND source_type = 'sales_return'
              AND source_id = :doc_id AND source_line_id = :line_id
        """), {"org": org, "doc_id": return_id,
               "line_id": line["id"]}).scalar_one()
        changes.append(StockChange(
            warehouse_id=sales_return["target_warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=-line["quantity_base"],
            source_type="sales_return_reversal", source_id=return_id,
            source_line_id=line["id"], movement_kind="sales_return_reverse_out",
            reversal_of_id=original_id))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    db.execute(text("""
        UPDATE sales_returns SET status = 'reversed'
        WHERE id = :id AND organization_id = :org
    """), {"id": return_id, "org": org})
    _audit_reverse(db, org, actor, "sales_return.reverse",
                   "sales_return", return_id, reason)
    result = repository.get_return(db, org, return_id)
    db.commit()
    assert result is not None
    return result


def reverse_shipment(db: Session, org: UUID, actor: UUID,
                     shipment_id: UUID, reason: str) -> dict:
    reference = repository.get_shipment(db, org, shipment_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="出库单不存在")
    order = order_repository.get_order(db, org, reference["sales_order_id"], lock=True)
    shipment = repository.get_shipment(db, org, shipment_id, lock=True)
    assert order is not None and shipment is not None
    if shipment["is_opening_reference"]:
        raise HTTPException(status_code=409, detail="期初历史来源单据不能冲销")
    if shipment["status"] == "reversed":
        return shipment
    if shipment["status"] != "posted":
        raise HTTPException(status_code=409, detail="只有已过账的出库单可以冲销")
    if shipment["shipment_type"] == "normal":
        child = db.execute(text("""
            SELECT 1 FROM sales_returns WHERE original_shipment_id = :id
              AND status = 'posted' LIMIT 1
        """), {"id": shipment_id}).scalar_one_or_none()
        if child:
            raise HTTPException(status_code=409, detail="请先冲销销售退货单")
    changes = []
    for line in shipment["lines"]:
        original_id = db.execute(text("""
            SELECT id FROM stock_movements
            WHERE organization_id = :org AND source_type = 'sales_shipment'
              AND source_id = :doc_id AND source_line_id = :line_id
        """), {"org": org, "doc_id": shipment_id,
               "line_id": line["id"]}).scalar_one()
        changes.append(StockChange(
            warehouse_id=shipment["warehouse_id"], item_id=line["item_id"],
            quantity_delta_base=line["quantity_base"],
            source_type="sales_shipment_reversal", source_id=shipment_id,
            source_line_id=line["id"], movement_kind="sales_shipment_reverse_in",
            reversal_of_id=original_id))
    post_stock_changes(db, organization_id=org, actor_id=actor, changes=changes)
    if shipment["shipment_type"] == "normal":
        for line in shipment["lines"]:
            original_entry = db.execute(text("""
                SELECT id, amount_delta FROM business_amount_entries
                WHERE organization_id = :org AND source_type = 'sales_shipment'
                  AND source_id = :doc_id AND source_line_id = :line_id
            """), {"org": org, "doc_id": shipment_id,
                   "line_id": line["id"]}).mappings().first()
            if original_entry is not None:
                db.execute(text("""
                    INSERT INTO business_amount_entries (
                        organization_id, party_id, direction, amount_delta,
                        source_type, source_id, source_line_id, reversal_of_id
                    ) VALUES (:org, :party, 'receivable', :amount,
                              'sales_shipment_reversal', :doc_id, :line_id,
                              :original_id)
                """), {"org": org, "party": order["customer_id"],
                       "amount": -original_entry["amount_delta"],
                       "doc_id": shipment_id, "line_id": line["id"],
                       "original_id": original_entry["id"]})
    db.execute(text("""
        UPDATE sales_shipments SET status = 'reversed'
        WHERE id = :id AND organization_id = :org
    """), {"id": shipment_id, "org": org})
    _audit_reverse(db, org, actor, "sales_shipment.reverse",
                   "sales_shipment", shipment_id, reason)
    result = repository.get_shipment(db, org, shipment_id)
    db.commit()
    assert result is not None
    return result
