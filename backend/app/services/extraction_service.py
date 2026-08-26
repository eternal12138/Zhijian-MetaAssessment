"""Queue, execute, and recover auditable candidate extraction jobs."""
from __future__ import annotations

from datetime import timedelta
import logging

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.time import utc_now_naive
from app.database import AsyncSessionLocal
from app.models.asr import TranscriptVersion
from app.models.extraction import ExtractionCandidate, ExtractionJob
from app.models.session import AssessmentSession, TranscriptSegment
from app.services.metacognition_extractor import (
    ExtractionProviderError,
    MetacognitiveExtractor,
)
from app.services.metacognition_extractor.schemas import SourceSegment
from app.services.method_templates import get_template
from app.services.model_inference import classify_candidates
from app.services.notifications import create_notification
from app.services.runtime_model_config import load_runtime_model_settings


class ExtractionAlreadyRunningError(RuntimeError):
    pass


logger = logging.getLogger(__name__)


async def _notify_extraction_terminal(
    db: AsyncSession,
    job: ExtractionJob,
    *,
    succeeded: bool,
    candidate_count: int = 0,
) -> None:
    notify_user_id = job.requested_by
    if not notify_user_id:
        session = await db.get(AssessmentSession, job.session_id)
        if session:
            notify_user_id = session.user_id
    if not notify_user_id:
        return
    target_url = (
        f"/candidate-review?session_id={job.session_id}&job_id={job.id}"
    )
    try:
        nested = await db.begin_nested()
        try:
            if succeeded:
                await create_notification(
                    db, user_id=notify_user_id, type="review",
                    title=f"抽取版本 V{job.generation_no} 已生成",
                    content=f"AI 候选抽取已完成，共生成 {candidate_count} 条候选，等待人工复核。",
                    target_url=target_url, event_key=f"extraction:{job.id}:completed",
                    priority="important", metadata={
                        "job_id": job.id, "session_id": job.session_id,
                        "generation_no": job.generation_no,
                        "candidate_count": candidate_count, "status": "reviewing",
                    },
                )
            else:
                await create_notification(
                    db, user_id=notify_user_id, type="review",
                    title=f"抽取版本 V{job.generation_no} 生成失败",
                    content=job.error_message or "AI 候选抽取未能完成，请检查模型服务后重新运行。",
                    target_url=target_url, event_key=f"extraction:{job.id}:failed",
                    priority="important", metadata={
                        "job_id": job.id, "session_id": job.session_id,
                        "generation_no": job.generation_no,
                        "error_code": job.error_code, "status": "failed",
                    },
                )
            await nested.commit()
        except Exception:
            await nested.rollback()
            raise
    except Exception:
        logger.exception("Extraction job %s reached terminal state but notification failed", job.id)


async def enqueue_extraction(
    *,
    version: TranscriptVersion,
    db: AsyncSession,
    requested_by: str | None = None,
    force_new_generation: bool = False,
) -> ExtractionJob | None:
    # Serialize generation allocation per transcript. Without this lock two
    # browser requests can both calculate the same max(generation_no) + 1.
    locked_version = await db.scalar(
        select(TranscriptVersion)
        .where(TranscriptVersion.id == version.id)
        .with_for_update()
    )
    if locked_version is None:
        return None
    version = locked_version
    settings = await load_runtime_model_settings(db, get_settings())
    if not settings.METACOGNITIVE_EXTRACTION_ENABLED:
        return None
    prompt, prompt_version = await get_template(db, "metacognitive_extractor")
    existing = await db.scalar(
        select(ExtractionJob).where(
            ExtractionJob.transcript_version_id == version.id,
            ExtractionJob.extractor_version == settings.METACOGNITIVE_EXTRACTOR_VERSION,
            ExtractionJob.prompt_version == prompt_version,
        ).order_by(ExtractionJob.generation_no.desc(), ExtractionJob.created_at.desc()).limit(1)
    )
    if existing is not None and not force_new_generation:
        return existing
    previous = await db.scalar(
        select(ExtractionJob)
        .where(ExtractionJob.transcript_version_id == version.id)
        .order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc()).limit(1)
    )
    if force_new_generation and previous is not None and previous.status in {
        "queued", "running", "retry_wait"
    }:
        raise ExtractionAlreadyRunningError("当前抽取任务仍在处理中，不能重复提交")
    generation_no = int(await db.scalar(
        select(func.max(ExtractionJob.generation_no)).where(
            ExtractionJob.transcript_version_id == version.id,
        )
    ) or 0) + 1
    await db.execute(
        update(ExtractionJob)
        .where(
            ExtractionJob.session_id == version.session_id,
            ExtractionJob.status.in_(("queued", "running", "completed", "reviewing", "reviewed")),
        )
        .values(status="superseded")
    )
    job = ExtractionJob(
        session_id=version.session_id,
        transcript_version_id=version.id,
        requested_by=requested_by,
        status="queued",
        provider="openai_compatible",
        model=settings.LLM_MODEL,
        extractor_version=settings.METACOGNITIVE_EXTRACTOR_VERSION,
        prompt_version=prompt_version,
        generation_no=generation_no,
        supersedes_job_id=previous.id if previous else None,
        prompt_content=prompt,
        raw_asr_text=version.full_text,
        max_retries=settings.METACOGNITIVE_EXTRACTION_MAX_RETRIES,
    )
    db.add(job)
    await db.flush()
    # MySQL does not reliably return every server-default timestamp on INSERT.
    # Refresh before Pydantic serializes the ORM object, otherwise accessing a
    # still-expired created_at/updated_at can raise MissingGreenlet (HTTP 500).
    await db.refresh(job, attribute_names=["created_at"])
    return job


async def claim_next_extraction_job() -> str | None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            job = await db.scalar(
                select(ExtractionJob)
                .where(ExtractionJob.status.in_(("queued", "retry_wait")))
                .order_by(ExtractionJob.created_at.asc(), ExtractionJob.id.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            job.status = "running"
            job.started_at = utc_now_naive()
            job.error_code = None
            job.error_message = None
            await db.flush()
            return job.id


async def process_extraction_job(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.scalar(
            select(ExtractionJob)
            .where(ExtractionJob.id == job_id)
            .options(selectinload(ExtractionJob.candidates))
        )
        if job is None or job.status != "running":
            return
        version = await db.get(TranscriptVersion, job.transcript_version_id)
        session = await db.get(AssessmentSession, job.session_id)
        if version is None or session is None:
            job.status = "failed"
            job.error_code = "source_missing"
            job.error_message = "权威转录或测评会话不存在"
            job.completed_at = utc_now_naive()
            await _notify_extraction_terminal(db, job, succeeded=False)
            await db.commit()
            return
        rows = list((await db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_version_id == version.id)
            .order_by(TranscriptSegment.segment_no.asc(), TranscriptSegment.id.asc())
        )).all())
        # The exact prompt is snapshotted on the job; later template activation
        # or edits cannot change how this result is reproduced.
        prompt = job.prompt_content
        runtime = await load_runtime_model_settings(db, get_settings())
        source_segments = [SourceSegment(
            segment_id=item.id,
            text=item.text,
            started_at_ms=item.started_at_ms,
            ended_at_ms=item.ended_at_ms,
        ) for item in rows]
        try:
            # Keep every authoritative segment in scope without relying on one
            # model request having an unlimited context window.
            batches: list[list[SourceSegment]] = []
            current: list[SourceSegment] = []
            current_chars = 0
            for source_segment in source_segments:
                if current and (len(current) >= 40 or current_chars + len(source_segment.text) > 12000):
                    batches.append(current)
                    current = []
                    current_chars = 0
                current.append(source_segment)
                current_chars += len(source_segment.text)
            if current:
                batches.append(current)

            extractor = MetacognitiveExtractor(runtime)
            extracted_candidates = []
            raw_batches: list[dict] = []
            for batch_no, batch in enumerate(batches, start=1):
                batch_result = await extractor.extract(batch, prompt)
                extracted_candidates.extend(batch_result.candidates)
                raw_batches.append({
                    "batch_no": batch_no,
                    "segment_ids": [item.segment_id for item in batch],
                    "response": batch_result.raw_response,
                })
            by_id = {item.id: item for item in rows}
            for old in list(job.candidates):
                await db.delete(old)
            candidate_rows: list[ExtractionCandidate] = []
            for index, item in enumerate(extracted_candidates, start=1):
                source = by_id[item.segment_id]
                start = source.text.find(item.original_text)
                candidate = ExtractionCandidate(
                    extraction_job_id=job.id,
                    source_transcript_segment_id=source.id,
                    session_id=session.id,
                    run_id=session.run_id,
                    user_id=session.user_id,
                    task_id=session.task_id,
                    sequence_no=index,
                    source_type="llm",
                    review_status="pending",
                    raw_asr_text=source.text,
                    original_text=item.original_text,
                    clean_text=item.clean_text,
                    char_start=start if start >= 0 else None,
                    char_end=(start + len(item.original_text)) if start >= 0 else None,
                    started_at_ms=source.started_at_ms,
                    ended_at_ms=source.ended_at_ms,
                )
                db.add(candidate)
                candidate_rows.append(candidate)
            await db.flush()
            classifier_version = None
            classification_error = ""
            try:
                active_model = await classify_candidates(db, candidate_rows)
                classifier_version = active_model.version if active_model else None
            except Exception as error:
                # Candidate extraction remains available when the optional
                # production classifier is temporarily unavailable. The
                # failure stays visible on every candidate for human review.
                classification_error = str(error)[:1000]
                for candidate in candidate_rows:
                    candidate.classification_error = classification_error
                    candidate.classification_status = "pending_classification"
                    candidate.prediction_source = None
            job.status = "reviewing"
            job.raw_response = {
                "batches": raw_batches,
                "classification": {
                    "model_version": classifier_version,
                    "status": "completed" if classifier_version else "not_active" if not classification_error else "failed",
                    "error": classification_error,
                },
            }
            job.completed_at = utc_now_naive()
            job.error_code = None
            job.error_message = None
            await _notify_extraction_terminal(
                db, job, succeeded=True, candidate_count=len(extracted_candidates)
            )
            await db.commit()
        except ExtractionProviderError as error:
            job.retry_count += 1
            job.error_code = error.code
            job.error_message = str(error)
            job.status = (
                "retry_wait"
                if error.retryable and job.retry_count <= job.max_retries
                else "failed"
            )
            if job.status == "failed":
                job.completed_at = utc_now_naive()
                await _notify_extraction_terminal(db, job, succeeded=False)
            await db.commit()
        except Exception as error:
            job.retry_count += 1
            job.error_code = "extraction_worker_error"
            job.error_message = str(error)
            job.status = "retry_wait" if job.retry_count <= job.max_retries else "failed"
            if job.status == "failed":
                job.completed_at = utc_now_naive()
                await _notify_extraction_terminal(db, job, succeeded=False)
            await db.commit()


async def requeue_stale_extraction_jobs() -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(ExtractionJob)
            .where(
                ExtractionJob.status == "running",
                ExtractionJob.updated_at < utc_now_naive() - timedelta(minutes=10),
            )
            .values(
                status="queued",
                error_code="worker_restarted",
                error_message="候选抽取 Worker 重启，任务已重新排队",
            )
        )
        await db.commit()
        return int(result.rowcount or 0)
