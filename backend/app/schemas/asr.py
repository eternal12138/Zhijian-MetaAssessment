"""服务端权威 ASR API schemas。"""
from datetime import datetime

from pydantic import Field, model_validator
from app.schemas.base import ApiModel as BaseModel


class AsrJobOut(BaseModel):
    id: str
    session_id: str
    provider: str
    model: str
    config_version: str
    status: str
    expected_chunk_count: int
    audio_duration_ms: int | None = None
    language: str
    retry_count: int
    max_retries: int
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class TranscriptVersionSegmentOut(BaseModel):
    id: str
    segment_no: int | None = None
    text: str
    started_at_ms: int
    ended_at_ms: int
    confidence: float | None = None

    model_config = {"from_attributes": True}


class TranscriptVersionOut(BaseModel):
    id: str
    session_id: str
    asr_job_id: str | None = None
    version_no: int
    source: str
    status: str
    is_authoritative: bool
    language: str
    provider: str | None = None
    model: str | None = None
    full_text: str
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    segments: list[TranscriptVersionSegmentOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AsrSessionStatusOut(BaseModel):
    job: AsrJobOut | None = None
    authoritative_version: TranscriptVersionOut | None = None


class AsrBatchRetryIn(BaseModel):
    session_ids: list[str] = Field(min_length=1, max_length=200)


class AsrBatchRetryOut(BaseModel):
    processed: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class AsrReviewQueueItemOut(BaseModel):
    session_id: str
    run_id: str | None = None
    task_id: str
    sequence_no: int
    user_id: str
    user_name: str
    class_group: str | None = None
    job: AsrJobOut
    authoritative_version_no: int | None = None
    authoritative_source: str | None = None


class TranscriptCorrectionSegmentIn(BaseModel):
    segment_no: int = Field(ge=0, le=100_000)
    text: str = Field(min_length=1, max_length=20_000)
    started_at_ms: int = Field(ge=0, le=24 * 60 * 60 * 1000)
    ended_at_ms: int = Field(ge=0, le=24 * 60 * 60 * 1000)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.ended_at_ms < self.started_at_ms:
            raise ValueError("片段结束时间不能早于开始时间")
        return self


class TranscriptCorrectionIn(BaseModel):
    segments: list[TranscriptCorrectionSegmentIn] = Field(min_length=1, max_length=5_000)

    @model_validator(mode="after")
    def validate_segment_numbers(self):
        numbers = [item.segment_no for item in self.segments]
        if len(numbers) != len(set(numbers)):
            raise ValueError("片段序号不能重复")
        return self
