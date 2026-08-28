from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator
from app.schemas.base import ApiModel as BaseModel


ExperimentType = Literal[
    "tfidf_linear_svc",
    "embedding_linear_svc",
    "embedding_logistic",
    "embedding_random_forest",
    "embedding_xgboost",
    "embedding_lightgbm",
    "embedding_catboost",
]
DatasetSource = Literal["system_gold", "uploaded"]


def _validate_version_name(value: str, field_name: str) -> str:
    """Allow Chinese names while keeping generated artifact paths safe."""
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{field_name}不能为空")
    if not candidate[0].isalnum():
        raise ValueError(f"{field_name}必须以中文、英文字母或数字开头")
    if any(not (character.isalnum() or character in "._-") for character in candidate):
        raise ValueError(
            f"{field_name}只能包含中文、英文字母、数字、英文句点、下划线和连字符"
        )
    return candidate


class TrainingJobCreate(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    experiment_type: ExperimentType = "embedding_linear_svc"
    dataset_source: DatasetSource = "system_gold"
    dataset_id: str | None = None
    hyperparameters: dict[str, int | float | str | bool] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _validate_version_name(value, "训练版本")


class TrainingSuiteCreate(BaseModel):
    version_prefix: str = Field(
        min_length=1, max_length=42
    )
    dataset_source: DatasetSource = "system_gold"
    dataset_id: str | None = None
    experiment_types: list[ExperimentType] | None = None
    hyperparameters: dict[str, dict[str, int | float | str | bool]] = Field(default_factory=dict)

    @field_validator("version_prefix")
    @classmethod
    def validate_version_prefix(cls, value: str) -> str:
        return _validate_version_name(value, "版本前缀")

    @field_validator("experiment_types")
    @classmethod
    def validate_experiment_types(
        cls, value: list[ExperimentType] | None,
    ) -> list[ExperimentType] | None:
        if value is None:
            return None
        if len(value) < 2:
            raise ValueError("横向对比至少需要选择两个模型")
        if len(value) != len(set(value)):
            raise ValueError("横向对比模型不能重复选择")
        return value


class TrainingJobsDeleteIn(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("job_ids")
    @classmethod
    def validate_job_ids(cls, value: list[str]) -> list[str]:
        normalized = [job_id.strip() for job_id in value]
        if any(not job_id for job_id in normalized):
            raise ValueError("训练任务 ID 不能为空")
        if len(normalized) != len(set(normalized)):
            raise ValueError("训练任务不能重复选择")
        return normalized


class TrainingDatasetOut(BaseModel):
    id: str
    name: str
    source: DatasetSource
    original_filename: str | None = None
    sample_count: int
    training_sample_count: int = 0
    excluded_non_metacognitive_count: int = 0
    participant_count: int
    has_participant_ids: bool = False
    split_strategy: str = "sentence_stratified_5fold"
    label_distribution: dict[str, int]
    training_label_distribution: dict[str, int] = Field(default_factory=dict)
    training_labels: list[int] = Field(default_factory=lambda: [1, 2, 3])
    fingerprint: str
    created_by: str | None = None
    created_at: datetime


class TrainingJobOut(BaseModel):
    id: str
    version: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    stage: str
    progress: int
    current_fold: int | None = None
    total_folds: int = 5
    heartbeat_at: datetime | None = None
    estimated_remaining_seconds: int | None = None
    sample_count: int
    label_distribution: dict | None = None
    dataset_fingerprint: str | None = None
    config_snapshot: dict | None = None
    metrics: dict | None = None
    is_active: bool
    artifact_sha256: str | None = None
    cancel_requested: bool = False
    parent_job_id: str | None = None
    error_message: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    activated_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class TrainingAuditOut(BaseModel):
    id: str
    action: str
    job_id: str | None
    version: str | None
    actor_name: str | None
    detail: dict | None = None
    created_at: datetime
