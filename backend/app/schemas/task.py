"""任务相关 schemas"""
from datetime import datetime
from app.schemas.base import ApiModel as BaseModel

class QuestionPathOut(BaseModel):
    id: str
    dimension: str
    stage: str
    prompt_template: str
    trigger_keywords: list[str]

    model_config = {"from_attributes": True}


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
