"""Complete assessment reports, evidence coding, and human review."""
import json
import hashlib
import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import can_access_user, get_current_user, require_role
from app.database import get_db
from app.models.protocol import AssessmentRun
from app.models.report import MetacognitiveProfile, MetacognitionMeasurement, MeasurementCorrection
from app.models.session import AssessmentSession
from app.models.research import AuditLog
from app.core.time import utc_now_naive
from app.services.measurement_corrections import MAX_UPLOAD_BYTES, parse_correction_csv, correction_counts
from app.models.task import AssessmentTask
from app.models.user import User
from app.schemas.report import (
    ReportBriefOut,
    ReportGenerateIn,
    ReportOut,
    MetacognitionMeasurementOut,
    MetacognitionMeasurementPageOut,
)
from app.services.metacognition_measurement import calculate_and_persist_measurement
from app.services.metacognition_evidence import load_session_evidence
from app.services.report_analyzer import generate_run_report
from app.services.notifications import notify_reviewers

router = APIRouter(prefix="/reports", tags=["报告"])

LEGACY_REVIEW_DETAIL = {
    "code": "LEGACY_REVIEW_WORKFLOW_RETIRED",
    "message": "旧版单人编码复核流程已停用，请使用双人盲编与仲裁工作流",
}


async def _ensure_run_access(
    run_id: str,
    current_user: User,
    db: AsyncSession,
) -> AssessmentRun:
    run = await db.get(AssessmentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="完整测评不存在")
    owner = await db.get(User, run.user_id)
    if owner is None or not can_access_user(current_user, owner):
        raise HTTPException(status_code=403, detail="无权访问该测评报告")
    return run


async def _load_profile(
    *,
    profile_id: str | None = None,
    run_id: str | None = None,
    db: AsyncSession,
) -> MetacognitiveProfile | None:
    statement = select(MetacognitiveProfile).options(
        selectinload(MetacognitiveProfile.suggestions)
    )
    if profile_id:
        statement = statement.where(MetacognitiveProfile.id == profile_id)
    else:
        statement = statement.where(MetacognitiveProfile.run_id == run_id)
    result = await db.execute(statement)
    return result.scalar_one_or_none()


def _report_out(report: MetacognitiveProfile) -> ReportOut:
    return ReportOut(
        id=report.id,
        user_id=report.user_id,
        run_id=report.run_id,
        session_id=report.session_id,
        overall_score=report.overall_score,
        level=report.level,
        summary=report.summary,
        dimension_details=report.dimension_details or [],
        strengths=json.loads(report.strengths) if report.strengths else [],
        weaknesses=json.loads(report.weaknesses) if report.weaknesses else [],
        recommendations=[
            {
                "id": suggestion.id,
                "dimension": suggestion.dimension,
                "title": suggestion.title,
                "description": suggestion.description,
                "practices": json.loads(suggestion.practices) if suggestion.practices else [],
                "difficulty": suggestion.difficulty,
            }
            for suggestion in (report.suggestions or [])
        ],
        analysis_method=report.analysis_method,
        rubric_version=report.rubric_version,
        requires_review_count=report.requires_review_count,
        is_provisional=report.is_provisional,
        workflow_status=report.workflow_status,
        version_no=report.version_no,
        template_version=report.template_version,
        published_at=report.published_at,
        generated_at=report.generated_at,
    )


def _ensure_report_visible_to_user(
    report: MetacognitiveProfile,
    user: User,
) -> None:
    """Students only receive reports after the controlled publish step."""
    if user.role == "student" and report.workflow_status != "published":
        raise HTTPException(status_code=404, detail="报告尚未发布")


def _ensure_measurement_owned_by_student(run: AssessmentRun, user: User) -> None:
    if run.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权查看其他学生的测量结果")


async def _measurement_out(
    measurement: MetacognitionMeasurement,
    db: AsyncSession,
) -> MetacognitionMeasurementOut:
    task_ids = list(measurement.task_ids or [])
    tasks = list((await db.scalars(
        select(AssessmentTask).where(AssessmentTask.id.in_(task_ids))
    )).all()) if task_ids else []
    task_name_by_id = {task.id: task.title for task in tasks}
    return MetacognitionMeasurementOut(
        id=measurement.id,
        user_id=measurement.user_id,
        run_id=measurement.run_id,
        scope_type=measurement.scope_type,
        scope_key=measurement.scope_key,
        task_id=measurement.task_id,
        task_name=(task_name_by_id.get(measurement.task_id) if measurement.task_id else None),
        task_ids=task_ids,
        task_names=[task_name_by_id.get(task_id, "未知任务") for task_id in task_ids],
        effective_dialogue_count=measurement.effective_dialogue_count,
        denominator_breakdown=getattr(measurement, "denominator_breakdown", {}),
        fallback_dialogue_count=getattr(measurement, "fallback_dialogue_count", 0),
        unclassified_count=getattr(measurement, "unclassified_count", 0),
        dimension_counts={
            "monitoring": measurement.monitoring_count,
            "control_debugging": measurement.control_debugging_count,
            "evaluation": measurement.evaluation_count,
        },
        dimension_scores={
            "monitoring": measurement.monitoring_score,
            "control_debugging": measurement.control_debugging_score,
            "evaluation": measurement.evaluation_score,
        },
        score_available=measurement.score_available,
        source=measurement.source,
        data_version=measurement.data_version,
        calculated_at=measurement.calculated_at,
        completed_at=measurement.completed_at,
    )


@router.get("/measurement-corrections/template")
async def measurement_correction_template(user: User = Depends(require_role("admin"))):
    return Response(
        "\ufeff会话ID,校对文本,最终标签\r\n",
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="measurement-correction-template.csv"'},
    )


@router.post("/measurement-corrections")
async def upload_measurement_corrections(
    file: UploadFile = File(...), confirmed: bool = Form(False),
    user: User = Depends(require_role("admin")), db: AsyncSession = Depends(get_db),
):
    # Also enforced here for direct calls; teacher/student cannot upload by API.
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以上传校对结果")
    if not confirmed:
        raise HTTPException(status_code=422, detail="请确认文件包含每个所列会话的完整有效对话及最终标签")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="请使用 UTF-8 CSV 校对模板")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        grouped = parse_correction_csv(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Validate the whole upload before writing anything. Lock sessions to serialize
    # concurrent corrections and give versions an unambiguous chronological order.
    sessions = list((await db.scalars(select(AssessmentSession).join(
        AssessmentRun, AssessmentRun.id == AssessmentSession.run_id,
    ).where(
        AssessmentSession.id.in_(grouped), AssessmentRun.status == "completed",
        AssessmentRun.completed_at.is_not(None),
    ).order_by(AssessmentSession.id).with_for_update())).all())
    if {s.id for s in sessions} != set(grouped):
        raise HTTPException(status_code=422, detail="存在未知会话ID或尚未完成的测评；整个文件未导入")
    now = utc_now_naive()
    versions = []
    for session in sessions:
        version_no = int(await db.scalar(select(func.max(MeasurementCorrection.version_no)).where(
            MeasurementCorrection.session_id == session.id,
        )) or 0) + 1
        row = MeasurementCorrection(
            id=str(uuid.uuid4()), session_id=session.id, uploaded_by=user.id,
            version_no=version_no,
            filename=PurePosixPath((file.filename or "").replace("\\", "/")).name[:255],
            file_sha256=hashlib.sha256(content).hexdigest(), dialogues=grouped[session.id],
            dimension_counts=correction_counts(grouped[session.id]),
            effective_dialogue_count=len(grouped[session.id]), created_at=now,
        )
        db.add(row)
        versions.append(row.id)
    db.add(AuditLog(
        actor_id=user.id, action="measurement_correction_upload", target_type="measurement_correction",
        detail={"version_ids": versions, "session_ids": list(grouped), "row_count": sum(map(len, grouped.values()))},
    ))
    await db.flush()
    return {"session_count": len(sessions), "dialogue_count": sum(map(len, grouped.values())), "version_ids": versions}


@router.get("", response_model=list[ReportBriefOut])
async def list_reports(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前学生的历次完整测评报告。"""
    statement = select(MetacognitiveProfile).where(
        MetacognitiveProfile.user_id == user.id
    )
    if user.role == "student":
        statement = statement.where(
            MetacognitiveProfile.workflow_status == "published"
        )
    result = await db.execute(
        statement.order_by(MetacognitiveProfile.generated_at.desc())
    )
    return [ReportBriefOut.model_validate(report) for report in result.scalars().all()]


@router.get(
    "/metacognition-measurements",
    response_model=MetacognitionMeasurementPageOut,
)
async def list_metacognition_measurements(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    """Return the current student's completed runs in authoritative time order."""
    base_filter = (
        AssessmentRun.user_id == user.id,
        AssessmentRun.status == "completed",
        AssessmentRun.completed_at.is_not(None),
    )
    total = int(await db.scalar(
        select(func.count(AssessmentRun.id)).where(*base_filter)
    ) or 0)
    runs = list((await db.scalars(
        select(AssessmentRun)
        .where(*base_filter)
        .order_by(AssessmentRun.completed_at.desc(), AssessmentRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all())
    session_evidence = await load_session_evidence([run.id for run in runs], db)
    items = [
        await _measurement_out(await calculate_and_persist_measurement(run, db, session_evidence=session_evidence), db)
        for run in runs
    ]
    return MetacognitionMeasurementPageOut(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/metacognition-measurements/{run_id}",
    response_model=MetacognitionMeasurementOut,
)
async def get_metacognition_measurement(
    run_id: str,
    task_id: str | None = Query(default=None),
    user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    """Return one own-run measurement; the ownership check prevents IDOR."""
    run = await db.get(AssessmentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="完整测评不存在")
    _ensure_measurement_owned_by_student(run, user)
    if run.status != "completed" or run.completed_at is None:
        raise HTTPException(status_code=409, detail="完整测评尚未结束")
    try:
        measurement = await calculate_and_persist_measurement(run, db, task_id=task_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return await _measurement_out(measurement, db)


@router.post("/runs/{run_id}/generate", response_model=ReportOut)
async def generate_report(
    run_id: str,
    data: ReportGenerateIn | None = None,
    user: User = Depends(require_role("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """对双任务转录进行编码，并按运行快照选择是否合并任务后问卷。"""
    run = await _ensure_run_access(run_id, user, db)
    if run.status != "completed":
        raise HTTPException(status_code=409, detail="完整测评尚未结束，不能生成报告")
    previous_profile = await _load_profile(run_id=run_id, db=db)
    try:
        await generate_run_report(
            run_id,
            db,
            reanalyze=(data.reanalyze if data else False),
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    report = await _load_profile(run_id=run_id, db=db)
    if report is None:
        raise HTTPException(status_code=500, detail="报告生成失败")
    if previous_profile is None:
        if report.requires_review_count > 0:
            student = await db.get(User, run.user_id)
            if student is not None:
                await notify_reviewers(
                    db,
                    student=student,
                    event_key_prefix=f"report-review-pending:{report.id}",
                    title="有新的编码等待复核",
                    content=f"一份测评报告包含 {report.requires_review_count} 条低置信度编码。",
                    metadata={"run_id": run.id, "report_id": report.id},
                )
    return _report_out(report)


@router.get("/runs/{run_id}", response_model=ReportOut)
async def get_report_by_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_run_access(run_id, user, db)
    report = await _load_profile(run_id=run_id, db=db)
    if report is None:
        raise HTTPException(status_code=404, detail="该测评尚未生成报告")
    _ensure_report_visible_to_user(report, user)
    return _report_out(report)


@router.get("/review/pending")
async def list_pending_codings(
    user: User = Depends(get_current_user),
):
    """Retired single-review queue retained as an explicit tombstone."""
    del user
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=LEGACY_REVIEW_DETAIL)


@router.patch("/codings/{coding_id}")
async def review_coding(
    coding_id: str,
    user: User = Depends(get_current_user),
):
    """Retired single-review write endpoint retained as a tombstone."""
    del coding_id, user
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=LEGACY_REVIEW_DETAIL)


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(
    report_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按报告 ID 获取详情。"""
    report = await _load_profile(profile_id=report_id, db=db)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    owner = await db.get(User, report.user_id)
    if owner is None or not can_access_user(user, owner):
        raise HTTPException(status_code=403, detail="无权查看此报告")
    _ensure_report_visible_to_user(report, user)
    return _report_out(report)
