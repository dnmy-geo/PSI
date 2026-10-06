from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PlanLineWrite(BaseModel):
    item_id: UUID
    planned_quantity_base: int = Field(gt=0, le=9223372036854775807, strict=True)


class PlanWrite(BaseModel):
    # 留空则由后端按 SC+日期+流水生成。
    document_no: str | None = Field(default=None, min_length=1, max_length=60, pattern=r"\S")
    document_date: date
    remark: str | None = None
    lines: list[PlanLineWrite] = Field(min_length=1)


class PlanLineRead(PlanLineWrite):
    id: UUID
    # 物料的基本单位编码（计划数量就是按它计的整数）。
    unit_code: str | None = None
    allocated_quantity_base: int
    remaining_quantity_base: int


class PlanRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    document_date: date
    status: str
    remark: str | None
    lines: list[PlanLineRead]
    created_at: datetime
    updated_at: datetime


class ShortageLine(BaseModel):
    item_id: UUID
    item_code: str
    item_name: str
    item_type: str
    base_unit_id: UUID
    demand_quantity_base: Decimal
    available_quantity_base: Decimal
    shortage_quantity_base: Decimal
    bom_version: int | None


class ShortageRead(BaseModel):
    plan_id: UUID
    lines: list[ShortageLine]


class AutoSplitRequest(BaseModel):
    order_count: int = Field(gt=0, le=100)


class OrderOutputWrite(BaseModel):
    production_plan_line_id: UUID
    planned_quantity_base: int = Field(gt=0, le=9223372036854775807, strict=True)


class ManualOrderWrite(BaseModel):
    # 留空则由后端按「计划单号-P001」生成（与均分拆单同一套）。
    document_no: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    remark: str | None = None
    outputs: list[OrderOutputWrite] = Field(min_length=1)


class ManualSplitRequest(BaseModel):
    orders: list[ManualOrderWrite] = Field(min_length=1, max_length=100)


class OrderOutputRead(OrderOutputWrite):
    id: UUID
    item_id: UUID
    # 物料的基本单位编码（产出数量就是按它计的整数）。
    unit_code: str | None = None


class ProductionOrderRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_no: str
    production_plan_id: UUID
    document_date: date
    status: str
    remark: str | None
    outputs: list[OrderOutputRead]
    created_at: datetime
    updated_at: datetime
