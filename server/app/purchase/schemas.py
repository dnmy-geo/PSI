from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PurchaseOrderLineWrite(BaseModel):
    item_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)


class PurchaseOrderWrite(BaseModel):
    # 留空则由后端按 CG+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    supplier_id: UUID
    document_date: date
    remark: str | None = None
    lines: list[PurchaseOrderLineWrite] = Field(min_length=1)


class PurchaseOrderLineRead(PurchaseOrderLineWrite):
    id: UUID
    conversion_factor: Decimal
    quantity_base: Decimal
    amount: Decimal
    received_quantity_base: Decimal
    unreceived_quantity_base: Decimal


class PurchaseOrderRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    supplier_id: UUID
    document_date: date
    status: str
    close_remark: str | None
    remark: str | None
    lines: list[PurchaseOrderLineRead]
    # 未入库数量合计（明细各行之和）：0 = 已入完。列表的「入库状态」列用它。
    unreceived_quantity_base: Decimal = Decimal("0")
    created_at: datetime
    updated_at: datetime


class CloseRequest(BaseModel):
    remark: str = Field(min_length=1, max_length=1000, pattern=r"\S")
