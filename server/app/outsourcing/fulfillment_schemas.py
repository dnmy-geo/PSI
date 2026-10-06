from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ReverseWrite(BaseModel):
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class IssueLineWrite(BaseModel):
    outsourcing_material_line_id: UUID
    item_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    unit_id: UUID


class IssueWrite(BaseModel):
    # 留空则由后端按 WWFL+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    outsourcing_order_id: UUID
    warehouse_id: UUID
    document_date: date
    remark: str | None = None
    lines: list[IssueLineWrite] = Field(min_length=1)


class IssueLineRead(IssueLineWrite):
    id: UUID
    conversion_factor: Decimal
    quantity_base: Decimal


class IssueRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    outsourcing_order_id: UUID
    warehouse_id: UUID
    document_date: date
    status: str
    remark: str | None
    posted_at: datetime | None
    lines: list[IssueLineRead]
    created_at: datetime
    updated_at: datetime


class ReceiptLineWrite(BaseModel):
    outsourcing_output_line_id: UUID
    item_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    unit_id: UUID


class ReceiptWrite(BaseModel):
    # 留空则由后端按 WWRK+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    outsourcing_order_id: UUID
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
    outsourcing_order_id: UUID
    warehouse_id: UUID
    document_date: date
    status: str
    remark: str | None
    posted_at: datetime | None
    lines: list[ReceiptLineRead]
    created_at: datetime
    updated_at: datetime
