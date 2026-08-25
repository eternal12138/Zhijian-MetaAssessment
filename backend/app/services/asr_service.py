"""Authoritative ASR job creation and processing."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.time import utc_now_naive
from app.database import AsyncSessionLocal
from app.models.asr import AsrJob, TranscriptVersion
from app.models.session import AssessmentSession, AudioChunk, TranscriptSegment
from app.services.asr_provider import AsrProviderError, get_asr_provider
from app.services.audio_manifest import (
    AudioManifest,
    AudioManifestError,
    ManifestChunk,
    build_audio_manifest,
)
from app.services.audio_processor import AudioProcessingError, merge_and_transcode
from app.services.runtime_model_config import load_runtime_model_settings

settings = get_settings()


def _now() -> datetime:
    return utc_now_naive()


async def ensure_asr_job(
    session: AssessmentSession,
    chunks: list[AudioChunk],
    db: AsyncSession,
) -> AsrJob:
    await load_runtime_model_settings(db, settings)
    manifest = await asyncio.to_thread(
        build_audio_manifest, session.id, chunks, settings.audio_upload_path
    )
    provider = settings.ASR_PROVIDER.strip().lower()
    result = await db.execute(
        select(AsrJob).where(
            AsrJob.session_id == session.id,
            AsrJob.manifest_hash == manifest.manifest_hash,
            AsrJob.provider == provider,
            AsrJob.model == settings.ASR_MODEL,
            AsrJob.config_version == settings.ASR_CONFIG_VERSION,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    provider_ready = settings.asr_provider_ready
    job = AsrJob(
        session_id=session.id,
        provider=provider,
        model=settings.ASR_MODEL,
        config_version=settings.ASR_CONFIG_VERSION,
        status="queued" if provider_ready else "waiting_configuration",
        manifest_hash=manifest.manifest_hash,
        input_manifest=manifest.to_dict(),
        expected_chunk_count=manifest.chunk_count,
        language=settings.ASR_LANGUAGE,
        max_retries=settings.ASR_MAX_RETRIES,
        error_code=None if provider_ready else "provider_not_configured",
        error_message=None if provider_ready else "服务端 ASR 尚未完成配置",
    )
    db.add(job)
    await db.flush()
    return job


def _manifest_from_dict(data: dict, expected_hash: str) -> AudioManifest:
    chunks = tuple(ManifestChunk(**item) for item in data.get("chunks", []))
    return AudioManifest(
        schema_version=str(data.get("schema_version", "1.0")),
        session_id=str(data["session_id"]),
        chunk_count=int(data["chunk_count"]),
        mime_type=str(data["mime_type"]),
        chunks=chunks,
        manifest_hash=expected_hash,
    )


async def claim_next_asr_job() -> str | None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await db.execute(
                select(AsrJob)
                .where(AsrJob.status.in_(("queued", "retry_wait")))
                .order_by(AsrJob.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            job = result.scalar_one_or_none()
            if job is None:
                return None
            job.status = "preparing_audio"
            job.started_at = job.started_at or _now()
            job.error_code = None
            job.error_message = None
            await db.flush()
            return job.id


async def _mark_failure(
    job_id: str,
    code: str,
    message: str,
    *,
    retryable: bool,
) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(AsrJob, job_id)
        if job is None:
            return
        if code in {"provider_disabled", "provider_not_configured"}:
            job.status = "waiting_configuration"
        elif retryable and job.retry_count < job.max_retries:
            job.retry_count += 1
            job.status = "retry_wait"
        else:
            job.status = "failed"
            job.finished_at = _now()
        job.error_code = code
        job.error_message = message[:4000]
        await db.commit()


async def process_asr_job(job_id: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await load_runtime_model_settings(db, settings)
            result = await db.execute(
                select(AsrJob)
                .where(AsrJob.id == job_id)
                .options(selectinload(AsrJob.session))
            )
            job = result.scalar_one_or_none()
            if job is None:
                return
            chunk_result = await db.execute(
                select(AudioChunk)
                .where(AudioChunk.session_id == job.session_id)
                .order_by(AudioChunk.chunk_index.asc())
            )
            chunks = list(chunk_result.scalars().all())
            rebuilt = await asyncio.to_thread(
                build_audio_manifest,
                job.session_id,
                chunks,
                settings.audio_upload_path,
            )
            if rebuilt.manifest_hash != job.manifest_hash:
                raise AudioManifestError(
                    "manifest_changed",
                    "音频分片在任务入队后发生变化，已拒绝识别",
                )
            processed = await asyncio.to_thread(
                merge_and_transcode,
                _manifest_from_dict(job.input_manifest, job.manifest_hash),
                settings.audio_upload_path,
                settings.FFMPEG_PATH,
            )
            job.source_audio_path = processed.source_path
            job.canonical_audio_path = processed.canonical_path
            job.audio_duration_ms = processed.duration_ms
            job.audio_size_bytes = processed.size_bytes
            job.audio_sha256 = processed.sha256
            job.audio_contains_signal = processed.contains_signal
            job.audio_rms_dbfs = processed.rms_dbfs
            job.audio_peak_dbfs = processed.peak_dbfs
            if not processed.contains_signal:
                rms = (
                    f"{processed.rms_dbfs} dBFS"
                    if processed.rms_dbfs is not None
                    else "无可测信号"
                )
                peak = (
                    f"{processed.peak_dbfs} dBFS"
                    if processed.peak_dbfs is not None
                    else "无可测信号"
                )
                job.status = "failed"
                job.error_code = "silent_audio"
                job.error_message = (
                    "录音文件存在且可解码，但声音电平过低，无法进行可靠识别。"
                    f"检测值：RMS {rms}，峰值 {peak}。"
                    "请试听原始录音并将该条数据标记为无声录音；重复识别不会恢复声音。"
                )
                job.finished_at = _now()
                await db.commit()
                return
            job.status = "transcribing"
            await db.commit()

        provider = get_asr_provider(settings)
        canonical_path = (
            settings.audio_upload_path / processed.canonical_path
        ).resolve()
        result = await provider.transcribe(canonical_path, job_id=job_id)

        async with AsyncSessionLocal() as db:
            job = await db.get(AsrJob, job_id)
            if job is None:
                return
            existing = await db.execute(
                select(TranscriptVersion).where(
                    TranscriptVersion.session_id == job.session_id,
                    TranscriptVersion.asr_job_id == job.id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                job.status = "completed"
                job.finished_at = _now()
                await db.commit()
                return
            await db.execute(
                update(TranscriptVersion)
                .where(
                    TranscriptVersion.session_id == job.session_id,
                    TranscriptVersion.is_authoritative.is_(True),
                )
                .values(is_authoritative=False, status="superseded")
            )
            max_version = await db.scalar(
                select(func.max(TranscriptVersion.version_no)).where(
                    TranscriptVersion.session_id == job.session_id
                )
            ) or 0
            version = TranscriptVersion(
                session_id=job.session_id,
                asr_job_id=job.id,
                version_no=max_version + 1,
                source="server_asr",
                status="ready",
                is_authoritative=True,
                language=result.language,
                provider=job.provider,
                model=job.model,
                full_text=result.text,
                raw_response=result.raw_response,
                created_by="system",
            )
            db.add(version)
            await db.flush()
            for index, segment in enumerate(result.segments):
                db.add(TranscriptSegment(
                    session_id=job.session_id,
                    client_segment_id=f"asr-{job.id}-{index}",
                    transcript_version_id=version.id,
                    segment_no=index,
                    text=segment.text,
                    started_at_ms=segment.started_at_ms,
                    ended_at_ms=segment.ended_at_ms,
                    is_final=True,
                    source="server_asr",
                    confidence=segment.confidence,
                    raw_data=segment.raw_data,
                ))
            from app.services.extraction_service import enqueue_extraction
            await enqueue_extraction(version=version, db=db)
            job.provider_request_id = result.request_id
            job.status = "completed"
            job.finished_at = _now()
            job.error_code = None
            job.error_message = None
            await db.commit()
    except AudioManifestError as error:
        await _mark_failure(job_id, error.code, str(error), retryable=False)
    except AudioProcessingError as error:
        await _mark_failure(job_id, error.code, str(error), retryable=False)
    except AsrProviderError as error:
        await _mark_failure(
            job_id, error.code, str(error), retryable=error.retryable
        )
    except Exception as error:
        await _mark_failure(
            job_id, "asr_worker_error", str(error), retryable=True
        )


async def requeue_stale_jobs() -> int:
    """Recover jobs interrupted by a worker/process restart."""
    async with AsyncSessionLocal() as db:
        stale_before = _now() - timedelta(minutes=10)
        result = await db.execute(
            update(AsrJob)
            .where(
                AsrJob.status.in_(("preparing_audio", "transcribing")),
                AsrJob.updated_at < stale_before,
            )
            .values(
                status="queued",
                error_code="worker_restarted",
                error_message="ASR Worker 重启，任务已重新排队",
            )
        )
        await db.commit()
        return int(result.rowcount or 0)


async def recover_missing_asr_jobs(
    *,
    older_than_minutes: int = 10,
    limit: int = 50,
) -> int:
    """Recreate jobs missed after a completed session was committed.

    This is intentionally conservative: only completed sessions with stored
    audio chunks and no ASR job at all are considered. ``ensure_asr_job`` keeps
    the operation idempotent if an API retry races with this recovery scan.
    """
    async with AsyncSessionLocal() as db:
        completed_before = _now() - timedelta(minutes=max(1, older_than_minutes))
        result = await db.execute(
            select(AssessmentSession)
            .where(
                AssessmentSession.status == "completed",
                AssessmentSession.end_time.is_not(None),
                AssessmentSession.end_time <= completed_before,
                ~AssessmentSession.asr_jobs.any(),
                AssessmentSession.audio_chunks.any(),
            )
            .order_by(AssessmentSession.end_time.asc())
            .limit(max(1, limit))
        )
        sessions = list(result.scalars().all())
        created = 0
        for session in sessions:
            chunk_result = await db.execute(
                select(AudioChunk)
                .where(AudioChunk.session_id == session.id)
                .order_by(AudioChunk.chunk_index.asc())
            )
            chunks = list(chunk_result.scalars().all())
            if not chunks:
                continue
            try:
                await ensure_asr_job(session, chunks, db)
                created += 1
            except AudioManifestError:
                # Invalid/incomplete audio remains available for manual review.
                continue
        await db.commit()
        return created


async def create_corrected_version(
    *,
    session_id: str,
    segments: list,
    user_id: str,
    db: AsyncSession,
    source: str = "human_corrected",
) -> TranscriptVersion:
    if source not in {"human_corrected", "human_transcribed"}:
        raise ValueError("不支持的人工转录来源")
    await db.execute(
        update(TranscriptVersion)
        .where(
            TranscriptVersion.session_id == session_id,
            TranscriptVersion.is_authoritative.is_(True),
        )
        .values(is_authoritative=False, status="superseded")
    )
    max_version = await db.scalar(
        select(func.max(TranscriptVersion.version_no)).where(
            TranscriptVersion.session_id == session_id
        )
    ) or 0
    ordered = sorted(segments, key=lambda item: item.segment_no)
    version = TranscriptVersion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        version_no=max_version + 1,
        source=source,
        status="approved",
        is_authoritative=True,
        language=settings.ASR_LANGUAGE,
        full_text="".join(item.text.strip() for item in ordered),
        provider="human" if source == "human_transcribed" else None,
        created_by=user_id,
        approved_by=user_id,
        approved_at=_now(),
    )
    db.add(version)
    await db.flush()
    for item in ordered:
        db.add(TranscriptSegment(
            session_id=session_id,
            client_segment_id=f"{source}-{version.id}-{item.segment_no}",
            transcript_version_id=version.id,
            segment_no=item.segment_no,
            text=item.text.strip(),
            started_at_ms=item.started_at_ms,
            ended_at_ms=item.ended_at_ms,
            is_final=True,
            source=source,
            confidence=item.confidence,
        ))
    await db.flush()
    from app.services.extraction_service import enqueue_extraction
    await enqueue_extraction(version=version, db=db, requested_by=user_id)
    return version
