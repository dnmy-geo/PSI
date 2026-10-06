from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class SalesOrderLineWrite(BaseModel):
    item_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)


class SalesOrderWrite(BaseModel):
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    customer_id: UUID
    document_date: date
    delivery_date: date | None = None
    remark: str | None = None
    lines: list[SalesOrderLineWrite] = Field(min_length=1)


class SalesOrderLineRead(SalesOrderLineWrite):
    id: UUID
    conversion_factor: Decimal
    quantity_base: Decimal
    amount: Decimal
    shipped_quantity_base: Decimal
    unshipped_quantity_base: Decimal


class SalesOrderRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    customer_id: UUID
    document_date: date
    delivery_date: date | None
    status: str
    close_remark: str | None
    remark: str | None
    lines: list[SalesOrderLineRead]
    created_at: datetime
    updated_at: datetime


class SalesOrderSummary(BaseModel):
    id: UUID
    document_no: str
    customer_id: UUID
    document_date: date
    status: str
    created_at: datetime
    updated_at: datetime
    # 未发数量（订单量 − 已出库 + 已退货）：出库单只能选还有未发量的订单。
    unshipped_quantity_base: Decimal = Decimal("0")
    created_at: datetime


class CloseRequest(BaseModel):
    remark: str = Field(min_length=1, max_length=1000, pattern=r"\S")
