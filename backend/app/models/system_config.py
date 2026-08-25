"""
系统配置表 —— 存储可编辑的提示词模板等
"""
from datetime import datetime
import uuid

from sqlalchemy import String, Text, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    config_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    config_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SystemConfigHistory(Base):
    """Encrypted point-in-time snapshots for safe administrator rollback."""

    __tablename__ = "system_config_history"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    config_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    config_value: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True, nullable=False
    )
