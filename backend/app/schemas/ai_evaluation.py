from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import ApiModel


EvaluationScope = Literal["all", "student", "session", "task"]


class AiEvaluationRunIn(ApiModel):
    scope: EvaluationScope = "all"
    ids: list[str] = Field(default_factory=list, max_length=500)
    batch_size: int = Field(default=100, ge=1, le=200)


class AiEvaluationModelOut(ApiModel):
    id: str
    version: str
    experiment_type: str
    display_name: str
    macro_f1: float | None = None
    weighted_f1: float | None = None
    is_active: bool
    is_best: bool = False
    completed_at: datetime | None = None


class AiEvaluationScopeOut(ApiModel):
    session_id: str
    participant_id: str
    participant_name: str
    username: str
    class_group: str | None = None
    task_id: str
    task_title: str
    completed_at: datetime | None = None
    candidate_count: int
    reviewed_count: int
    pending_count: int
    rejected_count: int
    classified_count: int
    training_participant: bool = False
    dimension_counts: dict[str, int] = Field(default_factory=dict)


class AiEvaluationOverviewOut(ApiModel):
    enabled: bool
    can_activate: bool
    active_model: AiEvaluationModelOut | None = None
    best_model_id: str | None = None
    models: list[AiEvaluationModelOut] = Field(default_factory=list)
    training_source: Literal["system_gold", "uploaded", "none"] = "none"
    training_source_label: str
    scope_items: list[AiEvaluationScopeOut] = Field(default_factory=list)


class AiEvaluationRunOut(ApiModel):
    model_id: str
    model_version: str
    processed: int
    remaining: int
    skipped_rejected: int
    source_counts: dict[str, int] = Field(default_factory=dict)
    dimension_counts: dict[str, int] = Field(default_factory=dict)
