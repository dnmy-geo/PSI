from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class OrganizationRead(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")


class DepartmentCreate(BaseModel):
    code: str | None = Field(default=None, max_length=80)
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    parent_id: UUID | None = None
    is_active: bool = True


class DepartmentWrite(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"\S")
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    parent_id: UUID | None = None
    is_active: bool = True


class DepartmentRead(DepartmentWrite):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime


class RoleWrite(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"\S")
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    is_active: bool = True


class RoleRead(RoleWrite):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80, pattern=r"\S")
    display_name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    password: str = Field(min_length=6)
    department_id: UUID | None = None
    role_ids: list[UUID] = Field(min_length=1)
    is_active: bool = True


class UserUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=80, pattern=r"\S")
    display_name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    department_id: UUID | None = None
    role_ids: list[UUID] = Field(min_length=1)
    is_active: bool = True


class UserRead(BaseModel):
    id: UUID
    organization_id: UUID
    username: str
    display_name: str
    department_id: UUID | None
    role_ids: list[UUID]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PasswordReset(BaseModel):
    password: str = Field(min_length=6)
