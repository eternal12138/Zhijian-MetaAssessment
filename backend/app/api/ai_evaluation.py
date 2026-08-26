"""Role-aware, auditable metacognitive classification over reviewed candidates."""
from __future__ import annotations

from collections import Counter
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.models.extraction import ExtractionCandidate, ExtractionJob
from app.models.research import AuditLog, ModelTrainingJob
from app.models.session import AssessmentSession
from app.models.task import AssessmentTask
from app.models.user import User
from app.schemas.ai_evaluation import (
    AiEvaluationModelOut, AiEvaluationOverviewOut, AiEvaluationRunIn,
    AiEvaluationRunOut, AiEvaluationScopeOut,
)
from app.services.model_inference import classify_candidates
from app.services.model_metrics_service import group_evaluations
from app.services.model_training_datasets import load_dataset_samples
from app.config import get_settings

router = APIRouter(prefix="/research/ai-evaluation", tags=["AI 元认知评估"])
settings = get_settings()
logger = logging.getLogger(__name__)

EXPERIMENT_NAMES = {
    "tfidf_linear_svc": "TF-IDF + LinearSVC",
    "embedding_linear_svc": "远程 Embedding + LinearSVC",
    "embedding_logistic": "远程 Embedding + LogisticRegression",
    "embedding_random_forest": "远程 Embedding + RandomForest",
    "embedding_xgboost": "远程 Embedding + XGBoost",
    "embedding_lightgbm": "远程 Embedding + LightGBM",
    "embedding_catboost": "远程 Embedding + CatBoost",
}
ELIGIBLE_REVIEW_STATUSES = ("accepted", "pending")


def _require_operator(user: User) -> None:
    if user.role not in {"teacher", "admin"}:
        raise HTTPException(403, "仅教师或管理员可使用 AI 评估")


def candidate_text_source(review_status: str) -> str:
    """Accepted text is human-reviewed; pending text remains the AI candidate."""
    return "human_review" if review_status == "accepted" else "ai_candidate"


def _managed_classes(user: User) -> set[str]:
    return {item.strip() for item in (user.managed_classes or "").split(",") if item.strip()}


def _latest_jobs_subquery():
    ranked = select(
        ExtractionJob.id.label("job_id"),
        ExtractionJob.session_id.label("session_id"),
        func.row_number().over(
            partition_by=ExtractionJob.session_id,
            order_by=(ExtractionJob.created_at.desc(), ExtractionJob.id.desc()),
        ).label("rank_no"),
    ).where(ExtractionJob.status.in_(("completed", "reviewing", "reviewed"))).subquery()
    return select(ranked.c.job_id, ranked.c.session_id).where(ranked.c.rank_no == 1).subquery()


def _visible_condition(user: User):
    if user.role == "admin":
        return None
    classes = _managed_classes(user)
    return User.class_group.in_(classes) if classes else User.id == "__no_visible_student__"


def _metric(job: ModelTrainingJob, name: str) -> float | None:
    value = (job.metrics or {}).get(name)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _model_cards(db: AsyncSession) -> tuple[list[ModelTrainingJob], str | None]:
    jobs = list((await db.scalars(
        select(ModelTrainingJob)
        .where(ModelTrainingJob.status == "completed", ModelTrainingJob.artifact_path.is_not(None))
        .order_by(ModelTrainingJob.completed_at.desc(), ModelTrainingJob.created_at.desc())
    )).all())
    by_id = {job.id: job for job in jobs}
    evaluation_index = group_evaluations(jobs, settings.model_training_path)
    comparison = next(
        (item for item in evaluation_index["versions"] if len(item["models"]) == len(EXPERIMENT_NAMES)),
        next(
            (item for item in evaluation_index["versions"] if len(item["models"]) == 4),
            evaluation_index["versions"][0] if evaluation_index["versions"] else None,
        ),
    )
    if comparison is not None:
        compared_jobs = [
            by_id[item["model_id"]] for item in comparison["models"]
            if item["model_id"] in by_id
        ]
        if compared_jobs:
            return compared_jobs, comparison.get("best_model_id")
    latest: dict[str, ModelTrainingJob] = {}
    for job in jobs:
        kind = str((job.config_snapshot or {}).get("experiment_type") or "")
        if kind in EXPERIMENT_NAMES and kind not in latest:
            latest[kind] = job
    ordered = [latest[kind] for kind in EXPERIMENT_NAMES if kind in latest]
    # Historical jobs from different datasets must not be ranked against each
    # other. A best marker is only emitted by the validated comparison group.
    return ordered, None


def _model_out(job: ModelTrainingJob, best_id: str | None) -> AiEvaluationModelOut:
    snapshot = job.config_snapshot or {}
    kind = str(snapshot.get("experiment_type") or "")
    return AiEvaluationModelOut(
        id=job.id, version=job.version, experiment_type=kind,
        display_name=str(snapshot.get("display_name") or EXPERIMENT_NAMES.get(kind) or kind),
        macro_f1=_metric(job, "macro_f1"), weighted_f1=_metric(job, "weighted_f1"),
        is_active=job.is_active, is_best=job.id == best_id, completed_at=job.completed_at,
    )


def _training_provenance(active: ModelTrainingJob | None) -> tuple[str, str, set[str]]:
    if active is None:
        return "none", "管理员尚未启用分类模型", set()
    snapshot = active.config_snapshot or {}
    source = str(snapshot.get("dataset_source") or "system_gold")
    name = str(snapshot.get("dataset_name") or "未命名训练数据")
    if source == "uploaded":
        return "uploaded", f"模型训练数据来自外部上传：{name}", set()
    dataset_id = str(snapshot.get("dataset_id") or "")
    participant_ids: set[str] = set()
    if dataset_id:
        try:
            participant_ids = {
                str(participant_id) for participant_id, _text, _label
                in load_dataset_samples(settings.model_training_path, dataset_id)
                if str(participant_id).strip()
            }
        except ValueError:
            participant_ids = set()
    return "system_gold", f"模型训练数据来自系统专家金标准：{name}", participant_ids


@router.get("/overview", response_model=AiEvaluationOverviewOut)
async def overview(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    _require_operator(user)
    model_jobs, best_id = await _model_cards(db)
    active = next((job for job in model_jobs if job.is_active), None)
    if active is None:
        active = await db.scalar(select(ModelTrainingJob).where(
            ModelTrainingJob.is_active.is_(True), ModelTrainingJob.status == "completed",
        ))
    training_source, training_label, training_participants = _training_provenance(active)
    latest_jobs = _latest_jobs_subquery()
    classified_condition = and_(
        ExtractionCandidate.classifier_job_id == (active.id if active else ""),
        ExtractionCandidate.review_status.in_(ELIGIBLE_REVIEW_STATUSES),
    )
    classified = case((classified_condition, 1), else_=0)
    statement = (
        select(
            AssessmentSession.id, User.id, User.name, User.username, User.class_group,
            AssessmentTask.id, AssessmentTask.title, AssessmentSession.end_time,
            func.count(ExtractionCandidate.id),
            func.sum(case((ExtractionCandidate.review_status == "accepted", 1), else_=0)),
            func.sum(case((ExtractionCandidate.review_status == "pending", 1), else_=0)),
            func.sum(case((ExtractionCandidate.review_status == "rejected", 1), else_=0)),
            func.sum(classified),
            func.sum(case((and_(classified_condition, ExtractionCandidate.predicted_dimension == "monitoring"), 1), else_=0)),
            func.sum(case((and_(classified_condition, ExtractionCandidate.predicted_dimension == "controlDebugging"), 1), else_=0)),
            func.sum(case((and_(classified_condition, ExtractionCandidate.predicted_dimension == "evaluation"), 1), else_=0)),
        )
        .join(latest_jobs, latest_jobs.c.session_id == AssessmentSession.id)
        .join(ExtractionCandidate, ExtractionCandidate.extraction_job_id == latest_jobs.c.job_id)
        .join(User, User.id == AssessmentSession.user_id)
        .join(AssessmentTask, AssessmentTask.id == AssessmentSession.task_id)
        .group_by(
            AssessmentSession.id, User.id, User.name, User.username, User.class_group,
            AssessmentTask.id, AssessmentTask.title, AssessmentSession.end_time,
        )
        .order_by(AssessmentSession.end_time.desc(), AssessmentSession.id.desc())
    )
    visibility = _visible_condition(user)
    if visibility is not None:
        statement = statement.where(visibility)
    rows = (await db.execute(statement)).all()
    scope_items = [AiEvaluationScopeOut(
        session_id=row[0], participant_id=row[1], participant_name=row[2], username=row[3],
        class_group=row[4], task_id=row[5], task_title=row[6], completed_at=row[7],
        candidate_count=int(row[8] or 0), reviewed_count=int(row[9] or 0),
        pending_count=int(row[10] or 0), rejected_count=int(row[11] or 0),
        classified_count=int(row[12] or 0), training_participant=row[1] in training_participants,
        dimension_counts={"monitoring": int(row[13] or 0), "regulation": int(row[14] or 0), "evaluation": int(row[15] or 0)},
    ) for row in rows]
    return AiEvaluationOverviewOut(
        enabled=active is not None, can_activate=user.role == "admin",
        active_model=_model_out(active, best_id) if active else None,
        best_model_id=best_id, models=[_model_out(job, best_id) for job in model_jobs],
        training_source=training_source, training_source_label=training_label,
        scope_items=scope_items,
    )


@router.post("/classify", response_model=AiEvaluationRunOut)
async def classify_scope(
    data: AiEvaluationRunIn, db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_operator(user)
    active = await db.scalar(select(ModelTrainingJob).where(
        ModelTrainingJob.is_active.is_(True), ModelTrainingJob.status == "completed",
    ))
    if active is None:
        raise HTTPException(409, "管理员尚未启用分类模型")
    latest_jobs = _latest_jobs_subquery()
    statement = (
        select(ExtractionCandidate)
        .join(latest_jobs, latest_jobs.c.job_id == ExtractionCandidate.extraction_job_id)
        .join(AssessmentSession, AssessmentSession.id == ExtractionCandidate.session_id)
        .join(User, User.id == AssessmentSession.user_id)
        .where(
            ExtractionCandidate.review_status.in_(ELIGIBLE_REVIEW_STATUSES),
            func.length(func.trim(ExtractionCandidate.clean_text)) > 0,
            or_(
                ExtractionCandidate.classifier_job_id.is_(None),
                ExtractionCandidate.classifier_job_id != active.id,
                ExtractionCandidate.classification_status.not_in(("classified", "classified_with_fallback")),
            ),
        )
        .order_by(ExtractionCandidate.session_id, ExtractionCandidate.sequence_no)
    )
    visibility = _visible_condition(user)
    if visibility is not None:
        statement = statement.where(visibility)
    if data.scope != "all":
        if not data.ids:
            raise HTTPException(422, "请选择需要评估的数据范围")
        target = {
            "student": ExtractionCandidate.user_id,
            "session": ExtractionCandidate.session_id,
            "task": ExtractionCandidate.task_id,
        }[data.scope]
        statement = statement.where(target.in_(data.ids))
    batch = list((await db.scalars(statement.limit(data.batch_size))).all())
    if batch:
        try:
            await classify_candidates(db, batch)
            # Force cache and prediction audit writes here so database failures
            # are reported as a classification error instead of a generic 500
            # from a later query-triggered autoflush.
            await db.flush()
        except Exception as error:
            await db.rollback()
            logger.exception(
                "AI candidate classification failed model=%s batch_size=%s",
                active.id, len(batch),
            )
            raise HTTPException(409, f"分类模型执行失败：{error}") from error
    remaining = int(await db.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ) or 0)
    sources = Counter(candidate_text_source(item.review_status) for item in batch)
    dimensions = Counter(item.predicted_dimension for item in batch if item.predicted_dimension)
    rejected_statement = (
        select(func.count(ExtractionCandidate.id))
        .join(latest_jobs, latest_jobs.c.job_id == ExtractionCandidate.extraction_job_id)
        .join(AssessmentSession, AssessmentSession.id == ExtractionCandidate.session_id)
        .join(User, User.id == AssessmentSession.user_id)
        .where(ExtractionCandidate.review_status == "rejected")
    )
    if visibility is not None:
        rejected_statement = rejected_statement.where(visibility)
    if data.scope != "all":
        target = {"student": ExtractionCandidate.user_id, "session": ExtractionCandidate.session_id, "task": ExtractionCandidate.task_id}[data.scope]
        rejected_statement = rejected_statement.where(target.in_(data.ids))
    rejected = int(await db.scalar(rejected_statement) or 0)
    db.add(AuditLog(
        actor_id=user.id, action="ai_evaluation.classify", target_type="model_training_job",
        target_id=active.id, detail={
            "scope": data.scope, "ids": data.ids, "processed": len(batch),
            "remaining": remaining, "human_review": sources["human_review"],
            "ai_candidate": sources["ai_candidate"], "skipped_rejected": rejected,
        },
    ))
    await db.commit()
    return AiEvaluationRunOut(
        model_id=active.id, model_version=active.version, processed=len(batch),
        remaining=remaining, skipped_rejected=rejected,
        source_counts=dict(sources), dimension_counts={str(key): value for key, value in dimensions.items()},
    )
