from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class IssueLineWrite(BaseModel):
    item_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    bom_quantity_base: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    loss_quantity_base: Decimal = Field(default=Decimal("0"), ge=0, max_digits=20, decimal_places=6)


class IssueWrite(BaseModel):
    # 留空则由后端按 SCLL+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    production_order_id: UUID
    source_warehouse_id: UUID
    target_warehouse_id: UUID
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
    production_order_id: UUID
    source_warehouse_id: UUID
    target_warehouse_id: UUID
    document_date: date
    status: str
    remark: str | None
    lines: list[IssueLineRead]
    created_at: datetime
    updated_at: datetime


class ConsumptionLineWrite(BaseModel):
    item_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class ConsumptionWrite(BaseModel):
    # 留空则由后端按 SCXH+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    production_order_id: UUID
    warehouse_id: UUID
    document_date: date
    remark: str | None = None
    lines: list[ConsumptionLineWrite] = Field(min_length=1)


class ConsumptionLineRead(ConsumptionLineWrite):
    id: UUID
    conversion_factor: Decimal
    quantity_base: Decimal


class ConsumptionRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    production_order_id: UUID
    warehouse_id: UUID
    document_date: date
    status: str
    remark: str | None
    lines: list[ConsumptionLineRead]
    created_at: datetime
    updated_at: datetime


class ReceiptLineWrite(BaseModel):
    production_order_output_id: UUID
    item_id: UUID
    target_warehouse_id: UUID
    quantity_base: int = Field(gt=0, le=9223372036854775807, strict=True)


class ReceiptWrite(BaseModel):
    # 留空则由后端按 SCRK+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    production_order_id: UUID
    document_date: date
    remark: str | None = None
    lines: list[ReceiptLineWrite] = Field(min_length=1)


class ReceiptLineRead(ReceiptLineWrite):
    id: UUID


class ReceiptRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    production_order_id: UUID
    document_date: date
    status: str
    remark: str | None
    lines: list[ReceiptLineRead]
    created_at: datetime
    updated_at: datetime


class ReverseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")
