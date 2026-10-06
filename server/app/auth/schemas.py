from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1)
    organization_code: str | None = Field(default=None, min_length=1, max_length=80)


class UserSession(BaseModel):
    user_id: str
    organization_id: str
    username: str
    display_name: str
    csrf_token: str
