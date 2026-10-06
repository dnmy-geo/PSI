from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ReceiptLineWrite(BaseModel):
    purchase_order_line_id: UUID
    item_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class ReceiptWrite(BaseModel):
    # 留空则由后端按 CR+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    purchase_order_id: UUID
    warehouse_id: UUID
    document_date: date
    remark: str | None = None
    lines: list[ReceiptLineWrite] = Field(min_length=1)


class ReceiptLineRead(ReceiptLineWrite):
    id: UUID
    conversion_factor: Decimal
    quantity_base: Decimal
    unit_price: Decimal
    amount: Decimal


class ReceiptRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    purchase_order_id: UUID
    warehouse_id: UUID
    document_date: date
    status: str
    is_opening_reference: bool = False
    remark: str | None
    lines: list[ReceiptLineRead]
    created_at: datetime
    updated_at: datetime


class ReturnLineWrite(BaseModel):
    purchase_receipt_line_id: UUID
    item_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class ReturnWrite(BaseModel):
    # 留空则由后端按 CT+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    original_receipt_id: UUID
    warehouse_id: UUID
    document_date: date
    remark: str | None = None
    lines: list[ReturnLineWrite] = Field(min_length=1)


class ReturnLineRead(ReturnLineWrite):
    id: UUID
    conversion_factor: Decimal
    quantity_base: Decimal
    amount: Decimal


class ReturnRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    original_receipt_id: UUID
    warehouse_id: UUID
    document_date: date
    status: str
    remark: str | None
    lines: list[ReturnLineRead]
    created_at: datetime
    updated_at: datetime


class ReverseWrite(BaseModel):
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")
