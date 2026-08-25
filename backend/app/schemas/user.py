"""用户相关 schemas"""
from datetime import datetime
from pydantic import Field
from app.schemas.base import ApiModel as BaseModel


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    name: str = Field(..., min_length=1, max_length=64)
    role: str = Field(default="student", pattern="^(student|teacher|admin)$")
    class_group: str | None = None


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    name: str
    role: str
    avatar_text: str
    class_group: str | None = None
    managed_classes: str | None = None
    is_active: bool = True
    must_change_password: bool = False
    can_manage_users: bool = False
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
