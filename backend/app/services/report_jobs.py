"""Durable report queue. One global database slot; no transaction spans AI I/O."""
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.core.time import utc_now_naive
from app.database import AsyncSessionLocal
from app.models.protocol import AssessmentRun
from app.models.report import MetacognitiveProfile
from app.models.research import AnalysisJob, AuditLog
from app.services.report_analyzer import prepare_report, call_report_ai, save_report, ReportReadOnlyError


async def enqueue_report(run_id, requested_by, db, *, report_only=False, expected_generated_at=None):
    await db.scalar(select(AssessmentRun.id).where(AssessmentRun.id == run_id).with_for_update())
    existing = await db.scalar(select(AnalysisJob).where(AnalysisJob.active_run_id == run_id))
    if existing:
        return existing
    profile = await db.scalar(select(MetacognitiveProfile).where(MetacognitiveProfile.run_id == run_id))
    if profile and (profile.workflow_status not in {"draft", "review_pending", "reviewed"} or profile.published_at):
        raise ReportReadOnlyError("已发布或已归档报告不能重新分析")
    from app.core.time import as_utc, utc_isoformat
    if report_only and (not profile or not expected_generated_at or as_utc(expected_generated_at) != as_utc(profile.generated_at)):
        raise ValueError("报告已更新，请刷新并选择最新草稿后重试")
    job = AnalysisJob(run_id=run_id, requested_by=requested_by, status="queued", progress=0,
        active_run_id=run_id, created_at=utc_now_naive(), error_message="",
        payload={"report_only": report_only, "expected_generated_at": utc_isoformat(expected_generated_at) if expected_generated_at else None,
                 "submitted_version": profile.version_no if profile else None})
    db.add(job)
    await db.flush()
    return job


async def claim_report_job():
    async with AsyncSessionLocal() as db:
        now = utc_now_naive()
        # No automatic paid retry after a crash: release safely and let the user retry.
        await db.execute(update(AnalysisJob).where(AnalysisJob.status == "running",
            AnalysisJob.heartbeat_at < now - timedelta(minutes=3)).values(status="failed", active_run_id=None,
            running_slot=None, completed_at=now, error_message="报告工作进程中断或心跳超时；原草稿已保留，可重新提交"))
        await db.execute(update(AnalysisJob).where(AnalysisJob.status == "queued",
            AnalysisJob.created_at < now - timedelta(hours=1)).values(status="failed", active_run_id=None,
            running_slot=None, completed_at=now, error_message="报告排队超过一小时，请检查 report-worker 后重新提交"))
        await db.commit()
        if await db.scalar(select(AnalysisJob.id).where(AnalysisJob.running_slot == 1)):
            return None
        job = await db.scalar(select(AnalysisJob).where(AnalysisJob.status == "queued",
            AnalysisJob.active_run_id.is_not(None)).order_by(AnalysisJob.created_at, AnalysisJob.id)
            .with_for_update(skip_locked=True).limit(1))
        if not job:
            return None
        job.status, job.progress, job.running_slot = "running", 10, 1
        job.started_at = job.heartbeat_at = now
        job_id = job.id
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return None
        return job_id


async def heartbeat(job_id):
    while True:
        await asyncio.sleep(10)
        async with AsyncSessionLocal() as db:
            await db.execute(update(AnalysisJob).where(AnalysisJob.id == job_id, AnalysisJob.status == "running")
                             .values(heartbeat_at=utc_now_naive()))
            await db.commit()


async def process_report_job(job_id):
    pulse = asyncio.create_task(heartbeat(job_id))
    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(AnalysisJob, job_id)
            if not job or job.status != "running":
                return
            payload = dict(job.payload or {})
            from app.models.user import User
            from app.core.security import can_access_user
            actor = await db.get(User, job.requested_by)
            run = await db.get(AssessmentRun, job.run_id)
            owner = await db.get(User, run.user_id) if run else None
            if not actor or not actor.is_active or actor.role not in {"admin", "teacher"} or not owner or not can_access_user(actor, owner):
                raise ValueError("申请人的权限或测评归属已变化，任务未执行")
            expected = payload.get("expected_generated_at")
            prepared = await prepare_report(job.run_id, db, report_only=payload.get("report_only", False),
                expected_generated_at=datetime.fromisoformat(expected.replace("Z", "+00:00")) if expected else None)
            if prepared["expected_version"] != payload.get("submitted_version"):
                raise ValueError("排队期间草稿版本已变化，请重新提交")
            job.payload = {**payload, "prepared": prepared}
            job.progress = 35
            await db.commit()
        # The session is CLOSED before sending a network request. Timeout bounds
        # the whole request, even when a provider streams bytes indefinitely.
        value, metadata = await asyncio.wait_for(call_report_ai(prepared), timeout=180)
        async with AsyncSessionLocal() as db:
            job = await db.scalar(select(AnalysisJob).where(AnalysisJob.id == job_id)
                                  .with_for_update().execution_options(populate_existing=True))
            if not job or job.status != "running" or job.running_slot != 1:
                return  # A canceled/stale worker has lost its right to write.
            profile = await save_report(prepared, value, {**metadata, "job_id": job.id,
                "started_at": job.started_at.isoformat(), "completed_at": utc_now_naive().isoformat(),
                "duration_seconds": (utc_now_naive() - job.started_at).total_seconds()}, db)
            job.status, job.progress, job.result_profile_id = "completed", 100, profile.id
            job.active_run_id = job.running_slot = None
            job.completed_at = utc_now_naive()
            # Only the successful report retains its immutable full input snapshot.
            job.payload = {k: v for k, v in (job.payload or {}).items() if k != "prepared"}
            db.add(AuditLog(actor_id=job.requested_by, action="analysis.complete", target_type="metacognitive_profile",
                target_id=profile.id, detail={"job_id": job.id, "version_no": profile.version_no,
                                            "data_version": prepared["snapshot"]["data_version"]}))
            await db.commit()
    except (Exception, asyncio.CancelledError) as error:
        async with AsyncSessionLocal() as db:
            job = await db.get(AnalysisJob, job_id)
            if job and job.status == "running":
                message = str(error) if isinstance(error, ValueError) else "报告处理异常或超时；原草稿已保留，请查看后端日志并重试"
                job.status, job.error_message = "failed", message[:2000]
                job.active_run_id = job.running_slot = None
                job.completed_at = utc_now_naive()
                db.add(AuditLog(actor_id=job.requested_by, action="analysis.failed", target_type="analysis_job",
                    target_id=job.id, detail={"reason": job.error_message}))
                await db.commit()
        if isinstance(error, asyncio.CancelledError):
            raise
        import logging
        logging.getLogger(__name__).exception("Report job %s failed", job_id)
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
