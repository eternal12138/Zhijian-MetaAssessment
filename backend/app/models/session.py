"""
测评会话模型 - 对话记录与 AI 编码
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    String, Text, Integer, BigInteger, Float, Enum, DateTime,
    ForeignKey, Index, UniqueConstraint, func, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AssessmentSession(Base):
    """测评会话"""
    __tablename__ = "assessment_sessions"
    __table_args__ = (
        Index("ix_sessions_status_started", "status", "start_time", "id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessment_tasks.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assessment_runs.id"), nullable=True, index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        Enum("preparation", "in_progress", "paused", "completed", "abandoned", name="session_status"),
        nullable=False, default="preparation"
    )
    start_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    elapsed_minutes: Mapped[int] = mapped_column(Integer, default=0)
    ai_agent_version: Mapped[str] = mapped_column(String(32), default="0.2.0")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    model_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 关联
    user: Mapped["User"] = relationship(back_populates="sessions")
    task: Mapped["AssessmentTask"] = relationship(back_populates="sessions")
    run: Mapped["AssessmentRun | None"] = relationship(back_populates="sessions")
    dialogue_turns: Mapped[list["DialogueTurn"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    coded_segments: Mapped[list["CodedSegment"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    audio_chunks: Mapped[list["AudioChunk"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    interaction_events: Mapped[list["InteractionEvent"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    asr_jobs: Mapped[list["AsrJob"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    transcript_versions: Mapped[list["TranscriptVersion"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    report: Mapped["MetacognitiveProfile | None"] = relationship(back_populates="session", uselist=False)


class DialogueTurn(Base):
    """单条对话记录"""
    __tablename__ = "dialogue_turns"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessment_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("agent", "user", "system", name="dialogue_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    audio_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    emotion_features: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    session: Mapped["AssessmentSession"] = relationship(back_populates="dialogue_turns")


class CodedSegment(Base):
    """AI 编码后的对话片段"""
    __tablename__ = "coded_segments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessment_sessions.id"), nullable=False)
    turn_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("dialogue_turns.id"), nullable=True
    )
    transcript_segment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transcript_segments.id"), nullable=True, index=True
    )
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[str | None] = mapped_column(
        Enum("monitoring", "controlDebugging", "evaluation", name="coded_dimension"), nullable=True
    )
    scale_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    coded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    needs_review: Mapped[bool] = mapped_column(default=False)
    human_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_method: Mapped[str] = mapped_column(String(32), default="rule")
    rubric_version: Mapped[str] = mapped_column(String(32), default="2026.1")

    session: Mapped["AssessmentSession"] = relationship(back_populates="coded_segments")
    transcript_segment: Mapped["TranscriptSegment | None"] = relationship()


class AudioChunk(Base):
    """浏览器录音产生的分片元数据，文件本体保存到受控存储目录。"""
    __tablename__ = "audio_chunks"
    __table_args__ = (
        UniqueConstraint("session_id", "chunk_index", name="uq_audio_chunk_session_index"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_sessions.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    mime_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    ended_at_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["AssessmentSession"] = relationship(back_populates="audio_chunks")


class TranscriptSegment(Base):
    """浏览器实时识别得到的最终转录片段。"""
    __tablename__ = "transcript_segments"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "client_segment_id",
            name="uq_transcript_session_client_id",
        ),
        UniqueConstraint(
            "transcript_version_id", "segment_no",
            name="uq_transcript_version_segment_no",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_sessions.id"), nullable=False
    )
    client_segment_id: Mapped[str] = mapped_column(String(96), nullable=False)
    transcript_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("transcript_versions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    segment_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    started_at_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    ended_at_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    is_final: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String(32), default="browser")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["AssessmentSession"] = relationship(back_populates="transcript_segments")
    transcript_version: Mapped["TranscriptVersion | None"] = relationship(
        back_populates="segments"
    )


class InteractionEvent(Base):
    """测评过程中可审计、可重放的客户端交互事件。"""
    __tablename__ = "interaction_events"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "client_event_id",
            name="uq_interaction_event_session_client_id",
        ),
        Index(
            "idx_interaction_events_timeline",
            "session_id", "sequence_no", "occurred_at_ms",
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
    client_event_id: Mapped[str] = mapped_column(String(96), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    occurred_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    client_timestamp_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="browser")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["AssessmentSession"] = relationship(back_populates="interaction_events")
