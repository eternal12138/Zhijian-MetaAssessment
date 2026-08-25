"""High-recall metacognitive candidate extraction and human validation records."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ExtractionJob(Base):
    """One immutable extraction attempt against one transcript version."""

    __tablename__ = "extraction_jobs"
    __table_args__ = (
        UniqueConstraint(
            "transcript_version_id",
            "extractor_version",
            "prompt_version",
            "generation_no",
            name="uq_extraction_version_config",
        ),
        Index(
            "ix_extraction_version_created",
            "transcript_version_id", "created_at", "id",
        ),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("assessment_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    transcript_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("transcript_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="queued", index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="openai_compatible")
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    generation_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("extraction_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    prompt_content: Mapped[str] = mapped_column(Text, nullable=False)
    raw_asr_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_lock_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    review_lock_acquired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    candidates: Mapped[list["ExtractionCandidate"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="ExtractionCandidate.sequence_no"
    )


class ExtractionCandidate(Base):
    """An LLM-proposed or human-added candidate, never a final metacognitive label."""

    __tablename__ = "extraction_candidates"
    __table_args__ = (
        UniqueConstraint("extraction_job_id", "sequence_no", name="uq_extraction_candidate_no"),
        Index("ix_candidate_job_status", "extraction_job_id", "review_status"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    extraction_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("extraction_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_transcript_segment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transcript_segments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assessment_runs.id"), nullable=True, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessment_tasks.id"), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="llm")
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    raw_asr_text: Mapped[str] = mapped_column(Text, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    clean_text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ended_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reviewer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    classifier_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("model_training_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    classifier_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    predicted_label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_dimension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prediction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    prediction_probabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    classification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_classification", index=True
    )
    prediction_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    classification_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    job: Mapped[ExtractionJob] = relationship(back_populates="candidates")


class ExtractionCandidateRevision(Base):
    """Immutable before/after snapshots for every human candidate operation."""

    __tablename__ = "extraction_candidate_revisions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("extraction_candidates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    extraction_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("extraction_jobs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    before_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
