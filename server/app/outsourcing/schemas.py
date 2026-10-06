from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class MaterialWrite(BaseModel):
    item_id: UUID
    supply_party: Literal["self", "processor"]
    expected_quantity_base: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class OutputWrite(BaseModel):
    item_id: UUID
    expected_quantity_base: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)


class OrderWrite(BaseModel):
    # 留空则由后端按 WW+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    processor_id: UUID
    document_date: date
    remark: str | None = None
    materials: list[MaterialWrite] = Field(default_factory=list)
    outputs: list[OutputWrite] = Field(min_length=1)


class MaterialRead(MaterialWrite):
    id: UUID
    issued_quantity_base: Decimal
    remaining_quantity_base: Decimal


class OutputRead(OutputWrite):
    id: UUID
    received_quantity_base: Decimal
    remaining_quantity_base: Decimal


class OrderRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    processor_id: UUID
    document_date: date
    status: str
    remark: str | None
    materials: list[MaterialRead]
    outputs: list[OutputRead]
    created_at: datetime
    updated_at: datetime


class CloseWrite(BaseModel):
    remark: str = Field(min_length=1, max_length=1000, pattern=r"\S")
