from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

PartyType = Literal["customer", "supplier", "processor"]


class PartyWrite(BaseModel):
    code: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=150, pattern=r"\S")
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=60)
    types: set[PartyType] = Field(min_length=1)


class PartyUpdate(PartyWrite):
    is_active: bool


class PartyRead(BaseModel):
    id: UUID
    organization_id: UUID
    code: str
    name: str
    contact_name: str | None
    contact_phone: str | None
    is_active: bool
    types: list[PartyType]
    created_at: datetime
    updated_at: datetime

