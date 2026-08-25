"""任务相关 schemas"""
from datetime import datetime
from pydantic import Field
from app.schemas.base import ApiModel as BaseModel


class QuestionPathIn(BaseModel):
    dimension: str = Field(..., pattern="^(monitoring|controlDebugging|evaluation)$")
    stage: str = Field(..., pattern="^(basic|deep|transfer)$")
    prompt_template: str
    trigger_keywords: list[str] = []


class QuestionPathOut(BaseModel):
    id: str
    dimension: str
    stage: str
    prompt_template: str
    trigger_keywords: list[str]

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=128)
    subject: str = Field(default="general", pattern="^(mathematics|science|language|general)$")
    description: str
    scenario: str
    estimated_minutes: int = Field(default=12, ge=1, le=120)
    requires_voice: bool = True
    protocol_order: int = Field(default=0, ge=0, le=100)
    stimulus_data: dict | None = None
    question_paths: list[QuestionPathIn] = []


class TaskOut(BaseModel):
    id: str
    title: str
    subject: str
    description: str
    scenario: str
    estimated_minutes: int
    requires_voice: bool
    protocol_order: int
    stimulus_data: dict | None = None
    status: str
    publisher_id: str
    published_at: datetime | None = None
    deadline: datetime | None = None
    created_at: datetime
    question_paths: list[QuestionPathOut] = []

    model_config = {"from_attributes": True}


class TaskPublish(BaseModel):
    deadline: datetime | None = None
