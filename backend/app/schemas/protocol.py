"""标准化双任务测评流程 API schemas。"""
from datetime import datetime

from pydantic import Field, field_validator
from app.schemas.base import ApiModel as BaseModel


class ProtocolTaskOut(BaseModel):
    id: str
    title: str
    description: str
    scenario: str
    estimated_minutes: int
    protocol_order: int
    stimulus_data: dict | None = None


class ProtocolQuestionnaireItemOut(BaseModel):
    id: str
    dimension: str
    text: str
    scale_min: int
    scale_max: int
    display_order: int


class ProtocolNarrationAssetOut(BaseModel):
    id: str
    slot_key: str
    version: int
    original_filename: str
    mime_type: str
    size_bytes: int
    created_at: datetime


class AssessmentProtocolOut(BaseModel):
    version: str
    questionnaire_enabled: bool = False
    questionnaire_source: str
    task_order_code: str = "AB"
    order_source: str = "default"
    tasks: list[ProtocolTaskOut]
    questionnaire_items: list[ProtocolQuestionnaireItemOut]
    likert_labels: dict[int, str]
    narration_assets: list[ProtocolNarrationAssetOut] = Field(default_factory=list)


class RunCreateIn(BaseModel):
    consent: bool


class RunSessionOut(BaseModel):
    id: str
    task_id: str
    sequence_no: int
    status: str


class QuestionnaireAnswerOut(BaseModel):
    item_id: str
    value: int


class AssessmentRunOut(BaseModel):
    id: str
    user_id: str
    status: str
    current_stage: str
    protocol_version: str
    questionnaire_enabled: bool = True
    questionnaire_source: str
    task_order_code: str = "AB"
    order_assignment_id: str | None = None
    consented_at: datetime
    started_at: datetime
    completed_at: datetime | None = None
    sessions: list[RunSessionOut]
    questionnaire_answers: list[QuestionnaireAnswerOut] = []
    questionnaire_participant_name: str | None = None


class RunStageIn(BaseModel):
    stage: str = Field(
        pattern="^(device_check|instructions|practice|task_1|task_2|questionnaire|review)$"
    )


class QuestionnaireAnswerIn(BaseModel):
    item_id: str = Field(min_length=1, max_length=36)
    value: int = Field(ge=1, le=7)


class QuestionnaireSubmitIn(BaseModel):
    answers: list[QuestionnaireAnswerIn] = Field(min_length=1, max_length=100)
    participant_name: str = Field(min_length=1, max_length=255)

    @field_validator("participant_name")
    @classmethod
    def normalize_participant_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("请填写您的姓名或参加实验时使用的微信名等标识")
        return normalized


class ProtocolConfigUpdate(BaseModel):
    questionnaire_enabled: bool


class ProtocolConfigOut(BaseModel):
    questionnaire_enabled: bool
    updated_at: datetime | None = None


class NarrationAssetOut(BaseModel):
    id: str
    slot_key: str
    label: str
    source_text: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    version: int
    is_active: bool
    uploaded_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class NarrationSlotOut(BaseModel):
    slot_key: str
    label: str
    source_text: str
    category: str
    asset: NarrationAssetOut | None = None


class TaskOrderAssignmentIn(BaseModel):
    ordered_task_ids: list[str] = Field(min_length=2, max_length=2)


class TaskOrderBalanceIn(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=500)


class TaskOrderStudentOut(BaseModel):
    user_id: str
    username: str
    name: str
    class_group: str | None
    ordered_task_ids: list[str]
    order_code: str
    assigned_by: str | None = None
    assigned_at: datetime | None = None
    has_in_progress_run: bool = False


class TaskOrderOverviewOut(BaseModel):
    tasks: list[ProtocolTaskOut]
    students: list[TaskOrderStudentOut]
    total: int = 0
    page: int = 1
    page_size: int = 50
