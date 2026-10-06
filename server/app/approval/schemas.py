from typing import Literal
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


DocumentType = Literal["sales_order", "stocktake"]


class ApprovalStepWrite(BaseModel):
    approver_role_id: UUID | None = None
    approver_user_id: UUID | None = None

    @model_validator(mode="after")
    def exactly_one_approver(self):
        if (self.approver_role_id is None) == (self.approver_user_id is None):
            raise ValueError("每个审批层级必须且只能指定一个岗位或一名用户")
        return self


class ApprovalConfigWrite(BaseModel):
    is_enabled: bool = True
    steps: list[ApprovalStepWrite] = Field(min_length=1, max_length=10)


class ApprovalStepRead(ApprovalStepWrite):
    id: UUID
    step_no: int


class ApprovalConfigRead(BaseModel):
    id: UUID
    organization_id: UUID
    document_type: DocumentType
    is_enabled: bool
    version: int
    steps: list[ApprovalStepRead]


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    opinion: str | None = Field(default=None, max_length=1000)


class ApprovalTaskRead(BaseModel):
    id: UUID
    instance_id: UUID
    step_no: int
    approver_role_id: UUID | None
    approver_user_id: UUID | None
    status: str
    created_at: datetime
    document_type: str
    document_id: UUID
    submitted_at: datetime


class ApprovalTaskHistory(BaseModel):
    id: UUID
    step_no: int
    approver_role_id: UUID | None
    approver_user_id: UUID | None
    acted_by: UUID | None
    status: str
    opinion: str | None
    created_at: datetime
    acted_at: datetime | None


class ApprovalInstanceRead(BaseModel):
    id: UUID
    organization_id: UUID
    config_id: UUID
    config_version: int
    document_type: str
    document_id: UUID
    status: str
    current_step_no: int
    submitted_by: UUID
    submitted_at: datetime
    finished_at: datetime | None
    tasks: list[ApprovalTaskHistory]
