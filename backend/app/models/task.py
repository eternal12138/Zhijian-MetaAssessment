"""
测评任务模型 - 教师发布的问题解决任务
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, Boolean, Enum, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AssessmentTask(Base):
    __tablename__ = "assessment_tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    subject: Mapped[str] = mapped_column(
        Enum("mathematics", "science", "language", "general", name="task_subject"),
        nullable=False, default="general"
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=12)
    requires_voice: Mapped[bool] = mapped_column(Boolean, default=True)
    protocol_order: Mapped[int] = mapped_column(Integer, default=0)
    stimulus_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("draft", "published", "closed", name="task_status"),
        nullable=False, default="draft"
    )
    publisher_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # 关联
    publisher: Mapped["User"] = relationship(back_populates="published_tasks", foreign_keys=[publisher_id])
    question_paths: Mapped[list["QuestionPath"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    sessions: Mapped[list["AssessmentSession"]] = relationship(back_populates="task")
    dimension_groups: Mapped[list["ScaleDimensionGroup"]] = relationship(back_populates="task")


class QuestionPath(Base):
    """启发式提问路径"""
    __tablename__ = "question_paths"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessment_tasks.id"), nullable=False)
    dimension: Mapped[str] = mapped_column(
        Enum("monitoring", "controlDebugging", "evaluation", name="path_dimension"),
        nullable=False
    )
    stage: Mapped[str] = mapped_column(
        Enum("basic", "deep", "transfer", name="path_stage"), nullable=False
    )
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_keywords: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON array string")

    task: Mapped["AssessmentTask"] = relationship(back_populates="question_paths")
