from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")


class WarehouseUpdate(BaseModel):
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    is_active: bool


class WarehouseRead(BaseModel):
    id: UUID
    organization_id: UUID
    code: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
