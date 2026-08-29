"""报告相关 schemas"""
from datetime import datetime
from app.schemas.base import ApiModel as BaseModel


class LearningSuggestionOut(BaseModel):
    id: str
    dimension: str
    title: str
    description: str
    practices: list[str] = []
    difficulty: str

    model_config = {"from_attributes": True}


class DimensionDetailOut(BaseModel):
    dimension: str
    label: str
    score: float
    percentile: float | None = None
    interpretation: str
    evidence: list[dict] = []
    behavioral_score: float | None = None
    questionnaire_score: float | None = None


class ReportOut(BaseModel):
    id: str
    user_id: str
    run_id: str | None = None
    session_id: str
    overall_score: float
    level: str
    summary: str
    dimension_details: list[DimensionDetailOut] = []
    strengths: list[str] = []
    weaknesses: list[str] = []
    recommendations: list[LearningSuggestionOut] = []
    analysis_method: str
    rubric_version: str
    requires_review_count: int
    is_provisional: bool
    workflow_status: str = "draft"
    version_no: int = 1
    template_version: str = "draft-1"
    measurement_snapshot: dict | None = None
    metacognition_pattern: dict | None = None
    generation_metadata: dict | None = None
    overall_score_available: bool = True
    evidence_is_provisional: bool | None = None
    published_at: datetime | None = None
    generated_at: datetime

    model_config = {"from_attributes": True}


class ReportBriefOut(BaseModel):
    """报告摘要（用于列表）"""
    id: str
    run_id: str | None = None
    session_id: str
    overall_score: float
    overall_score_available: bool = True
    level: str
    is_provisional: bool = True
    workflow_status: str = "draft"
    generated_at: datetime

    model_config = {"from_attributes": True}


class ConsistencyOut(BaseModel):
    id: str
    session_id: str
    overall_pearson_r: float
    overall_qwk: float
    dimension_consistency: list[dict] = []
    discrepancies: list[dict] = []
    generated_at: datetime

    model_config = {"from_attributes": True}


class ReportGenerateIn(BaseModel):
    reanalyze: bool = False


class MeasurementSessionState(BaseModel):
    session_id: str
    task_id: str
    status: str
    extraction_generation: int | None = None
    latest_generation: int | None = None
    latest_extraction_status: str | None = None
    using_previous_extraction: bool = False
    model_versions: list[str] = []


class MetacognitionMeasurementOut(BaseModel):
    id: str
    user_id: str
    run_id: str
    scope_type: str = "run"
    scope_key: str = "run"
    task_id: str | None = None
    task_name: str | None = None
    task_ids: list[str] = []
    task_names: list[str] = []
    effective_dialogue_count: int
    denominator_breakdown: dict[str, int] = {}
    fallback_dialogue_count: int = 0
    unclassified_count: int = 0
    evidence_status_counts: dict[str, int] = {}
    retained_previous_count: int = 0
    session_states: list[MeasurementSessionState] = []
    dimension_counts: dict[str, int]
    dimension_scores: dict[str, float | None]
    score_available: bool
    source: str
    data_version: str
    calculated_at: datetime
    completed_at: datetime


class MetacognitionMeasurementPageOut(BaseModel):
    items: list[MetacognitionMeasurementOut]
    page: int
    page_size: int
    total: int
