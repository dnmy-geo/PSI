from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CategoryWrite(BaseModel):
    code: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=150, pattern=r"\S")
    parent_id: UUID | None = None


class CategoryRead(CategoryWrite):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

