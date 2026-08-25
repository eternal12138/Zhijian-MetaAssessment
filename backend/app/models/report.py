"""
报告模型 - 元认知画像 / 学习建议 / 人机一致性
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, Float, DateTime, ForeignKey, func, JSON
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
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(
        back_populates="reports",
        foreign_keys=[user_id],
    )
    session: Mapped["AssessmentSession"] = relationship(back_populates="report")
    suggestions: Mapped[list["LearningSuggestion"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


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
