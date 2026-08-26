"""Complete assessment reports, evidence coding, and human review."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import can_access_user, get_current_user, require_role
from app.database import get_db
from app.models.protocol import AssessmentRun
from app.models.report import MetacognitiveProfile
from app.models.session import AssessmentSession, CodedSegment
from app.models.user import User
from app.schemas.report import (
    CodingReviewIn,
    CodingReviewOut,
    ReportBriefOut,
    ReportGenerateIn,
    ReportOut,
)
from app.services.report_analyzer import generate_run_report
from app.services.notifications import create_notification, notify_reviewers

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


@router.get("/review/pending", response_model=list[CodingReviewOut])
async def list_pending_codings(
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """教师或管理员查看低置信度、尚未人工确认的编码片段。"""
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=LEGACY_REVIEW_DETAIL)
    if user.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="仅教师或管理员可进行人工复核")
    statement = (
        select(CodedSegment, User)
        .join(AssessmentSession, AssessmentSession.id == CodedSegment.session_id)
        .join(User, User.id == AssessmentSession.user_id)
        .where(
            CodedSegment.needs_review.is_(True),
            CodedSegment.human_score.is_(None),
        )
    )
    rows = [row for row in (await db.execute(statement)).all() if can_access_user(user, row[1])]
    response.headers["X-Total-Count"] = str(len(rows))
    start = (page - 1) * page_size
    return [CodingReviewOut.model_validate(code) for code, _ in rows[start:start + page_size]]


@router.patch("/codings/{coding_id}", response_model=CodingReviewOut)
async def review_coding(
    coding_id: str,
    data: CodingReviewIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """保存人工评分；人工分数在报告聚合时优先于 AI 分数。"""
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=LEGACY_REVIEW_DETAIL)
    if user.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="仅教师或管理员可进行人工复核")
    result = await db.execute(
        select(CodedSegment)
        .where(CodedSegment.id == coding_id)
        .options(selectinload(CodedSegment.session))
    )
    coding = result.scalar_one_or_none()
    if coding is None:
        raise HTTPException(status_code=404, detail="编码片段不存在")
    owner = await db.get(User, coding.session.user_id)
    if owner is None or not can_access_user(user, owner):
        raise HTTPException(status_code=403, detail="无权复核该学生的编码")

    coding.human_score = data.human_score
    coding.review_note = data.review_note.strip()
    coding.needs_review = False
    await db.flush()
    if coding.session.run_id:
        await generate_run_report(coding.session.run_id, db, reanalyze=False)
        await create_notification(
            db,
            user_id=coding.session.user_id,
            type="report",
            title="报告复核处理中",
            content=(
                "初步人工复核已完成，仍需完成研究审核与发布；"
                "正式发布后系统会再次通知你。"
            ),
            target_url=f"/report?run={coding.session.run_id}",
            event_key=f"coding-reviewed:{coding.id}:{coding.session.user_id}",
            metadata={
                "run_id": coding.session.run_id,
                "coding_id": coding.id,
            },
        )
    return CodingReviewOut.model_validate(coding)


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
