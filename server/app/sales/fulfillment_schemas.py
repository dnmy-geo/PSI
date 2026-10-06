from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ShipmentLineWrite(BaseModel):
    sales_order_line_id: UUID
    item_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    replacement_return_line_id: UUID | None = None


class ShipmentWrite(BaseModel):
    # 留空则由后端按 XC+日期+流水生成（与销售订单一致）。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    sales_order_id: UUID
    warehouse_id: UUID
    document_date: date
    shipment_type: Literal["normal", "replacement"]
    remark: str | None = None
    lines: list[ShipmentLineWrite] = Field(min_length=1)


class ShipmentLineRead(ShipmentLineWrite):
    id: UUID
    conversion_factor: Decimal
    quantity_base: Decimal


class ShipmentRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    sales_order_id: UUID
    warehouse_id: UUID
    document_date: date
    shipment_type: str
    status: str
    is_opening_reference: bool = False
    remark: str | None
    lines: list[ShipmentLineRead]
    created_at: datetime
    updated_at: datetime


class ReturnLineWrite(BaseModel):
    sales_shipment_line_id: UUID
    item_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class ReturnWrite(BaseModel):
    # 留空则由后端按 XT+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    original_shipment_id: UUID
    target_warehouse_id: UUID
    document_date: date
    remark: str | None = None
    lines: list[ReturnLineWrite] = Field(min_length=1)


class ReturnLineRead(ReturnLineWrite):
    id: UUID
    conversion_factor: Decimal
    quantity_base: Decimal


class ReturnRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    original_shipment_id: UUID
    target_warehouse_id: UUID
    document_date: date
    status: str
    remark: str | None
    lines: list[ReturnLineRead]
    created_at: datetime
    updated_at: datetime


class ReverseWrite(BaseModel):
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")
