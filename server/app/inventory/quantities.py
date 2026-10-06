"""Resolve a document's quantity and conversion snapshot in base units."""

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


def quantity_snapshot(
    db: Session, organization_id: UUID, item_id: UUID, unit_id: UUID, quantity: Decimal
) -> tuple[Decimal, Decimal]:
    row = db.execute(
        text("""
            SELECT i.base_unit_id, i.is_active AS item_active,
                   u.is_active AS unit_active, u.precision_scale,
                   base_u.precision_scale AS base_precision_scale
            FROM items i JOIN units u ON u.id = :unit_id AND u.organization_id = i.organization_id
            JOIN units base_u ON base_u.id = i.base_unit_id
            WHERE i.id = :item_id AND i.organization_id = :organization_id
        """),
        {"organization_id": organization_id, "item_id": item_id, "unit_id": unit_id},
    ).mappings().first()
    if row is None or not row["item_active"] or not row["unit_active"]:
        raise HTTPException(status_code=422, detail="物料或计量单位不可用")
    if max(0, -quantity.normalize().as_tuple().exponent) > row["precision_scale"]:
        raise HTTPException(status_code=422, detail="数量超出计量单位的小数位数")

    if unit_id == row["base_unit_id"]:
        factor = Decimal("1")
    else:
        # 换算走全局单位层级：业务单位必须直接挂在物料的基本单位下（1 业务单位 = base_quantity 个基本单位）。
        # 层级最多两层（见 catalog.service._validate_base_unit），所以这里一步就能定位，不需要逐级上溯。
        factor = db.execute(
            text("""
                SELECT base_quantity FROM units
                WHERE id = :unit_id AND organization_id = :organization_id
                  AND base_unit_id = :item_base_unit_id
            """),
            {"unit_id": unit_id, "organization_id": organization_id,
             "item_base_unit_id": row["base_unit_id"]},
        ).scalar_one_or_none()
        if factor is None:
            raise HTTPException(
                status_code=422,
                detail="该单位既不是物料的基本单位，也没有挂在物料的基本单位之下")
    quantity_base = quantity * factor
    if quantity_base != quantity_base.quantize(Decimal("0.000001")):
        raise HTTPException(status_code=422, detail="换算后的基本数量超过六位小数")
    if max(0, -quantity_base.normalize().as_tuple().exponent) > row["base_precision_scale"]:
        raise HTTPException(status_code=422, detail="换算后的基本数量超出基本单位的小数位数")
    return factor, quantity_base
