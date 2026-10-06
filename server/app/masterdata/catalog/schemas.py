from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


Code = str
ItemType = Literal["raw_material", "semi_finished", "finished"]


class UnitCreate(BaseModel):
    code: Code = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    precision_scale: int = Field(ge=0, le=6)
    # 挂在哪个基本单位下，以及 1 个本单位等于多少个基本单位（如 1 箱 = 12 个）。
    base_unit_id: UUID | None = None
    base_quantity: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=6)

    @model_validator(mode="after")
    def _base_unit_and_quantity_together(self) -> "UnitCreate":
        if (self.base_unit_id is None) != (self.base_quantity is None):
            raise ValueError("基本单位与基本数量必须同时填写")
        return self


class UnitRelated(BaseModel):
    """把本单位当作基本单位的单位。"""
    id: UUID
    code: str
    name: str
    base_quantity: Decimal


class UnitRead(UnitCreate):
    id: UUID
    organization_id: UUID
    is_active: bool
    related_units: list[UnitRelated] = []
    created_at: datetime
    updated_at: datetime


class UnitUpdate(UnitCreate):
    is_active: bool


class ItemCreate(BaseModel):
    code: Code = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=150, pattern=r"\S")
    item_type: ItemType
    base_unit_id: UUID
    category_id: UUID | None = None


class ItemRead(ItemCreate):
    id: UUID
    organization_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ItemUpdate(BaseModel):
    code: Code = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=150, pattern=r"\S")
    category_id: UUID | None = None
    is_active: bool

