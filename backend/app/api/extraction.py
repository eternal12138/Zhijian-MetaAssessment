"""Human validation workflow for high-recall metacognitive candidates."""
from __future__ import annotations

import asyncio
import logging
import math
import time
import wave
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.config import get_settings
from app.core.security import can_access_user, get_current_user
from app.core.time import utc_now_naive
from app.database import get_db
from app.models.asr import AsrJob, TranscriptVersion
from app.models.extraction import ExtractionCandidate, ExtractionCandidateRevision, ExtractionJob
from app.models.protocol import AssessmentRun
from app.models.session import AssessmentSession, TranscriptSegment
from app.models.task import AssessmentTask
from app.models.user import User
from app.models.research import AuditLog
from app.schemas.extraction import (
    BulkAcceptOut, CandidateCreateIn, CandidateReviewIn, CandidateRevisionOut, ExtractionCandidateOut,
    ExtractionBatchRerunIn, ExtractionBatchRerunItemOut, ExtractionBatchRerunOut,
    ExtractionJobOut, ExtractionJobStatusBatchIn, ExtractionJobStatusBatchOut,
    ExtractionJobStatusOut, ExtractionQueueItemOut, ExtractionQueuePageOut,
    ExtractionReviewDetailOut, ReviewAudioTicketOut, ReviewAudioWaveformOut,
    ReviewLeaseOut, TranscriptEvidenceSegmentOut,
)
from app.services.extraction_service import ExtractionAlreadyRunningError, enqueue_extraction
from app.services.metacognition_extractor.extractor import is_conservative_derivation
from app.services.model_inference import classify_candidates, invalidate_candidate_prediction
from app.services.review_audio import sign_review_audio, verify_review_audio, wav_waveform

router = APIRouter(prefix="/research/extraction", tags=["元认知候选复核"])
logger = logging.getLogger(__name__)
settings = get_settings()
REVIEW_LEASE_MINUTES = 5
REVIEW_AUDIO_TTL_SECONDS = 15 * 60
PIPELINE_STATUSES = [
    "asr_not_created", "asr_processing", "asr_failed", "asr_waiting_configuration",
    "ready_for_extraction", "extraction_queued", "extraction_running",
    "extraction_retry_wait", "extraction_reviewing", "extraction_reviewed",
    "extraction_failed", "extraction_superseded",
]


def _require_reviewer(user: User) -> None:
    if user.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="仅教师或管理员可复核候选片段")


async def _session_context(session_id: str, user: User, db: AsyncSession):
    row = (await db.execute(
        select(AssessmentSession, User, AssessmentTask)
        .join(User, User.id == AssessmentSession.user_id)
        .join(AssessmentTask, AssessmentTask.id == AssessmentSession.task_id)
        .where(AssessmentSession.id == session_id)
    )).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="测评会话不存在")
    session, owner, task = row
    if not can_access_user(user, owner):
        raise HTTPException(status_code=403, detail="无权访问该测评会话")
    return session, owner, task


async def _context(session_id: str, user: User, db: AsyncSession):
    session, owner, task = await _session_context(session_id, user, db)
    version = await db.scalar(
        select(TranscriptVersion)
        .where(
            TranscriptVersion.session_id == session.id,
            TranscriptVersion.is_authoritative.is_(True),
        )
        .options(selectinload(TranscriptVersion.segments))
        .order_by(TranscriptVersion.version_no.desc()).limit(1)
    )
    if version is None:
        raise HTTPException(status_code=409, detail="该会话尚无权威转录")
    return session, owner, task, version


async def _latest_job(version_id: str, db: AsyncSession) -> ExtractionJob | None:
    return await db.scalar(
        select(ExtractionJob)
        .where(ExtractionJob.transcript_version_id == version_id)
        .options(selectinload(ExtractionJob.candidates))
        .order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc()).limit(1)
    )


async def _audio_job(session_id: str, db: AsyncSession) -> AsrJob | None:
    return await db.scalar(
        select(AsrJob)
        .where(
            AsrJob.session_id == session_id,
            AsrJob.canonical_audio_path.is_not(None),
        )
        .order_by(AsrJob.finished_at.desc(), AsrJob.created_at.desc()).limit(1)
    )


def _review_audio_path(job: AsrJob):
    if not job.canonical_audio_path:
        raise HTTPException(status_code=404, detail="该会话尚无可播放的完整录音")
    root = settings.audio_upload_path.resolve()
    audio_path = (root / job.canonical_audio_path).resolve()
    try:
        audio_path.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=403, detail="录音路径不安全") from error
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="录音文件不存在")
    return audio_path


def _pipeline_status(
    version: TranscriptVersion | None,
    asr_job: AsrJob | None,
    job: ExtractionJob | None,
) -> str:
    if version is None:
        if asr_job is None:
            return "asr_not_created"
        if asr_job.status == "failed":
            return "asr_failed"
        if asr_job.status == "waiting_configuration":
            return "asr_waiting_configuration"
        return "asr_processing"
    if job is None:
        return "ready_for_extraction"
    return f"extraction_{job.status}"


def _is_low_risk(candidate: ExtractionCandidate) -> bool:
    """Structural safety only; it is not a semantic confidence score."""
    original = candidate.original_text.strip()
    cleaned = candidate.clean_text.strip()
    classifier_safe = (
        candidate.predicted_label is None
        or (
            candidate.predicted_label in {1, 2, 3}
            and (candidate.prediction_confidence or 0) >= 0.85
        )
    )
    return bool(
        candidate.source_type == "llm"
        and candidate.review_status == "pending"
        and candidate.source_transcript_segment_id
        and original
        and cleaned
        and original in candidate.raw_asr_text
        and is_conservative_derivation(original, cleaned)
        and candidate.started_at_ms >= 0
        and candidate.ended_at_ms > candidate.started_at_ms
        and classifier_safe
    )


def _candidate_out(candidate: ExtractionCandidate) -> ExtractionCandidateOut:
    return ExtractionCandidateOut.model_validate(candidate).model_copy(
        update={"is_low_risk": _is_low_risk(candidate)}
    )


def _job_status_out(job: ExtractionJob, candidate_count: int) -> ExtractionJobStatusOut:
    return ExtractionJobStatusOut(
        id=job.id,
        session_id=job.session_id,
        status=job.status,
        generation_no=job.generation_no,
        retry_count=job.retry_count,
        max_retries=job.max_retries,
        candidate_count=candidate_count,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.post("/jobs/{job_id}/classify", response_model=list[ExtractionCandidateOut])
async def classify_job_candidates(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_reviewer(user)
    job = await db.scalar(
        select(ExtractionJob)
        .where(ExtractionJob.id == job_id)
        .options(selectinload(ExtractionJob.candidates))
    )
    if job is None:
        raise HTTPException(status_code=404, detail="候选抽取版本不存在")
    await _session_context(job.session_id, user, db)
    candidates = [
        candidate for candidate in job.candidates
        if candidate.review_status in {"accepted", "pending"} and candidate.clean_text.strip()
    ]
    if not candidates:
        raise HTTPException(status_code=409, detail="该抽取版本没有可分类的已接受或待复核候选")
    try:
        active = await classify_candidates(db, candidates)
    except Exception as error:
        # Keep the auditable pending/failure state written by the inference
        # service even though this manual action returns a conflict response.
        # Candidate text and human review fields are never modified here.
        await db.commit()
        raise HTTPException(status_code=409, detail=f"分类模型执行失败：{error}") from error
    if active is None:
        raise HTTPException(status_code=409, detail="尚未启用可用的分类模型")
    db.add(AuditLog(
        actor_id=user.id, action="model_training.classify_candidates",
        target_type="extraction_job", target_id=job.id,
        detail={"version": active.version, "candidate_count": len(candidates)},
    ))
    await db.flush()
    return [_candidate_out(candidate) for candidate in candidates]


async def _job_status_rows(
    job_ids: list[str], user: User, db: AsyncSession,
) -> list[ExtractionJobStatusOut]:
    candidate_count = (
        select(func.count(ExtractionCandidate.id))
        .where(ExtractionCandidate.extraction_job_id == ExtractionJob.id)
        .correlate(ExtractionJob)
        .scalar_subquery()
    )
    rows = (await db.execute(
        select(ExtractionJob, User, candidate_count.label("candidate_count"))
        .join(AssessmentSession, AssessmentSession.id == ExtractionJob.session_id)
        .join(User, User.id == AssessmentSession.user_id)
        .where(ExtractionJob.id.in_(job_ids))
        .options(
            defer(ExtractionJob.prompt_content),
            defer(ExtractionJob.raw_asr_text),
            defer(ExtractionJob.raw_response),
        )
    )).all()
    found = {job.id for job, _owner, _count in rows}
    if len(found) != len(set(job_ids)):
        raise HTTPException(status_code=404, detail="抽取任务不存在")
    output: dict[str, ExtractionJobStatusOut] = {}
    for job, owner, count in rows:
        if not can_access_user(user, owner):
            raise HTTPException(status_code=403, detail="无权查看该抽取任务")
        output[job.id] = _job_status_out(job, int(count or 0))
    return [output[job_id] for job_id in job_ids]


@router.get("/jobs/{job_id}/status", response_model=ExtractionJobStatusOut)
async def extraction_job_status(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_reviewer(user)
    return (await _job_status_rows([job_id], user, db))[0]


@router.post("/jobs/status", response_model=ExtractionJobStatusBatchOut)
async def extraction_job_status_batch(
    data: ExtractionJobStatusBatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_reviewer(user)
    return ExtractionJobStatusBatchOut(
        items=await _job_status_rows(data.job_ids, user, db)
    )


def _candidate_snapshot(candidate: ExtractionCandidate) -> dict:
    return {
        "original_text": candidate.original_text,
        "clean_text": candidate.clean_text,
        "review_status": candidate.review_status,
        "review_note": candidate.review_note,
        "started_at_ms": candidate.started_at_ms,
        "ended_at_ms": candidate.ended_at_ms,
    }


def _record_candidate_revision(
    db: AsyncSession,
    candidate: ExtractionCandidate,
    actor: User,
    action: str,
    before: dict | None,
) -> None:
    db.add(ExtractionCandidateRevision(
        candidate_id=candidate.id,
        extraction_job_id=candidate.extraction_job_id,
        session_id=candidate.session_id,
        actor_id=actor.id,
        action=action,
        before_snapshot=before,
        after_snapshot=_candidate_snapshot(candidate),
    ))


async def _lock_view(job: ExtractionJob | None, user: User, db: AsyncSession):
    if job is None:
        return False, None, None
    now = utc_now_naive()
    active = bool(job.review_lock_user_id and job.review_lock_expires_at and job.review_lock_expires_at > now)
    if not active:
        return False, None, None
    owner_name = await db.scalar(select(User.name).where(User.id == job.review_lock_user_id))
    return job.review_lock_user_id == user.id, owner_name, job.review_lock_expires_at


def _require_review_lock(job: ExtractionJob, user: User) -> None:
    now = utc_now_naive()
    if not (
        job.review_lock_user_id == user.id
        and job.review_lock_expires_at
        and job.review_lock_expires_at > now
    ):
        if job.review_lock_user_id and job.review_lock_expires_at and job.review_lock_expires_at > now:
            raise HTTPException(status_code=423, detail="该任务正由另一名复核员编辑，请稍后再试")
        raise HTTPException(status_code=409, detail="复核编辑权已过期，请重新获取后再保存")


@router.get("/queue", response_model=ExtractionQueuePageOut)
async def list_extraction_queue(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    keyword: str = Query(default="", max_length=100),
    class_group: str = Query(default="", max_length=100),
    task_id: str = Query(default="", max_length=160),
    status: str = Query(default="", max_length=48),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    managed_classes = [
        value.strip() for value in (user.managed_classes or "").split(",") if value.strip()
    ]
    access_scope = literal(True) if user.role == "admin" else or_(
        User.id == user.id,
        and_(User.role == "student", User.class_group.in_(managed_classes)),
    )

    latest_version_id = (
        select(TranscriptVersion.id)
        .where(
            TranscriptVersion.session_id == AssessmentSession.id,
            TranscriptVersion.is_authoritative.is_(True),
        )
        .order_by(TranscriptVersion.version_no.desc(), TranscriptVersion.id.desc())
        .limit(1).correlate(AssessmentSession).scalar_subquery()
    )
    latest_asr_id = (
        select(AsrJob.id).where(AsrJob.session_id == AssessmentSession.id)
        .order_by(AsrJob.created_at.desc(), AsrJob.id.desc())
        .limit(1).correlate(AssessmentSession).scalar_subquery()
    )
    latest_job_id = (
        select(ExtractionJob.id)
        .where(ExtractionJob.transcript_version_id == latest_version_id)
        .order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc())
        .limit(1).correlate(AssessmentSession).scalar_subquery()
    )
    candidate_count = (
        select(func.count(ExtractionCandidate.id))
        .where(ExtractionCandidate.extraction_job_id == latest_job_id)
        .correlate(AssessmentSession).scalar_subquery()
    )
    pending_count = (
        select(func.count(ExtractionCandidate.id))
        .where(
            ExtractionCandidate.extraction_job_id == latest_job_id,
            ExtractionCandidate.review_status == "pending",
        )
        .correlate(AssessmentSession).scalar_subquery()
    )
    pipeline_status = case(
        (
            TranscriptVersion.id.is_(None),
            case(
                (AsrJob.id.is_(None), literal("asr_not_created")),
                (AsrJob.status == "failed", literal("asr_failed")),
                (AsrJob.status == "waiting_configuration", literal("asr_waiting_configuration")),
                else_=literal("asr_processing"),
            ),
        ),
        (ExtractionJob.id.is_(None), literal("ready_for_extraction")),
        else_=literal("extraction_") + ExtractionJob.status,
    )
    base = (
        select(
            AssessmentSession, User, AssessmentTask, AssessmentRun,
            TranscriptVersion, AsrJob, ExtractionJob,
            candidate_count.label("candidate_count"), pending_count.label("pending_count"),
        )
        .join(User, User.id == AssessmentSession.user_id)
        .join(AssessmentTask, AssessmentTask.id == AssessmentSession.task_id)
        .outerjoin(AssessmentRun, AssessmentRun.id == AssessmentSession.run_id)
        .outerjoin(TranscriptVersion, TranscriptVersion.id == latest_version_id)
        .outerjoin(AsrJob, AsrJob.id == latest_asr_id)
        .outerjoin(ExtractionJob, ExtractionJob.id == latest_job_id)
    )
    conditions = [AssessmentSession.status == "completed", access_scope]
    normalized_keyword = keyword.strip()
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        conditions.append(or_(
            User.name.ilike(pattern), User.username.ilike(pattern),
            User.class_group.ilike(pattern), AssessmentTask.title.ilike(pattern),
        ))
    if class_group:
        conditions.append(User.class_group == class_group)
    if task_id:
        if task_id.startswith("title:"):
            conditions.append(AssessmentTask.title == task_id.removeprefix("title:"))
        else:
            conditions.append(AssessmentTask.id == task_id)
    if status:
        conditions.append(pipeline_status == status)

    base = base.where(*conditions)
    count_source = (
        select(AssessmentSession.id)
        .join(User, User.id == AssessmentSession.user_id)
        .join(AssessmentTask, AssessmentTask.id == AssessmentSession.task_id)
        .outerjoin(TranscriptVersion, TranscriptVersion.id == latest_version_id)
        .outerjoin(AsrJob, AsrJob.id == latest_asr_id)
        .outerjoin(ExtractionJob, ExtractionJob.id == latest_job_id)
        .where(*conditions)
    )
    count_query = select(func.count()).select_from(count_source.subquery())
    total = int(await db.scalar(count_query) or 0)
    total_pages = max(1, math.ceil(total / page_size))
    safe_page = min(page, total_pages)
    rows = (await db.execute(
        base.order_by(
            func.coalesce(
                AssessmentSession.end_time,
                AssessmentRun.completed_at,
                AssessmentSession.start_time,
            ).desc(),
            AssessmentSession.id.desc(),
        )
        .options(
            defer(TranscriptVersion.full_text),
            defer(TranscriptVersion.raw_response),
            defer(AsrJob.input_manifest),
            defer(ExtractionJob.prompt_content),
            defer(ExtractionJob.raw_asr_text),
            defer(ExtractionJob.raw_response),
        )
        .offset((safe_page - 1) * page_size).limit(page_size)
    )).all()

    output = [ExtractionQueueItemOut(
        session_id=session.id, run_id=session.run_id, user_id=owner.id,
        user_name=owner.name, username=owner.username, class_group=owner.class_group,
        task_id=task.id, task_title=task.title, sequence_no=session.sequence_no,
        completed_at=session.end_time or (run.completed_at if run else None) or session.start_time,
        completed_at_source=(
            "session_end" if session.end_time else
            "run_completed" if run and run.completed_at else
            "session_start_fallback"
        ),
        transcript_version_no=version.version_no if version else None,
        transcript_source=version.source if version else None,
        asr_status=asr_job.status if asr_job else "not_created",
        asr_error_code=asr_job.error_code if asr_job else None,
        asr_error_message=asr_job.error_message if asr_job else None,
        audio_available=bool(asr_job and asr_job.canonical_audio_path),
        job=job, candidate_count=int(candidate_total or 0),
        pending_count=int(pending_total or 0),
    ) for session, owner, task, run, version, asr_job, job, candidate_total, pending_total in rows]

    facet_base = (
        select(User.class_group, AssessmentTask.id, AssessmentTask.title)
        .join(AssessmentSession, AssessmentSession.user_id == User.id)
        .join(AssessmentTask, AssessmentTask.id == AssessmentSession.task_id)
        .where(AssessmentSession.status == "completed", access_scope)
        .distinct()
    )
    facet_rows = (await db.execute(facet_base)).all()
    class_groups = sorted({row.class_group for row in facet_rows if row.class_group})
    task_titles = sorted({row.title for row in facet_rows})
    return ExtractionQueuePageOut(
        items=output,
        total=total,
        page=safe_page,
        page_size=page_size,
        total_pages=total_pages,
        class_groups=class_groups,
        tasks=[{"id": f"title:{title}", "title": title} for title in task_titles],
        statuses=PIPELINE_STATUSES,
    )


@router.get("/sessions/{session_id}", response_model=ExtractionReviewDetailOut)
async def extraction_review_detail(
    session_id: str,
    job_id: str = Query(default="", max_length=36),
    candidate_page: int = Query(default=1, ge=1),
    candidate_page_size: int = Query(default=10, ge=5, le=50),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    session, owner, task = await _session_context(session_id, user, db)
    version = await db.scalar(
        select(TranscriptVersion)
        .where(
            TranscriptVersion.session_id == session.id,
            TranscriptVersion.is_authoritative.is_(True),
        )
        .options(selectinload(TranscriptVersion.segments))
        .options(defer(TranscriptVersion.raw_response))
        .order_by(TranscriptVersion.version_no.desc()).limit(1)
    )
    asr_job = await db.scalar(
        select(AsrJob).where(AsrJob.session_id == session.id)
        .options(defer(AsrJob.input_manifest))
        .order_by(AsrJob.created_at.desc(), AsrJob.id.desc()).limit(1)
    )
    job_history = list((await db.scalars(
        select(ExtractionJob).where(ExtractionJob.transcript_version_id == version.id)
        .options(
            defer(ExtractionJob.prompt_content),
            defer(ExtractionJob.raw_asr_text),
            defer(ExtractionJob.raw_response),
        )
        .order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc())
        .limit(50)
    )).all()) if version else []
    selected_job_id = job_id or (job_history[0].id if job_history else "")
    job = await db.scalar(
        select(ExtractionJob).where(
            ExtractionJob.id == selected_job_id,
            ExtractionJob.transcript_version_id == version.id,
        ).options(
            defer(ExtractionJob.prompt_content),
            defer(ExtractionJob.raw_asr_text),
            defer(ExtractionJob.raw_response),
        )
    ) if version and selected_job_id else None
    if job_id and job is None:
        raise HTTPException(status_code=404, detail="抽取历史版本不存在")
    candidate_total = 0
    pending_count = 0
    accepted_count = 0
    rejected_count = 0
    candidate_total_pages = 1
    safe_candidate_page = 1
    candidates: list[ExtractionCandidate] = []
    if job:
        status_rows = (await db.execute(
            select(ExtractionCandidate.review_status, func.count(ExtractionCandidate.id))
            .where(ExtractionCandidate.extraction_job_id == job.id)
            .group_by(ExtractionCandidate.review_status)
        )).all()
        status_counts = {status: int(count) for status, count in status_rows}
        pending_count = status_counts.get("pending", 0)
        accepted_count = status_counts.get("accepted", 0)
        rejected_count = status_counts.get("rejected", 0)
        candidate_total = pending_count + accepted_count + rejected_count
        candidate_total_pages = max(1, math.ceil(candidate_total / candidate_page_size))
        safe_candidate_page = min(candidate_page, candidate_total_pages)
        candidates = list((await db.scalars(
            select(ExtractionCandidate)
            .where(ExtractionCandidate.extraction_job_id == job.id)
            .order_by(ExtractionCandidate.sequence_no.asc(), ExtractionCandidate.id.asc())
            .offset((safe_candidate_page - 1) * candidate_page_size)
            .limit(candidate_page_size)
        )).all())

    locked_by_current_user, lock_owner_name, lock_expires_at = await _lock_view(job, user, db)
    return ExtractionReviewDetailOut(
        session_id=session.id, run_id=session.run_id, user_id=owner.id,
        user_name=owner.name, username=owner.username, task_id=task.id,
        task_title=task.title, sequence_no=session.sequence_no,
        transcript_version_id=version.id if version else None,
        transcript_version_no=version.version_no if version else None,
        transcript_source=version.source if version else None,
        full_text=version.full_text if version else "",
        audio_available=bool(asr_job and asr_job.canonical_audio_path),
        asr_status=asr_job.status if asr_job else "not_created",
        asr_error_code=asr_job.error_code if asr_job else None,
        asr_error_message=asr_job.error_message if asr_job else None,
        job=job,
        job_history=job_history,
        segments=[TranscriptEvidenceSegmentOut.model_validate(item) for item in version.segments] if version else [],
        candidates=[_candidate_out(item) for item in candidates],
        candidate_total=candidate_total,
        candidate_page=safe_candidate_page,
        candidate_page_size=candidate_page_size,
        candidate_total_pages=candidate_total_pages,
        pending_count=pending_count,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        locked_by_current_user=locked_by_current_user,
        lock_owner_name=lock_owner_name,
        lock_expires_at=lock_expires_at,
    )


@router.post("/sessions/{session_id}/lock", response_model=ReviewLeaseOut)
async def acquire_review_lock(
    session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    _session, _owner, _task, version = await _context(session_id, user, db)
    job = await db.scalar(
        select(ExtractionJob)
        .where(ExtractionJob.transcript_version_id == version.id)
        .order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc())
        .with_for_update().limit(1)
    )
    if job is None or job.status not in {"reviewing", "reviewed"}:
        raise HTTPException(status_code=409, detail="候选尚未生成，暂时不能获取复核编辑权")
    now = utc_now_naive()
    if (
        job.review_lock_user_id
        and job.review_lock_user_id != user.id
        and job.review_lock_expires_at
        and job.review_lock_expires_at > now
    ):
        owner_name = await db.scalar(select(User.name).where(User.id == job.review_lock_user_id))
        return ReviewLeaseOut(
            acquired=False, locked_by_current_user=False,
            lock_owner_name=owner_name, lock_expires_at=job.review_lock_expires_at,
        )
    job.review_lock_user_id = user.id
    job.review_lock_acquired_at = now
    job.review_lock_expires_at = now + timedelta(minutes=REVIEW_LEASE_MINUTES)
    await db.flush()
    return ReviewLeaseOut(
        acquired=True, locked_by_current_user=True,
        lock_owner_name=user.name, lock_expires_at=job.review_lock_expires_at,
    )


@router.post("/sessions/{session_id}/lock/renew", response_model=ReviewLeaseOut)
async def renew_review_lock(
    session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    _session, _owner, _task, version = await _context(session_id, user, db)
    job = await db.scalar(
        select(ExtractionJob).where(ExtractionJob.transcript_version_id == version.id)
        .order_by(ExtractionJob.created_at.desc()).with_for_update().limit(1)
    )
    if job is None:
        raise HTTPException(status_code=409, detail="候选抽取任务不存在")
    _require_review_lock(job, user)
    job.review_lock_expires_at = utc_now_naive() + timedelta(minutes=REVIEW_LEASE_MINUTES)
    await db.flush()
    return ReviewLeaseOut(
        acquired=True, locked_by_current_user=True,
        lock_owner_name=user.name, lock_expires_at=job.review_lock_expires_at,
    )


@router.delete("/sessions/{session_id}/lock", response_model=ReviewLeaseOut)
async def release_review_lock(
    session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    _session, _owner, _task, version = await _context(session_id, user, db)
    job = await db.scalar(
        select(ExtractionJob).where(ExtractionJob.transcript_version_id == version.id)
        .order_by(ExtractionJob.created_at.desc()).with_for_update().limit(1)
    )
    if job and job.review_lock_user_id == user.id:
        job.review_lock_user_id = None
        job.review_lock_acquired_at = None
        job.review_lock_expires_at = None
        await db.flush()
    return ReviewLeaseOut(acquired=False, locked_by_current_user=False)


@router.post("/sessions/{session_id}/enqueue", response_model=ExtractionJobOut)
async def enqueue_session_extraction(
    session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    _session, _owner, _task, version = await _context(session_id, user, db)
    job = await enqueue_extraction(version=version, db=db, requested_by=user.id)
    if job is None:
        raise HTTPException(status_code=409, detail="模型候选抽取功能尚未启用")
    if job.status in {"failed", "superseded"}:
        job.status = "queued"
        job.retry_count = 0
        job.error_code = None
        job.error_message = None
        job.completed_at = None
        await db.flush()
    return job


@router.post("/sessions/{session_id}/rerun", response_model=ExtractionJobOut)
async def rerun_session_extraction(
    session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    _session, _owner, _task, version = await _context(session_id, user, db)
    latest = await _latest_job(version.id, db)
    if latest and latest.status in {"queued", "running", "retry_wait"}:
        raise HTTPException(status_code=409, detail="当前抽取任务仍在处理中，不能重复提交")
    try:
        job = await enqueue_extraction(
            version=version, db=db, requested_by=user.id, force_new_generation=True
        )
    except ExtractionAlreadyRunningError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if job is None:
        raise HTTPException(status_code=409, detail="模型候选抽取功能尚未启用")
    db.add(AuditLog(
        actor_id=user.id, action="extraction.rerun", target_type="extraction_job",
        target_id=job.id, detail={
            "session_id": session_id,
            "generation_no": job.generation_no,
            "supersedes_job_id": job.supersedes_job_id,
            "prompt_version": job.prompt_version,
        },
    ))
    await db.flush()
    return job


@router.post("/sessions/batch-rerun", response_model=ExtractionBatchRerunOut)
async def batch_rerun_session_extraction(
    data: ExtractionBatchRerunIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create independent extraction generations without replacing old results."""
    _require_reviewer(user)
    items: list[ExtractionBatchRerunItemOut] = []

    # Stable ordering reduces deadlock risk when two administrators submit
    # overlapping batches at the same time.
    for session_id in sorted(data.session_ids):
        try:
            async with db.begin_nested():
                _session, _owner, _task, version = await _context(session_id, user, db)
                latest = await _latest_job(version.id, db)
                if latest is None:
                    items.append(ExtractionBatchRerunItemOut(
                        session_id=session_id,
                        status="skipped",
                        message="尚无历史抽取版本，请先执行首次候选抽取",
                    ))
                    continue
                if latest.status in {"queued", "running", "retry_wait"}:
                    items.append(ExtractionBatchRerunItemOut(
                        session_id=session_id,
                        status="skipped",
                        message="当前抽取任务仍在处理中",
                    ))
                    continue
                try:
                    job = await enqueue_extraction(
                        version=version,
                        db=db,
                        requested_by=user.id,
                        force_new_generation=True,
                    )
                except ExtractionAlreadyRunningError as error:
                    items.append(ExtractionBatchRerunItemOut(
                        session_id=session_id,
                        status="skipped",
                        message=str(error),
                    ))
                    continue
                if job is None:
                    items.append(ExtractionBatchRerunItemOut(
                        session_id=session_id,
                        status="failed",
                        message="模型候选抽取功能尚未启用或权威转录已不存在",
                    ))
                    continue
                db.add(AuditLog(
                    actor_id=user.id,
                    action="extraction.rerun",
                    target_type="extraction_job",
                    target_id=job.id,
                    detail={
                        "session_id": session_id,
                        "generation_no": job.generation_no,
                        "supersedes_job_id": job.supersedes_job_id,
                        "prompt_version": job.prompt_version,
                        "batch": True,
                    },
                ))
                await db.flush()
                items.append(ExtractionBatchRerunItemOut(
                    session_id=session_id,
                    status="created",
                    message=f"已创建抽取版本 V{job.generation_no}",
                    job=job,
                ))
        except HTTPException as error:
            # Access-control errors fail the whole request rather than exposing
            # whether an out-of-scope session exists.
            if error.status_code in {401, 403, 404}:
                raise
            items.append(ExtractionBatchRerunItemOut(
                session_id=session_id,
                status="failed",
                message=str(error.detail),
            ))
        except Exception:
            logger.exception(
                "Batch extraction rerun failed for session %s", session_id
            )
            items.append(ExtractionBatchRerunItemOut(
                session_id=session_id,
                status="failed",
                message="创建新抽取版本失败，请查看后端日志",
            ))

    created = sum(item.status == "created" for item in items)
    skipped = sum(item.status == "skipped" for item in items)
    failed = sum(item.status == "failed" for item in items)
    db.add(AuditLog(
        actor_id=user.id,
        action="extraction.batch_rerun",
        target_type="extraction_batch",
        target_id=None,
        detail={
            "session_ids": data.session_ids,
            "requested": len(data.session_ids),
            "created": created,
            "skipped": skipped,
            "failed": failed,
        },
    ))
    await db.flush()
    return ExtractionBatchRerunOut(
        requested=len(data.session_ids),
        created=created,
        skipped=skipped,
        failed=failed,
        items=items,
    )


@router.patch("/candidates/{candidate_id}", response_model=ExtractionCandidateOut)
async def review_candidate(
    candidate_id: str, data: CandidateReviewIn,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    candidate = await db.get(ExtractionCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="候选片段不存在")
    await _context(candidate.session_id, user, db)
    job = await db.get(ExtractionJob, candidate.extraction_job_id)
    if job is None:
        raise HTTPException(status_code=409, detail="候选抽取任务不存在")
    _require_review_lock(job, user)
    if data.expected_updated_at and candidate.updated_at != data.expected_updated_at.replace(tzinfo=None):
        raise HTTPException(status_code=409, detail="候选已被更新，请刷新后重新确认")
    before = _candidate_snapshot(candidate)
    candidate.original_text = data.original_text.strip()
    candidate.clean_text = data.clean_text.strip()
    candidate.review_status = data.review_status
    candidate.review_note = data.review_note.strip()
    candidate.reviewer_id = user.id
    candidate.reviewed_at = utc_now_naive()
    # Any human text change invalidates the former model output.  The next AI
    # evaluation must classify the reviewed text instead of displaying a stale
    # prediction made from the original AI candidate.
    if candidate.clean_text != before["clean_text"]:
        invalidate_candidate_prediction(candidate)
    _record_candidate_revision(db, candidate, user, f"review_{data.review_status}", before)
    await db.flush()
    await db.refresh(candidate)
    return _candidate_out(candidate)


@router.post("/sessions/{session_id}/candidates", response_model=ExtractionCandidateOut, status_code=201)
async def add_candidate(
    session_id: str, data: CandidateCreateIn,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    session, _owner, _task, version = await _context(session_id, user, db)
    job = await _latest_job(version.id, db)
    if job is None:
        job = await enqueue_extraction(version=version, db=db, requested_by=user.id)
        if job is None:
            raise HTTPException(status_code=409, detail="无法建立候选抽取任务")
        job.status = "reviewing"
        now = utc_now_naive()
        job.review_lock_user_id = user.id
        job.review_lock_acquired_at = now
        job.review_lock_expires_at = now + timedelta(minutes=REVIEW_LEASE_MINUTES)
    _require_review_lock(job, user)
    source = None
    if data.source_transcript_segment_id:
        source = await db.get(TranscriptSegment, data.source_transcript_segment_id)
        if source is None or source.transcript_version_id != version.id:
            raise HTTPException(status_code=422, detail="来源转录片段不属于当前权威版本")
    next_no = (await db.scalar(select(func.max(ExtractionCandidate.sequence_no)).where(
        ExtractionCandidate.extraction_job_id == job.id
    )) or 0) + 1
    candidate = ExtractionCandidate(
        extraction_job_id=job.id, source_transcript_segment_id=source.id if source else None,
        session_id=session.id, run_id=session.run_id, user_id=session.user_id,
        task_id=session.task_id, sequence_no=next_no, source_type="human",
        review_status="accepted", raw_asr_text=source.text if source else version.full_text,
        original_text=data.original_text.strip(), clean_text=data.clean_text.strip(),
        started_at_ms=data.started_at_ms or (source.started_at_ms if source else 0),
        ended_at_ms=data.ended_at_ms or (source.ended_at_ms if source else 0),
        reviewer_id=user.id, review_note=data.review_note.strip(), reviewed_at=utc_now_naive(),
    )
    db.add(candidate)
    await db.flush()
    _record_candidate_revision(db, candidate, user, "human_create", None)
    await db.flush()
    await db.refresh(candidate)
    return _candidate_out(candidate)


@router.post("/sessions/{session_id}/candidates/bulk-accept-low-risk", response_model=BulkAcceptOut)
async def bulk_accept_low_risk(
    session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    _session, _owner, _task, version = await _context(session_id, user, db)
    job = await _latest_job(version.id, db)
    if job is None:
        raise HTTPException(status_code=409, detail="候选抽取任务不存在")
    _require_review_lock(job, user)
    now = utc_now_naive()
    accepted = 0
    skipped_ids: list[str] = []
    for candidate in job.candidates:
        if _is_low_risk(candidate):
            before = _candidate_snapshot(candidate)
            candidate.review_status = "accepted"
            candidate.reviewer_id = user.id
            candidate.review_note = "批量接受：通过结构低风险校验，仍需在正式编码阶段独立判断"
            candidate.reviewed_at = now
            _record_candidate_revision(db, candidate, user, "bulk_accept_low_risk", before)
            accepted += 1
        elif candidate.review_status == "pending":
            skipped_ids.append(candidate.id)
    await db.flush()
    return BulkAcceptOut(
        accepted=accepted, skipped=len(skipped_ids), skipped_candidate_ids=skipped_ids
    )


@router.get("/candidates/{candidate_id}/history", response_model=list[CandidateRevisionOut])
async def candidate_revision_history(
    candidate_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    candidate = await db.get(ExtractionCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="候选片段不存在")
    await _session_context(candidate.session_id, user, db)
    rows = (await db.execute(
        select(ExtractionCandidateRevision, User.name)
        .outerjoin(User, User.id == ExtractionCandidateRevision.actor_id)
        .where(ExtractionCandidateRevision.candidate_id == candidate_id)
        .order_by(ExtractionCandidateRevision.created_at.desc(), ExtractionCandidateRevision.id.desc())
    )).all()
    return [CandidateRevisionOut(
        id=revision.id, candidate_id=revision.candidate_id,
        extraction_job_id=revision.extraction_job_id, action=revision.action,
        actor_id=revision.actor_id, actor_name=actor_name,
        before_snapshot=revision.before_snapshot, after_snapshot=revision.after_snapshot,
        created_at=revision.created_at,
    ) for revision, actor_name in rows]


@router.post("/sessions/{session_id}/complete", response_model=ExtractionJobOut)
async def complete_candidate_review(
    session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    _session, _owner, _task, version = await _context(session_id, user, db)
    job = await _latest_job(version.id, db)
    if job is None:
        raise HTTPException(status_code=409, detail="该会话尚无候选抽取任务")
    _require_review_lock(job, user)
    pending = await db.scalar(select(func.count(ExtractionCandidate.id)).where(
        ExtractionCandidate.extraction_job_id == job.id,
        ExtractionCandidate.review_status == "pending",
    )) or 0
    if pending:
        raise HTTPException(status_code=409, detail=f"仍有 {pending} 条候选尚未复核")
    accepted = await db.scalar(select(func.count(ExtractionCandidate.id)).where(
        ExtractionCandidate.extraction_job_id == job.id,
        ExtractionCandidate.review_status == "accepted",
    )) or 0
    if accepted == 0:
        raise HTTPException(status_code=409, detail="至少需要确认一条候选，或人工补充遗漏")
    job.status = "reviewed"
    job.review_lock_user_id = None
    job.review_lock_acquired_at = None
    job.review_lock_expires_at = None
    await db.flush()
    return job


@router.post(
    "/sessions/{session_id}/audio-ticket",
    response_model=ReviewAudioTicketOut,
)
async def create_review_audio_ticket(
    session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    await _session_context(session_id, user, db)
    job = await _audio_job(session_id, db)
    if job is None or not job.canonical_audio_path:
        raise HTTPException(status_code=404, detail="该会话尚无可播放的完整录音")
    _review_audio_path(job)
    expires = int(time.time()) + REVIEW_AUDIO_TTL_SECONDS
    signature = sign_review_audio(session_id, job.id, expires, settings.SECRET_KEY)
    query = urlencode({"job_id": job.id, "expires": expires, "signature": signature})
    return ReviewAudioTicketOut(
        url=f"/api/research/extraction/sessions/{session_id}/audio-stream?{query}",
        expires=expires,
    )


@router.get(
    "/sessions/{session_id}/audio-waveform",
    response_model=ReviewAudioWaveformOut,
)
async def review_audio_waveform(
    session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _require_reviewer(user)
    await _session_context(session_id, user, db)
    job = await _audio_job(session_id, db)
    if job is None:
        raise HTTPException(status_code=404, detail="该会话尚无可播放的完整录音")
    try:
        duration, peaks = await asyncio.to_thread(wav_waveform, _review_audio_path(job))
    except (ValueError, wave.Error) as error:
        raise HTTPException(status_code=422, detail=f"录音波形生成失败：{error}") from error
    return ReviewAudioWaveformOut(duration_seconds=duration, peaks=peaks)


@router.get("/sessions/{session_id}/audio-stream")
async def stream_review_audio(
    session_id: str,
    job_id: str = Query(min_length=1, max_length=64),
    expires: int = Query(gt=0),
    signature: str = Query(min_length=64, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    if not verify_review_audio(
        session_id, job_id, expires, signature, settings.SECRET_KEY
    ):
        raise HTTPException(status_code=403, detail="录音播放地址无效或已过期")
    job = await db.get(AsrJob, job_id)
    if job is None or job.session_id != session_id:
        raise HTTPException(status_code=404, detail="录音不存在")
    audio_path = _review_audio_path(job)
    return FileResponse(
        path=audio_path,
        media_type="audio/wav",
        filename=f"{session_id}.wav",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "Accept-Ranges": "bytes"},
    )
