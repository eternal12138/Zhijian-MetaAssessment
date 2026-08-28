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
    published_at: datetime | None = None
    generated_at: datetime

    model_config = {"from_attributes": True}


class ReportBriefOut(BaseModel):
    """报告摘要（用于列表）"""
    id: str
    run_id: str | None = None
    session_id: str
    overall_score: float
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
