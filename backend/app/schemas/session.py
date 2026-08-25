"""会话 & 对话相关 schemas"""
import json
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator
from app.schemas.base import ApiModel as BaseModel


InteractionEventType = Literal[
    "task_entered",
    "recording_started",
    "recording_paused",
    "recording_resumed",
    "recording_stopped",
    "speech_started",
    "speech_stopped",
    "transcript_final",
    "silence_threshold_reached",
    "neutral_prompt_started",
    "neutral_prompt_finished",
    "neutral_prompt_interrupted",
    "audio_chunk_uploaded",
    "session_submitted",
    "transfer_failed",
    "realtime_transcription_unavailable",
    "assessment_tool_used",
    "narration_started",
    "narration_finished",
    "narration_fallback",
]


class EmotionFeatures(BaseModel):
    emotion: str = "neutral"
    speech_rate: float = 0.0
    pause_count: int = 0
    avg_pause_duration: float = 0.0
    pitch_variation: float = 0.0


class DialogueTurnIn(BaseModel):
    content: str
    audio_url: str | None = None
    emotion_features: EmotionFeatures | None = None


class DialogueTurnOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    audio_url: str | None = None
    timestamp: int
    emotion_features: dict | None = None

    model_config = {"from_attributes": True}


class AudioChunkOut(BaseModel):
    id: str
    session_id: str
    chunk_index: int
    mime_type: str
    size_bytes: int
    started_at_ms: int
    ended_at_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TranscriptSegmentIn(BaseModel):
    client_segment_id: str = Field(min_length=1, max_length=96)
    text: str = Field(min_length=1, max_length=20_000)
    started_at_ms: int = Field(default=0, ge=0)
    ended_at_ms: int = Field(default=0, ge=0)
    is_final: bool = True
    source: str = Field(default="browser", max_length=32)


class TranscriptBatchIn(BaseModel):
    segments: list[TranscriptSegmentIn] = Field(min_length=1, max_length=100)


class TranscriptSegmentOut(BaseModel):
    id: str
    session_id: str
    client_segment_id: str
    transcript_version_id: str | None = None
    segment_no: int | None = None
    text: str
    started_at_ms: int
    ended_at_ms: int
    is_final: bool
    source: str
    confidence: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class InteractionEventIn(BaseModel):
    client_event_id: str = Field(min_length=1, max_length=96)
    sequence_no: int = Field(ge=0, le=10_000_000)
    event_type: InteractionEventType
    occurred_at_ms: int = Field(default=0, ge=0, le=24 * 60 * 60 * 1000)
    client_timestamp_ms: int = Field(ge=0)
    payload: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload_size(self):
        serialized = json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > 8 * 1024:
            raise ValueError("事件载荷不能超过 8 KB")
        return self


class InteractionEventBatchIn(BaseModel):
    events: list[InteractionEventIn] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_client_ids(self):
        client_ids = [item.client_event_id for item in self.events]
        if len(client_ids) != len(set(client_ids)):
            raise ValueError("同一批次不能包含重复事件 ID")
        return self


class InteractionEventOut(BaseModel):
    id: str
    session_id: str
    client_event_id: str
    sequence_no: int
    event_type: str
    occurred_at_ms: int
    client_timestamp_ms: int
    source: str
    payload: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionCompleteIn(BaseModel):
    elapsed_seconds: int = Field(default=0, ge=0, le=24 * 60 * 60)
    expected_audio_chunks: int = Field(default=0, ge=0)
    expected_transcript_segments: int = Field(default=0, ge=0)


class CodedSegmentOut(BaseModel):
    id: str
    session_id: str
    turn_id: str
    segment: str
    dimension: str | None = None
    scale_item_id: str | None = None
    score: int | None = None
    reason: str
    confidence: float
    coded_at: datetime
    needs_review: bool
    human_score: int | None = None
    review_note: str | None = None

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: str
    user_id: str
    task_id: str
    run_id: str | None = None
    sequence_no: int = 1
    status: str
    start_time: datetime
    end_time: datetime | None = None
    elapsed_minutes: int
    ai_agent_version: str
    model_id: str
    model_params: dict | None = None
    dialogue_turns: list[DialogueTurnOut] = []
    coded_segments: list[CodedSegmentOut] = []
    audio_chunks: list[AudioChunkOut] = []
    transcript_segments: list[TranscriptSegmentOut] = []
    interaction_events: list[InteractionEventOut] = []

    model_config = {"from_attributes": True}


class SessionStart(BaseModel):
    task_id: str


class AgentResponse(BaseModel):
    """AI Agent 回复"""
    message: str
    coded_segment: CodedSegmentOut | None = None
    session_status: str
