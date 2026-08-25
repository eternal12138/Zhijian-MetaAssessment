"""User-facing, privacy-safe in-app notifications."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    event_key: Mapped[str | None] = mapped_column(
        String(160), unique=True, nullable=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_url: Mapped[str] = mapped_column(String(512), nullable=False, default="/")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
