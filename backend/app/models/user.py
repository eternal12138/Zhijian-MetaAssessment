"""
用户模型 - 学生 / 教师 / 管理员
"""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("student", "teacher", "admin", name="user_role"), nullable=False, default="student"
    )
    avatar_text: Mapped[str] = mapped_column(String(8), default="用")
    class_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    can_manage_users: Mapped[bool] = mapped_column(default=False)          # 超管权限
    managed_classes: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 教师管理的班级，逗号分隔
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # 关联
    sessions: Mapped[list["AssessmentSession"]] = relationship(back_populates="user")
    reports: Mapped[list["MetacognitiveProfile"]] = relationship(
        back_populates="user",
        foreign_keys="MetacognitiveProfile.user_id",
    )
    published_tasks: Mapped[list["AssessmentTask"]] = relationship(
        back_populates="publisher", foreign_keys="AssessmentTask.publisher_id"
    )
