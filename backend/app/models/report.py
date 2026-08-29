"""
报告模型 - 元认知画像 / 学习建议 / 人机一致性
"""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, String, Text, Integer, Float, DateTime, ForeignKey, func, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class MetacognitiveProfile(Base):
    """元认知画像"""
    __tablename__ = "metacognitive_profiles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assessment_runs.id"), unique=True, nullable=True
    )
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessment_sessions.id"), unique=True, nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    level: Mapped[str] = mapped_column(String(16), default="发展中")
    summary: Mapped[str] = mapped_column(Text, default="")
    dimension_details: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True, comment="维度详情的 JSON")
    strengths: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON array")
    weaknesses: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON array")
    analysis_method: Mapped[str] = mapped_column(String(32), default="rule")
    rubric_version: Mapped[str] = mapped_column(String(32), default="2026.1")
    requires_review_count: Mapped[int] = mapped_column(Integer, default=0)
    is_provisional: Mapped[bool] = mapped_column(default=True)
    workflow_status: Mapped[str] = mapped_column(String(24), default="draft")
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    template_version: Mapped[str] = mapped_column(String(32), default="draft-1")
    evidence_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generation_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def overall_score_available(self):
        return self.evidence_snapshot is None

    user: Mapped["User"] = relationship(
        back_populates="reports",
        foreign_keys=[user_id],
    )
    session: Mapped["AssessmentSession"] = relationship(back_populates="report")
    suggestions: Mapped[list["LearningSuggestion"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class ReportRevision(Base):
    """Immutable successful report versions; never reconstruct legacy provenance."""
    __tablename__ = "report_revisions"
    __table_args__ = (Index("uq_report_revision", "profile_id", "version_no", unique=True),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("metacognitive_profiles.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MetacognitionMeasurement(Base):
    """Traceable run- or task-scoped behavioral proportion snapshot."""

    __tablename__ = "metacognition_measurements"
    __table_args__ = (
        Index(
            "uq_metacognition_measurement_scope",
            "run_id", "scope_key",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="run")
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False, default="run")
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(
            "assessment_tasks.id",
            ondelete="CASCADE",
            name="fk_metacognition_measurement_task",
        ),
        nullable=True, index=True,
    )
    task_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    effective_dialogue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    monitoring_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    control_debugging_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    monitoring_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    control_debugging_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    data_version: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    calculated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class MeasurementCorrection(Base):
    """Immutable admin-uploaded, complete reviewed dialogue set for one session."""

    __tablename__ = "measurement_corrections"
    __table_args__ = (
        Index("uq_measurement_correction_version", "session_id", "version_no", unique=True),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_sessions.id", ondelete="CASCADE"), index=True,
    )
    uploaded_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    dialogues: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    dimension_counts: Mapped[dict] = mapped_column(JSON, nullable=False)
    effective_dialogue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class LearningSuggestion(Base):
    """个性化学习建议"""
    __tablename__ = "learning_suggestions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("metacognitive_profiles.id"), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    practices: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON array")
    difficulty: Mapped[str] = mapped_column(String(16), default="medium")

    profile: Mapped["MetacognitiveProfile"] = relationship(back_populates="suggestions")


class ConsistencyReport(Base):
    """人机一致性校验报告"""
    __tablename__ = "consistency_reports"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessment_sessions.id"), nullable=False)
    overall_pearson_r: Mapped[float] = mapped_column(Float, default=0.0)
    overall_qwk: Mapped[float] = mapped_column(Float, default=0.0)
    dimension_consistency: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    discrepancies: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
