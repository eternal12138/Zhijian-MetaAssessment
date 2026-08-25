from datetime import datetime

from pydantic import Field, field_validator, model_validator

from app.schemas.base import ApiModel as BaseModel


class ExtractionJobOut(BaseModel):
    id: str
    session_id: str
    transcript_version_id: str
    status: str
    provider: str
    model: str
    extractor_version: str
    prompt_version: str
    generation_no: int = 1
    supersedes_job_id: str | None = None
    retry_count: int
    max_retries: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    review_lock_user_id: str | None = None
    review_lock_acquired_at: datetime | None = None
    review_lock_expires_at: datetime | None = None
    model_config = {"from_attributes": True}


class ExtractionBatchRerunIn(BaseModel):
    session_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("session_ids")
    @classmethod
    def unique_session_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if not normalized:
            raise ValueError("至少选择一条测评任务记录")
        if len(set(normalized)) != len(normalized):
            raise ValueError("测评任务记录不能重复选择")
        return normalized


class ExtractionBatchRerunItemOut(BaseModel):
    session_id: str
    status: str
    message: str
    job: ExtractionJobOut | None = None


class ExtractionBatchRerunOut(BaseModel):
    requested: int
    created: int
    skipped: int
    failed: int
    items: list[ExtractionBatchRerunItemOut]


class ExtractionJobStatusOut(BaseModel):
    id: str
    session_id: str
    status: str
    generation_no: int
    retry_count: int
    max_retries: int
    candidate_count: int = 0
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ExtractionJobStatusBatchIn(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("job_ids")
    @classmethod
    def unique_job_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if not normalized:
            raise ValueError("至少需要查询一个抽取任务")
        if len(set(normalized)) != len(normalized):
            raise ValueError("抽取任务不能重复")
        return normalized


class ExtractionJobStatusBatchOut(BaseModel):
    items: list[ExtractionJobStatusOut]


class ExtractionCandidateOut(BaseModel):
    id: str
    extraction_job_id: str
    source_transcript_segment_id: str | None
    sequence_no: int
    source_type: str
    review_status: str
    raw_asr_text: str
    original_text: str
    clean_text: str
    char_start: int | None
    char_end: int | None
    started_at_ms: int
    ended_at_ms: int
    reviewer_id: str | None
    review_note: str
    reviewed_at: datetime | None
    updated_at: datetime
    is_low_risk: bool = False
    classifier_version: str | None = None
    predicted_label: int | None = None
    predicted_dimension: str | None = None
    prediction_confidence: float | None = None
    prediction_probabilities: dict | None = None
    classified_at: datetime | None = None
    classification_error: str = ""
    classification_status: str = "pending_classification"
    prediction_source: str | None = None
    model_config = {"from_attributes": True}


class ExtractionQueueItemOut(BaseModel):
    session_id: str
    run_id: str | None
    user_id: str
    user_name: str
    username: str
    class_group: str | None
    task_id: str
    task_title: str
    sequence_no: int
    completed_at: datetime | None
    completed_at_source: str
    transcript_version_no: int | None
    transcript_source: str | None
    asr_status: str
    asr_error_code: str | None
    asr_error_message: str | None
    audio_available: bool
    job: ExtractionJobOut | None
    candidate_count: int
    pending_count: int


class ExtractionQueuePageOut(BaseModel):
    items: list[ExtractionQueueItemOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    class_groups: list[str]
    tasks: list[dict]
    statuses: list[str]


class TranscriptEvidenceSegmentOut(BaseModel):
    id: str
    segment_no: int | None
    text: str
    started_at_ms: int
    ended_at_ms: int
    model_config = {"from_attributes": True}


class ExtractionReviewDetailOut(BaseModel):
    session_id: str
    run_id: str | None
    user_id: str
    user_name: str
    username: str
    task_id: str
    task_title: str
    sequence_no: int
    transcript_version_id: str | None
    transcript_version_no: int | None
    transcript_source: str | None
    full_text: str
    audio_available: bool
    asr_status: str
    asr_error_code: str | None
    asr_error_message: str | None
    job: ExtractionJobOut | None
    job_history: list[ExtractionJobOut] = Field(default_factory=list)
    segments: list[TranscriptEvidenceSegmentOut]
    candidates: list[ExtractionCandidateOut]
    candidate_total: int = 0
    candidate_page: int = 1
    candidate_page_size: int = 10
    candidate_total_pages: int = 1
    pending_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    locked_by_current_user: bool = False
    lock_owner_name: str | None = None
    lock_expires_at: datetime | None = None


class CandidateReviewIn(BaseModel):
    review_status: str = Field(pattern="^(accepted|rejected)$")
    original_text: str = Field(min_length=1, max_length=4000)
    clean_text: str = Field(min_length=1, max_length=4000)
    review_note: str = Field(default="", max_length=2000)
    expected_updated_at: datetime | None = None


class CandidateCreateIn(BaseModel):
    source_transcript_segment_id: str | None = None
    original_text: str = Field(min_length=1, max_length=4000)
    clean_text: str = Field(min_length=1, max_length=4000)
    started_at_ms: int = Field(default=0, ge=0)
    ended_at_ms: int = Field(default=0, ge=0)
    review_note: str = Field(default="人工补充遗漏", max_length=2000)

    @model_validator(mode="after")
    def validate_timeline(self):
        if self.ended_at_ms and self.ended_at_ms < self.started_at_ms:
            raise ValueError("结束时间不能早于开始时间")
        return self


class ReviewLeaseOut(BaseModel):
    acquired: bool
    locked_by_current_user: bool
    lock_owner_name: str | None = None
    lock_expires_at: datetime | None = None


class BulkAcceptOut(BaseModel):
    accepted: int
    skipped: int
    skipped_candidate_ids: list[str] = Field(default_factory=list)


class ReviewAudioTicketOut(BaseModel):
    url: str
    expires: int


class ReviewAudioWaveformOut(BaseModel):
    duration_seconds: float
    peaks: list[float] = Field(default_factory=list)


class CandidateRevisionOut(BaseModel):
    id: str
    candidate_id: str
    extraction_job_id: str
    action: str
    actor_id: str | None
    actor_name: str | None = None
    before_snapshot: dict | None
    after_snapshot: dict | None
    created_at: datetime
    model_config = {"from_attributes": True}
