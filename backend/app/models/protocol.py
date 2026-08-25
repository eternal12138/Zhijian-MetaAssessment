"""标准化测评流程、完整测评批次与问卷作答模型。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, JSON, DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AssessmentRun(Base):
    """一次完整测评，包含两个任务会话及创建时固化的可选问卷协议。"""

    __tablename__ = "assessment_runs"
    __table_args__ = (
        Index("ix_runs_started_id", "started_at", "id"),
        Index("ix_runs_user_started", "user_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        Enum("in_progress", "completed", "abandoned", name="run_status"),
        nullable=False,
        default="in_progress",
    )
    current_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default="device_check"
    )
    protocol_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="2026.2"
    )
    questionnaire_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    questionnaire_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="Zepeda-2023-task-based"
    )
    questionnaire_participant_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    task_order_code: Mapped[str] = mapped_column(
        String(32), nullable=False, default="AB"
    )
    order_assignment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("task_order_assignments.id"), nullable=True
    )
    narration_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    consented_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list["AssessmentSession"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AssessmentSession.sequence_no",
    )
    questionnaire_responses: Mapped[list["QuestionnaireResponse"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class TaskOrderAssignment(Base):
    """教师或管理员为学生设置的下一次标准测评任务顺序。"""

    __tablename__ = "task_order_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_task_order_assignment_user"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    ordered_task_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    order_code: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class QuestionnaireResponse(Base):
    """一次完整测评中的单个任务型问卷作答。"""

    __tablename__ = "questionnaire_responses"
    __table_args__ = (
        UniqueConstraint("run_id", "item_id", name="uq_questionnaire_run_item"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_runs.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scale_items.id"), nullable=False
    )
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    run: Mapped["AssessmentRun"] = relationship(back_populates="questionnaire_responses")
