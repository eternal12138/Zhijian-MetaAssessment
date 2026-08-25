"""
量表模型 - 元认知量表维度组与条目
"""
import uuid
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ScaleDimensionGroup(Base):
    """量表维度组（如 Zepeda 三维度）"""
    __tablename__ = "scale_dimension_groups"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessment_tasks.id"), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    task: Mapped["AssessmentTask"] = relationship(back_populates="dimension_groups")
    items: Mapped[list["ScaleItem"]] = relationship(back_populates="group", cascade="all, delete-orphan")


class ScaleItem(Base):
    """量表条目"""
    __tablename__ = "scale_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("scale_dimension_groups.id"), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    self_report_text: Mapped[str] = mapped_column(Text, nullable=False)
    observation_text: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON array string")
    scale_min: Mapped[int] = mapped_column(Integer, default=1)
    scale_max: Mapped[int] = mapped_column(Integer, default=7)
    scoring_rubric: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="")
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    group: Mapped["ScaleDimensionGroup"] = relationship(back_populates="items")
