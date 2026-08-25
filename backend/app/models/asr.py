"""服务端权威 ASR 任务与转录版本。"""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text,
    Index, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AsrJob(Base):
    __tablename__ = "asr_jobs"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "manifest_hash", "provider", "model", "config_version",
            name="uq_asr_job_manifest_config",
        ),
        Index("ix_asr_session_created", "session_id", "created_at", "id"),
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
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", index=True
    )
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    expected_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    canonical_audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    audio_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    audio_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    audio_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_contains_signal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    audio_rms_dbfs: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_peak_dbfs: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    session: Mapped["AssessmentSession"] = relationship(back_populates="asr_jobs")
    transcript_version: Mapped["TranscriptVersion | None"] = relationship(
        back_populates="asr_job", uselist=False
    )


class TranscriptVersion(Base):
    __tablename__ = "transcript_versions"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "version_no",
            name="uq_transcript_version_session_no",
        ),
        Index(
            "ix_transcript_authoritative_latest",
            "session_id", "is_authoritative", "version_no",
        ),
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
    asr_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("asr_jobs.id"), nullable=True, unique=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    is_authoritative: Mapped[bool] = mapped_column(nullable=False, default=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    full_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    session: Mapped["AssessmentSession"] = relationship(
        back_populates="transcript_versions"
    )
    asr_job: Mapped["AsrJob | None"] = relationship(back_populates="transcript_version")
    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="transcript_version",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.segment_no",
    )
