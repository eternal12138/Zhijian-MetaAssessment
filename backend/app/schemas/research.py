from datetime import date, datetime

from pydantic import Field, model_validator
from app.schemas.base import ApiModel as BaseModel


class TemplateOut(BaseModel):
    id: str
    template_key: str
    version: str
    kind: str
    content: str
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class TemplateUpdateIn(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    kind: str = Field(pattern="^(prompt|scoring|intervention)$")
    content: str = Field(min_length=2, max_length=30000)


class TemplateAuditOut(BaseModel):
    id: str
    action: str
    template_key: str
    from_version: str | None = None
    to_version: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    created_at: datetime


class AnalysisStartIn(BaseModel):
    reanalyze: bool = False


class AnalysisJobOut(BaseModel):
    id: str
    run_id: str
    status: str
    progress: int
    error_message: str
    result_profile_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    model_config = {"from_attributes": True}


class CodingReviewerOut(BaseModel):
    id: str
    username: str
    name: str
    role: str


class CodingBatchCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    reviewer_a_id: str
    reviewer_b_id: str
    adjudicator_id: str
    run_ids: list[str] = Field(default_factory=list, max_length=1000)
    class_groups: list[str] = Field(default_factory=list, max_length=100)
    user_ids: list[str] = Field(default_factory=list, max_length=1000)
    task_ids: list[str] = Field(default_factory=list, max_length=100)
    completed_from: date | None = None
    completed_to: date | None = None
    exclude_previously_batched: bool = False
    allow_unreviewed_candidates: bool = False

    @model_validator(mode="after")
    def validate_date_range(self):
        if (
            self.completed_from is not None
            and self.completed_to is not None
            and self.completed_from > self.completed_to
        ):
            raise ValueError("测评开始日期不能晚于结束日期")
        return self


class CodingBatchScopeIn(BaseModel):
    run_ids: list[str] = Field(default_factory=list, max_length=1000)
    class_groups: list[str] = Field(default_factory=list, max_length=100)
    user_ids: list[str] = Field(default_factory=list, max_length=1000)
    task_ids: list[str] = Field(default_factory=list, max_length=100)
    completed_from: date | None = None
    completed_to: date | None = None
    exclude_previously_batched: bool = False

    @model_validator(mode="after")
    def validate_date_range(self):
        if (
            self.completed_from is not None
            and self.completed_to is not None
            and self.completed_from > self.completed_to
        ):
            raise ValueError("测评开始日期不能晚于结束日期")
        return self


class CodingScopeStudentOut(BaseModel):
    id: str
    username: str
    name: str
    class_group: str | None


class CodingScopeTaskOut(BaseModel):
    id: str
    title: str
    protocol_order: int


class CodingBatchScopeOptionsOut(BaseModel):
    class_groups: list[str]
    students: list[CodingScopeStudentOut]
    tasks: list[CodingScopeTaskOut]
    earliest_completed_at: datetime | None
    latest_completed_at: datetime | None
    transcript_segment_count: int = 0
    coding_ready_segment_count: int = 0


class CodingBatchPreviewOut(BaseModel):
    student_count: int
    run_count: int
    session_count: int
    segment_count: int
    transcript_segment_count: int = 0
    coding_ready_segment_count: int = 0
    unreviewed_candidate_count: int = 0
    previously_batched_segment_count: int
    selected_students: list[CodingScopeStudentOut]


class CodingBatchAssignmentIn(BaseModel):
    reviewer_a_id: str
    reviewer_b_id: str
    adjudicator_id: str


class CodingBatchOut(BaseModel):
    id: str
    name: str
    status: str
    reviewer_a_id: str
    reviewer_a_name: str
    reviewer_b_id: str
    reviewer_b_name: str
    adjudicator_id: str
    adjudicator_name: str
    rubric_version: str
    scope_filter: dict | None
    scope_summary: dict | None
    unit_count: int
    resolved_count: int
    disputed_count: int
    reviewer_a_completed: int
    reviewer_b_completed: int
    created_at: datetime
    completed_at: datetime | None


class CodingUnitAssignmentOut(BaseModel):
    segment_id: str
    unit_id: str
    batch_id: str
    batch_name: str
    session_id: str
    run_id: str | None
    task_id: str
    audio_id: str | None
    participant_id: str | None
    sequence_no: int
    segment: str
    raw_text: str
    clean_text: str
    context_before: str
    context_after: str
    started_at_ms: int
    ended_at_ms: int
    reviewer_slot: str
    annotation_status: str
    current_expert_label: str | None
    current_note: str
    annotation_created_at: datetime | None
    annotation_updated_at: datetime | None
    completed_units: int
    total_units: int


class CodingUnitAnnotationIn(BaseModel):
    dimension: str | None = Field(
        ...,
        pattern="^(NON_META|MONITORING|REGULATION|EVALUATION|monitoring|controlDebugging|evaluation)$",
    )
    note: str = Field(default="", max_length=2000)


class CodingUnitAnnotationOut(BaseModel):
    id: str
    unit_id: str
    reviewer_slot: str
    dimension: str | None
    note: str
    created_at: datetime
    model_config = {"from_attributes": True}


class CodingUnitAdjudicationIn(CodingUnitAnnotationIn):
    dimension: str = Field(
        pattern="^(monitoring|regulation|evaluation)$"
    )
    note: str = Field(min_length=1, max_length=2000)


class CodingUnitDisagreementOut(BaseModel):
    segment_id: str
    unit_id: str
    batch_id: str
    batch_name: str
    session_id: str
    run_id: str | None
    task_id: str
    audio_id: str | None
    participant_id: str | None
    sequence_no: int
    segment: str
    raw_text: str
    clean_text: str
    context_before: str
    context_after: str
    started_at_ms: int
    ended_at_ms: int
    annotations: list[dict]


class ExpertAnnotationIn(BaseModel):
    expert_label: str = Field(
        pattern="^(monitoring|regulation|evaluation)$"
    )
    note: str = Field(default="", max_length=2000)


class ExpertAnnotationOut(BaseModel):
    id: str
    segment_id: str
    expert_id: str
    expert_label: str
    reviewer_slot: str
    note: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ExportJobOut(BaseModel):
    id: str
    status: str
    export_type: str
    row_count: int
    progress: int = 0
    error_message: str
    download_url: str | None = None
    created_at: datetime
    completed_at: datetime | None
    model_config = {"from_attributes": True}


class AudioTranscriptExportIn(BaseModel):
    mode: str = Field(default="all", pattern="^(all|incremental|accepted_only)$")
    include_audio: bool = True
    acknowledge_incomplete_review: bool = False


class AudioTranscriptExportPreviewOut(BaseModel):
    completed_session_count: int
    candidate_session_count: int
    sessions_without_candidates: int
    candidate_total: int
    accepted_count: int
    rejected_count: int
    pending_count: int
    review_complete: bool
    previous_export_at: datetime | None = None
    previous_review_complete: bool | None = None
    newly_reviewed_count: int = 0
    newly_accepted_count: int = 0
    incremental_session_count: int = 0


class ExportDownloadTicketOut(BaseModel):
    url: str
    expires: int
    filename: str


class ReportWorkflowIn(BaseModel):
    note: str = Field(default="", max_length=1000)


class BulkReportPublishIn(ReportWorkflowIn):
    report_ids: list[str] = Field(min_length=1, max_length=100)


class QualityCheckOut(BaseModel):
    key: str
    label: str
    status: str
    message: str


class RunQualityOut(BaseModel):
    run_id: str
    user_id: str
    username: str
    name: str
    class_group: str | None
    completed_at: datetime | None
    protocol_version: str
    automatic_status: str
    effective_status: str
    decision: str
    decision_reason: str
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    checks: list[QualityCheckOut]


class RunQualityDecisionIn(BaseModel):
    decision: str = Field(pattern="^(automatic|included|excluded)$")
    reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_reason(self):
        if self.decision != "automatic" and len(self.reason.strip()) < 5:
            raise ValueError("人工纳入或排除必须填写至少 5 个字的依据")
        return self
