"""第四阶段：研究工作流、双人编码、模板、导出与审计。"""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Computed, DateTime, Float, ForeignKey, Index, Integer, JSON,
    LargeBinary, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MethodTemplate(Base):
    __tablename__ = "method_templates"
    __table_args__ = (
        UniqueConstraint("template_key", "version", name="uq_method_template_version"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    template_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_runs.id"), nullable=False, index=True
    )
    requested_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_profile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("metacognitive_profiles.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CodingAnnotation(Base):
    __tablename__ = "coding_annotations"
    __table_args__ = (
        UniqueConstraint("coding_id", "reviewer_id", name="uq_coding_reviewer"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    coding_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("coded_segments.id"), nullable=False, index=True
    )
    reviewer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    dimension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    coding: Mapped["CodedSegment"] = relationship()


class CodingAdjudication(Base):
    __tablename__ = "coding_adjudications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    coding_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("coded_segments.id"), unique=True, nullable=False
    )
    adjudicator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    dimension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class CodingBatch(Base):
    """A fixed, blinded A/B coding assignment managed by an administrator."""

    __tablename__ = "coding_batches"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="active", index=True
    )
    reviewer_a_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    reviewer_b_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    adjudicator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    rubric_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="2026.2"
    )
    scope_filter: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scope_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CodingUnit(Base):
    """One authoritative transcript segment, independent from any AI prediction."""

    __tablename__ = "coding_units"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "transcript_segment_id",
            name="uq_coding_batch_transcript",
        ),
        UniqueConstraint("batch_id", "candidate_id", name="uq_coding_batch_candidate"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    batch_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("coding_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    transcript_segment_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("transcript_segments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    candidate_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("extraction_candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_sessions.id"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assessment_runs.id"), nullable=True, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_tasks.id"), nullable=False
    )
    audio_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("asr_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    participant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    clean_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_before: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_after: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ended_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ai_dimension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", index=True
    )
    final_dimension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    final_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class CodingUnitAnnotation(Base):
    """A blinded annotation submitted by the batch's fixed reviewer A or B."""

    __tablename__ = "coding_unit_annotations"
    __table_args__ = (
        UniqueConstraint("unit_id", "reviewer_id", name="uq_unit_reviewer"),
        UniqueConstraint("unit_id", "reviewer_slot", name="uq_unit_reviewer_slot"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    unit_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("coding_units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    reviewer_slot: Mapped[str] = mapped_column(String(1), nullable=False)
    dimension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class ExpertAnnotation(Base):
    """One expert's independent label; never overwrites AI or another expert."""

    __tablename__ = "expert_annotations"
    __table_args__ = (
        UniqueConstraint("segment_id", "expert_id", name="uq_expert_segment_reviewer"),
        UniqueConstraint("segment_id", "reviewer_slot", name="uq_expert_segment_slot"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    segment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("coding_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expert_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    reviewer_slot: Mapped[str] = mapped_column(String(1), nullable=False)
    expert_label: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CodingUnitAdjudication(Base):
    """Third-party resolution for a unit where reviewer A and B disagree."""

    __tablename__ = "coding_unit_adjudications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    unit_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("coding_units.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    adjudicator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    dimension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    requested_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    export_type: Mapped[str] = mapped_column(String(32), nullable=False, default="research_csv")
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dataset_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class RunQualityReview(Base):
    """Human inclusion/exclusion decision layered over automatic quality checks."""

    __tablename__ = "run_quality_reviews"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_runs.id", ondelete="CASCADE"),
        unique=True, nullable=False, index=True,
    )
    decision: Mapped[str] = mapped_column(
        String(24), nullable=False, default="automatic", index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ModelTrainingJob(Base):
    """Immutable training version built from human-reviewed research data."""

    __tablename__ = "model_training_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_fold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_folds: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    estimated_remaining_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label_distribution: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dataset_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("model_training_jobs.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    activated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active_scope: Mapped[int | None] = mapped_column(
        Integer,
        Computed("(if(`is_active`, 1, NULL))", persisted=True),
        nullable=True,
    )
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), index=True
    )


class TextEmbeddingCache(Base):
    """Reusable normalized float32 embeddings; never stores participant identity."""

    __tablename__ = "text_embedding_cache"
    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="legacy")
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    instruction_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    vector: Mapped[bytes] = mapped_column(LargeBinary(length=16 * 1024 * 1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ModelPredictionRun(Base):
    """Immutable audit record for one production/shadow classification batch."""

    __tablename__ = "model_prediction_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("model_training_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )


class ModelPredictionResult(Base):
    """Immutable per-candidate inference outcome attached to a prediction run."""

    __tablename__ = "model_prediction_results"
    __table_args__ = (
        UniqueConstraint("run_id", "candidate_id", name="uq_prediction_run_candidate"),
        Index("ix_prediction_result_candidate", "candidate_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("model_prediction_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("extraction_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    input_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    predicted_label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_dimension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prediction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    prediction_probabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top1_top2_gap: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_confidence_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    inference_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
