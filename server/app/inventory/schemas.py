from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class TransferLineCreate(BaseModel):
    item_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class TransferCreate(BaseModel):
    # 留空则由后端按 DB+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    document_date: date
    source_warehouse_id: UUID
    target_warehouse_id: UUID
    remark: str | None = None
    lines: list[TransferLineCreate] = Field(min_length=1)


class TransferLineRead(TransferLineCreate):
    id: UUID
    conversion_factor: Decimal
    quantity_base: Decimal


class TransferRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    document_date: date
    source_warehouse_id: UUID
    target_warehouse_id: UUID
    status: str
    remark: str | None
    lines: list[TransferLineRead]
    created_at: datetime
    updated_at: datetime


class StockBalanceRead(BaseModel):
    warehouse_id: UUID
    item_id: UUID
    quantity_base: Decimal
    # 物料的基本单位编码（结存数量就是按它计量）。
    base_unit_code: str


class StockMovementRead(BaseModel):
    id: UUID
    warehouse_id: UUID
    item_id: UUID
    quantity_delta_base: Decimal
    source_type: str
    source_id: UUID
    source_line_id: UUID
    # 来源单据的单号（列表显示用）：来源类型查不到对应单据表时为空。
    source_document_no: str | None = None
    movement_kind: str
    reversal_of_id: UUID | None
    posted_by: UUID | None
    posted_at: datetime


class OpeningStockLineRead(BaseModel):
    id: UUID
    warehouse_id: UUID
    item_id: UUID
    unit_id: UUID
    quantity: Decimal
    conversion_factor: Decimal
    quantity_base: Decimal


class OpeningStockRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    effective_date: date
    import_batch_no: str | None
    status: str
    remark: str | None
    lines: list[OpeningStockLineRead]
    created_at: datetime
    updated_at: datetime


class ReverseReason(BaseModel):
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")
