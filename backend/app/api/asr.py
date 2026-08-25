"""Authoritative ASR status, retry and transcript version APIs."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, delete, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.core.security import can_access_user, get_current_user
from app.core.time import utc_now_naive
from app.database import get_db
from app.models.asr import AsrJob, TranscriptVersion
from app.models.research import AuditLog
from app.models.session import AssessmentSession, AudioChunk
from app.models.user import User
from app.schemas.asr import (
    AsrBatchRetryIn,
    AsrBatchRetryOut,
    AsrReviewQueueItemOut,
    AsrSessionStatusOut,
    TranscriptCorrectionIn,
    TranscriptVersionOut,
)
from app.services.asr_service import (
    create_corrected_version,
    ensure_asr_job,
)
from app.services.audio_manifest import AudioManifestError
from app.services.extraction_service import enqueue_extraction
from app.config import get_settings

router = APIRouter(prefix="/sessions", tags=["服务端 ASR"])
settings = get_settings()


async def _accessible_session(
    session_id: str,
    user: User,
    db: AsyncSession,
) -> AssessmentSession:
    session = await db.get(AssessmentSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="测评会话不存在")
    owner = await db.get(User, session.user_id)
    if owner is None or not can_access_user(user, owner):
        raise HTTPException(status_code=403, detail="无权访问该测评会话")
    return session


async def _latest_job(session_id: str, db: AsyncSession) -> AsrJob | None:
    result = await db.execute(
        select(AsrJob)
        .where(AsrJob.session_id == session_id)
        .order_by(AsrJob.created_at.desc(), AsrJob.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _authoritative_version(
    session_id: str, db: AsyncSession
) -> TranscriptVersion | None:
    result = await db.execute(
        select(TranscriptVersion)
        .where(
            TranscriptVersion.session_id == session_id,
            TranscriptVersion.is_authoritative.is_(True),
        )
        .options(selectinload(TranscriptVersion.segments))
        .order_by(TranscriptVersion.version_no.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/asr/review-queue", response_model=list[AsrReviewQueueItemOut])
async def list_asr_review_queue(
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    search: str = Query(default="", max_length=100),
    status_filter: str = Query(default=""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_reviewer(user)
    managed_classes = [
        value.strip() for value in (user.managed_classes or "").split(",") if value.strip()
    ]
    access_scope = literal(True) if user.role == "admin" else or_(
        User.id == user.id,
        and_(User.role == "student", User.class_group.in_(managed_classes)),
    )
    latest_job_id = (
        select(AsrJob.id)
        .where(AsrJob.session_id == AssessmentSession.id)
        .order_by(AsrJob.created_at.desc(), AsrJob.id.desc())
        .limit(1).correlate(AssessmentSession).scalar_subquery()
    )
    authoritative_version_id = (
        select(TranscriptVersion.id)
        .where(
            TranscriptVersion.session_id == AssessmentSession.id,
            TranscriptVersion.is_authoritative.is_(True),
        )
        .order_by(TranscriptVersion.version_no.desc(), TranscriptVersion.id.desc())
        .limit(1).correlate(AssessmentSession).scalar_subquery()
    )
    filters = [AsrJob.id == latest_job_id, access_scope]
    keyword = search.strip()
    if keyword:
        filters.append(or_(
            User.name.ilike(f"%{keyword}%"),
            User.username.ilike(f"%{keyword}%"),
            User.class_group.ilike(f"%{keyword}%"),
        ))
    if status_filter == "attention":
        filters.append(AsrJob.status.in_(("failed", "retry_wait", "waiting_configuration")))
    elif status_filter == "completed":
        filters.append(AsrJob.status.in_(("completed", "manually_transcribed")))
    elif status_filter:
        filters.append(AsrJob.status == status_filter)
    base = (
        select(AsrJob, AssessmentSession, User, TranscriptVersion)
        .join(AssessmentSession, AssessmentSession.id == AsrJob.session_id)
        .join(User, User.id == AssessmentSession.user_id)
        .outerjoin(TranscriptVersion, TranscriptVersion.id == authoritative_version_id)
        .where(*filters)
    )
    total = int(await db.scalar(
        select(func.count()).select_from(
            select(AssessmentSession.id)
            .join(AsrJob, AsrJob.session_id == AssessmentSession.id)
            .join(User, User.id == AssessmentSession.user_id)
            .where(*filters)
            .subquery()
        )
    ) or 0)
    result = await db.execute(
        base
        .options(
            defer(AsrJob.input_manifest),
            defer(TranscriptVersion.full_text),
            defer(TranscriptVersion.raw_response),
        )
        .order_by(AssessmentSession.start_time.desc(), AssessmentSession.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    items: list[AsrReviewQueueItemOut] = []
    for job, session, owner, version in result.all():
        items.append(AsrReviewQueueItemOut(
            session_id=session.id,
            run_id=session.run_id,
            task_id=session.task_id,
            sequence_no=session.sequence_no,
            user_id=owner.id,
            user_name=owner.name,
            class_group=owner.class_group,
            job=job,
            authoritative_version_no=version.version_no if version else None,
            authoritative_source=version.source if version else None,
        ))
    return items


@router.get("/{session_id}/asr", response_model=AsrSessionStatusOut)
async def get_asr_status(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _accessible_session(session_id, user, db)
    return AsrSessionStatusOut(
        job=await _latest_job(session_id, db),
        authoritative_version=await _authoritative_version(session_id, db),
    )


@router.post("/{session_id}/asr/retry", response_model=AsrSessionStatusOut)
async def retry_asr(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _retry_asr_session(session_id, user, db)


async def _retry_asr_session(
    session_id: str,
    user: User,
    db: AsyncSession,
) -> AsrSessionStatusOut:
    session = await _accessible_session(session_id, user, db)
    if session.status != "completed":
        raise HTTPException(status_code=409, detail="会话尚未完成，不能重试识别")
    chunks_result = await db.execute(
        select(AudioChunk)
        .where(AudioChunk.session_id == session_id)
        .order_by(AudioChunk.chunk_index.asc())
    )
    try:
        job = await ensure_asr_job(
            session, list(chunks_result.scalars().all()), db
        )
    except AudioManifestError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "message": str(error)},
        ) from error
    if job.status == "completed":
        return AsrSessionStatusOut(
            job=job,
            authoritative_version=await _authoritative_version(session_id, db),
        )
    if job.status in {"preparing_audio", "transcribing"}:
        raise HTTPException(status_code=409, detail="ASR 任务已在排队或处理中")
    if not settings.asr_provider_ready:
        raise HTTPException(
            status_code=409,
            detail="服务端 ASR 尚未配置，请先设置 ASR_PROVIDER 与 ASR_BASE_URL",
        )
    if job.status in {"queued", "retry_wait"}:
        return AsrSessionStatusOut(
            job=job,
            authoritative_version=await _authoritative_version(session_id, db),
        )
    job.status = "queued"
    job.retry_count = 0
    job.error_code = None
    job.error_message = None
    job.started_at = None
    job.finished_at = None
    await db.flush()
    # updated_at is maintained by the database and becomes expired after the
    # UPDATE. Refresh it explicitly while async I/O is still allowed so that
    # Pydantic serialization cannot trigger a MissingGreenlet lazy load.
    await db.refresh(job)
    return AsrSessionStatusOut(
        job=job,
        authoritative_version=await _authoritative_version(session_id, db),
    )


@router.post("/asr/batch-retry", response_model=AsrBatchRetryOut)
async def batch_retry_asr(
    data: AsrBatchRetryIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_reviewer(user)
    processed = 0
    errors: list[str] = []
    for session_id in dict.fromkeys(data.session_ids):
        try:
            await _retry_asr_session(session_id, user, db)
            processed += 1
        except HTTPException as error:
            detail = error.detail
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("code") or str(detail)
            errors.append(f"{session_id}：{detail}")
    return AsrBatchRetryOut(
        processed=processed,
        skipped=len(errors),
        errors=errors,
    )


@router.get(
    "/{session_id}/transcript-versions",
    response_model=list[TranscriptVersionOut],
)
async def list_transcript_versions(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _accessible_session(session_id, user, db)
    result = await db.execute(
        select(TranscriptVersion)
        .where(TranscriptVersion.session_id == session_id)
        .options(selectinload(TranscriptVersion.segments))
        .order_by(TranscriptVersion.version_no.desc())
    )
    return list(result.scalars().all())


def _require_reviewer(user: User) -> None:
    if user.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="仅教师或管理员可确认权威转录")


@router.post(
    "/{session_id}/transcript-versions/{version_id}/approve",
    response_model=TranscriptVersionOut,
)
async def approve_transcript_version(
    session_id: str,
    version_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_reviewer(user)
    await _accessible_session(session_id, user, db)
    result = await db.execute(
        select(TranscriptVersion)
        .where(
            TranscriptVersion.id == version_id,
            TranscriptVersion.session_id == session_id,
        )
        .options(selectinload(TranscriptVersion.segments))
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="转录版本不存在")
    await db.execute(
        update(TranscriptVersion)
        .where(
            TranscriptVersion.session_id == session_id,
            TranscriptVersion.id != version_id,
            TranscriptVersion.is_authoritative.is_(True),
        )
        .values(is_authoritative=False, status="superseded")
    )
    version.is_authoritative = True
    version.status = "approved"
    version.approved_by = user.id
    version.approved_at = utc_now_naive()
    await enqueue_extraction(version=version, db=db, requested_by=user.id)
    await db.flush()
    return version


@router.post(
    "/{session_id}/transcript-versions/corrections",
    response_model=TranscriptVersionOut,
    status_code=201,
)
async def correct_transcript(
    session_id: str,
    data: TranscriptCorrectionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_reviewer(user)
    await _accessible_session(session_id, user, db)
    version = await create_corrected_version(
        session_id=session_id,
        segments=data.segments,
        user_id=user.id,
        db=db,
    )
    result = await db.execute(
        select(TranscriptVersion)
        .where(TranscriptVersion.id == version.id)
        .options(selectinload(TranscriptVersion.segments))
    )
    return result.scalar_one()


@router.post(
    "/{session_id}/transcript-versions/manual",
    response_model=TranscriptVersionOut,
    status_code=201,
)
async def create_manual_transcript(
    session_id: str,
    data: TranscriptCorrectionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an authoritative human transcript only after ASR has failed."""
    _require_reviewer(user)
    await _accessible_session(session_id, user, db)
    job = await _latest_job(session_id, db)
    if job is None or job.status != "failed":
        raise HTTPException(status_code=409, detail="仅识别失败的语音可以改为人工转录")
    existing_version_count = int(await db.scalar(
        select(func.count(TranscriptVersion.id)).where(
            TranscriptVersion.session_id == session_id
        )
    ) or 0)
    if existing_version_count:
        raise HTTPException(status_code=409, detail="该会话已经存在转录版本，请使用人工校订")

    version = await create_corrected_version(
        session_id=session_id,
        segments=data.segments,
        user_id=user.id,
        db=db,
        source="human_transcribed",
    )
    job.status = "manually_transcribed"
    job.finished_at = utc_now_naive()
    db.add(AuditLog(
        actor_id=user.id,
        action="asr.manual_transcript.create",
        target_type="assessment_session",
        target_id=session_id,
        detail={
            "asr_job_id": job.id,
            "transcript_version_id": version.id,
            "segment_count": len(data.segments),
            "source": "human_transcribed",
            "original_error_code": job.error_code,
        },
    ))
    result = await db.execute(
        select(TranscriptVersion)
        .where(TranscriptVersion.id == version.id)
        .options(selectinload(TranscriptVersion.segments))
    )
    return result.scalar_one()


def _safe_audio_file(storage_path: str | None) -> Path | None:
    if not storage_path:
        return None
    root = settings.audio_upload_path.resolve()
    candidate = (root / storage_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


@router.delete("/{session_id}/asr/failed-audio")
async def delete_failed_asr_audio(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently remove audio only when the latest ASR job failed and no transcript exists."""
    _require_reviewer(user)
    await _accessible_session(session_id, user, db)
    latest_job = await _latest_job(session_id, db)
    if latest_job is None or latest_job.status != "failed":
        raise HTTPException(status_code=409, detail="仅能删除识别失败的语音")
    version_count = int(await db.scalar(
        select(func.count(TranscriptVersion.id)).where(
            TranscriptVersion.session_id == session_id
        )
    ) or 0)
    if version_count:
        raise HTTPException(
            status_code=409,
            detail="该会话已经存在转录版本，不能在此直接删除；请前往数据管理处理",
        )

    jobs = list((await db.scalars(
        select(AsrJob).where(AsrJob.session_id == session_id)
    )).all())
    chunks = list((await db.scalars(
        select(AudioChunk).where(AudioChunk.session_id == session_id)
    )).all())
    storage_paths = {
        path
        for job in jobs
        for path in (job.source_audio_path, job.canonical_audio_path)
        if path
    }
    storage_paths.update(chunk.storage_path for chunk in chunks if chunk.storage_path)

    await db.execute(delete(AudioChunk).where(AudioChunk.session_id == session_id))
    await db.execute(delete(AsrJob).where(AsrJob.session_id == session_id))
    db.add(AuditLog(
        actor_id=user.id,
        action="asr.failed_audio.delete",
        target_type="assessment_session",
        target_id=session_id,
        detail={
            "asr_job_count": len(jobs),
            "audio_chunk_count": len(chunks),
            "storage_file_count": len(storage_paths),
            "latest_error_code": latest_job.error_code,
        },
    ))
    await db.flush()

    deleted_files = 0
    failed_files = 0
    for storage_path in storage_paths:
        target = _safe_audio_file(storage_path)
        if target is None:
            failed_files += 1
            continue
        try:
            if target.exists() and target.is_file():
                target.unlink()
                deleted_files += 1
        except OSError:
            failed_files += 1
    return {
        "status": "success",
        "message": "识别失败的语音及相关任务记录已删除",
        "deleted_files": deleted_files,
        "failed_files": failed_files,
    }
