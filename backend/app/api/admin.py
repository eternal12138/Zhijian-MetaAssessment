"""管理路由 —— 用户管理 / 评分规则 / 提示词版本 / 一致性校验"""
from datetime import datetime, timezone
from pathlib import Path
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field, field_validator

from app.database import get_db
from app.models.user import User
from app.models.task import AssessmentTask
from app.models.session import (
    AssessmentSession,
    AudioChunk,
    CodedSegment,
    DialogueTurn,
    InteractionEvent,
    TranscriptSegment,
)
from app.models.protocol import AssessmentRun, QuestionnaireResponse
from app.models.asr import AsrJob, TranscriptVersion
from app.models.extraction import ExtractionCandidate, ExtractionCandidateRevision, ExtractionJob
from app.models.report import ConsistencyReport, LearningSuggestion, MetacognitiveProfile
from app.models.research import (
    AnalysisJob,
    AuditLog,
    CodingAdjudication,
    CodingAnnotation,
    CodingUnit,
    CodingUnitAdjudication,
    CodingUnitAnnotation,
    RunQualityReview,
)
from app.core.security import require_role, hash_password
from app.core.time import as_utc
from app.config import get_settings
from app.schemas.diagnostics import (
    ModelServicesDiagnosticsOut,
    QuotaDiagnosticOut,
)
from app.schemas.model_services_config import (
    ModelConfigHistoryOut,
    ModelServicesConfigOut,
    ModelServicesConfigUpdate,
)
from app.schemas.protocol import ProtocolConfigOut, ProtocolConfigUpdate
from app.services.model_diagnostics import ModelDiagnosticsService
from app.services.runtime_model_config import (
    list_runtime_model_history,
    load_runtime_model_settings,
    model_services_config_view,
    save_runtime_model_settings,
    rollback_runtime_model_settings,
)
from app.services.protocol_config import load_protocol_config, save_protocol_config

router = APIRouter(prefix="/admin", tags=["研究管理"])
settings = get_settings()

# ==================== 请求/响应模型 ====================

class BulkDataImpactRequest(BaseModel):
    run_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("run_ids")
    @classmethod
    def normalize_run_ids(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not normalized:
            raise ValueError("至少选择一条测评记录")
        return normalized

class UserAdminCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(default="123456", min_length=6, max_length=128)
    name: str = Field(..., min_length=1, max_length=64)
    role: str = Field(default="student", pattern="^(student|teacher|admin)$")
    class_group: str | None = Field(default=None, max_length=64)
    managed_classes: str | None = Field(default=None, max_length=512)

    @field_validator("username", "name", "class_group", mode="before")
    @classmethod
    def strip_text_fields(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None

    @field_validator("managed_classes", mode="before")
    @classmethod
    def normalize_managed_classes(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        classes = []
        seen = set()
        for item in re.split(r"[,，;；、|]+", value):
            class_name = item.strip()
            if class_name and class_name not in seen:
                seen.add(class_name)
                classes.append(class_name)
        return ",".join(classes) or None

class BatchUserCreate(BaseModel):
    users: list[UserAdminCreate] = Field(..., min_length=1, max_length=1000)

class ChangePasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)

class AdminResetPasswordRequest(BaseModel):
    user_id: str
    new_password: str = Field(default="123456", min_length=6, max_length=128)

class ToggleStatusRequest(BaseModel):
    user_id: str


class BulkUserActionRequest(BaseModel):
    user_ids: list[str] = Field(..., min_length=1, max_length=500)
    action: str = Field(pattern="^(freeze|unfreeze|reset_password|assign_class)$")
    class_group: str | None = Field(default=None, max_length=64)


class StudentClassAssignmentRequest(BaseModel):
    class_group: str = Field(..., min_length=1, max_length=64)

    @field_validator("class_group", mode="before")
    @classmethod
    def normalize_class_group(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip()


class DeleteUserRequest(BaseModel):
    user_id: str

class UserAdminOut(BaseModel):
    id: str
    username: str
    name: str
    role: str
    avatar_text: str
    class_group: str | None = None
    managed_classes: str | None = None
    is_active: bool
    must_change_password: bool
    can_manage_users: bool
    model_config = {"from_attributes": True}

# ==================== 用户管理 API ====================

@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    search: str = Query(default="", max_length=100),
    role: str = Query(default=""),
    account_status: str = Query(default=""),
    class_group: str = Query(default="", max_length=100),
    sort_by: str = Query(default="name"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("teacher", "admin"))
):
    """列出用户：管理员看全部，教师仅看自己和负责班级内的学生。"""
    statement = select(User)
    if not current_user.can_manage_users:
        managed_classes = [
            item.strip()
            for item in (current_user.managed_classes or "").split(",")
            if item.strip()
        ]
        visibility_filter = User.username == current_user.username
        if managed_classes:
            visibility_filter = visibility_filter | (
                (User.role == "student")
                & User.class_group.in_(managed_classes)
            )
        statement = statement.where(visibility_filter)
    keyword = search.strip()
    if keyword:
        statement = statement.where(or_(
            User.name.ilike(f"%{keyword}%"),
            User.username.ilike(f"%{keyword}%"),
        ))
    if role in {"student", "teacher", "admin"}:
        statement = statement.where(User.role == role)
    if account_status == "active":
        statement = statement.where(User.is_active.is_(True))
    elif account_status == "inactive":
        statement = statement.where(User.is_active.is_(False))
    if class_group.strip():
        class_keyword = class_group.strip()
        statement = statement.where(or_(
            User.class_group == class_keyword,
            User.managed_classes.ilike(f"%{class_keyword}%"),
        ))
    total = int(await db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    order_column = {
        "username": User.username,
        "class": User.class_group,
        "role": User.role,
    }.get(sort_by, User.name)
    result = await db.execute(
        statement.order_by(order_column.asc(), User.username.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return result.scalars().all()


@router.get("/users/classes", response_model=list[str])
async def list_user_classes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("teacher", "admin")),
):
    if current_user.can_manage_users:
        rows = (await db.execute(
            select(User.class_group).where(User.class_group.is_not(None)).distinct()
        )).scalars().all()
        return sorted({value.strip() for value in rows if value and value.strip()})
    return sorted({
        value.strip()
        for value in (current_user.managed_classes or "").split(",")
        if value.strip()
    })


def _user_class_fields(data: UserAdminCreate) -> tuple[str | None, str | None]:
    """将学生所属班级与教师负责班级存入各自的权威字段。"""
    if data.role == "student":
        return data.class_group, None
    if data.role == "teacher":
        return None, data.managed_classes or data.class_group
    return None, None


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserAdminCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """新增单个用户"""
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该账号已存在")

    class_group, managed_classes = _user_class_fields(data)
    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        name=data.name,
        role=data.role,
        avatar_text=data.name[0],
        class_group=class_group,
        managed_classes=managed_classes,
        must_change_password=(data.password == "123456"),
        can_manage_users=(data.role == "admin")
    )
    db.add(user)
    await db.commit()
    return {"status": "success", "message": f"用户 {data.username} 创建成功"}


@router.post("/users/batch", status_code=status.HTTP_201_CREATED)
async def batch_create_users(
    data: BatchUserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """批量新增用户；学生班级与教师负责班级均可稍后分配。"""
    usernames = [user.username for user in data.users]
    existing_result = await db.execute(
        select(User.username).where(User.username.in_(usernames))
    )
    existing_usernames = set(existing_result.scalars().all())
    payload_usernames: set[str] = set()
    success, errors = 0, []

    for u in data.users:
        if u.username in payload_usernames:
            errors.append(f"账号 {u.username} 在导入内容中重复，跳过")
            continue
        payload_usernames.add(u.username)

        if u.username in existing_usernames:
            errors.append(f"账号 {u.username} 已存在，跳过")
            continue

        class_group, managed_classes = _user_class_fields(u)
        user = User(
            username=u.username,
            password_hash=hash_password(u.password),
            name=u.name,
            role=u.role,
            avatar_text=u.name[0],
            class_group=class_group,
            managed_classes=managed_classes,
            must_change_password=(u.password == "123456"),
            can_manage_users=(u.role == "admin")
        )
        db.add(user)
        success += 1
    await db.commit()
    return {
        "status": "success",
        "message": f"成功创建 {success} 个账号，跳过 {len(errors)} 个",
        "created": success,
        "skipped": len(errors),
        "errors": errors,
    }


@router.post("/users/toggle-status")
async def toggle_user_status(
    data: ToggleStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """冻结/解冻账号"""
    user = await db.get(User, data.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.username == current_user.username:
        raise HTTPException(status_code=400, detail="不能冻结自己")
    user.is_active = not user.is_active
    await db.commit()
    return {"status": "success", "message": "状态已更新"}


@router.post("/users/bulk-action")
async def bulk_user_action(
    data: BulkUserActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Apply a single auditable administrator action to many accounts."""
    unique_ids = list(dict.fromkeys(data.user_ids))
    users = list((await db.scalars(select(User).where(User.id.in_(unique_ids)))).all())
    by_id = {item.id: item for item in users}
    processed = 0
    errors: list[str] = []
    class_group = (data.class_group or "").strip()
    if data.action == "assign_class" and not class_group:
        raise HTTPException(status_code=422, detail="批量分班时必须填写班级")
    for user_id in unique_ids:
        target = by_id.get(user_id)
        if target is None:
            errors.append(f"用户 {user_id} 不存在")
            continue
        if target.id == current_user.id and data.action == "freeze":
            errors.append(f"{target.name}：不能冻结当前登录账号")
            continue
        if data.action == "freeze":
            target.is_active = False
        elif data.action == "unfreeze":
            target.is_active = True
        elif data.action == "reset_password":
            target.password_hash = hash_password("123456")
            target.must_change_password = True
            target.failed_login_attempts = 0
            target.locked_until = None
            target.token_version += 1
        elif data.action == "assign_class":
            if target.role == "student":
                target.class_group = class_group
            elif target.role == "teacher":
                target.managed_classes = class_group
            else:
                errors.append(f"{target.name}：管理员账号不使用班级范围")
                continue
        processed += 1
    await db.commit()
    return {
        "status": "success",
        "processed": processed,
        "skipped": len(errors),
        "errors": errors,
    }


@router.patch("/users/{user_id}/class-group", response_model=UserAdminOut)
async def assign_student_class_group(
    user_id: str,
    data: StudentClassAssignmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """为未分班学生或未设置负责班级的教师补充班级范围；不覆盖已有值。"""
    del current_user
    result = await db.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "student":
        if user.class_group and user.class_group.strip():
            raise HTTPException(status_code=409, detail="该学生已分配班级，不能重复分配")
        user.class_group = data.class_group
    elif user.role == "teacher":
        if user.managed_classes and user.managed_classes.strip():
            raise HTTPException(status_code=409, detail="该教师已设置负责班级，不能重复分配")
        user.managed_classes = data.class_group
    else:
        raise HTTPException(status_code=422, detail="管理员账号不使用班级范围")
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/users/reset-password")
async def admin_reset_password(
    data: AdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """管理员重置任意用户的密码"""
    user = await db.get(User, data.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = True
    user.failed_login_attempts = 0
    user.locked_until = None
    user.token_version += 1
    await db.commit()
    return {"status": "success", "message": "密码已重置，用户下次登录后必须修改"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """删除尚未产生关联数据的账号；已有研究数据时应冻结账号。"""
    if not current_user.can_manage_users:
        raise HTTPException(status_code=403, detail="仅超级管理员可删除用户")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.username == current_user.username:
        raise HTTPException(status_code=400, detail="不能删除自己")
    session_count = await db.scalar(
        select(func.count(AssessmentSession.id)).where(
            AssessmentSession.user_id == user.id
        )
    ) or 0
    if session_count:
        raise HTTPException(
            status_code=409,
            detail="该用户已有测评或实验数据，不能删除；请改为冻结账号",
        )
    try:
        await db.delete(user)
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="该用户仍被研究任务、编码或报告引用，不能删除；请改为冻结账号",
        ) from error
    return {"status": "success", "message": "用户已删除"}


def _safe_audio_path(storage_path: str | None) -> Path | None:
    """Resolve only files inside the configured audio root."""
    if not storage_path:
        return None
    root = settings.audio_upload_path.resolve()
    candidate = (root / storage_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _remove_audio_files(storage_paths: set[str]) -> tuple[int, int]:
    deleted = 0
    failed = 0
    for storage_path in storage_paths:
        target = _safe_audio_path(storage_path)
        if target is None:
            failed += 1
            continue
        try:
            if target.exists() and target.is_file():
                target.unlink()
                deleted += 1
        except OSError:
            failed += 1
    return deleted, failed


async def _data_run_or_404(run_id: str, db: AsyncSession) -> AssessmentRun:
    run = await db.get(AssessmentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="测评记录不存在")
    return run


async def _session_ids_for_run(run_id: str, db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(AssessmentSession.id).where(AssessmentSession.run_id == run_id)
    )
    return list(result.scalars().all())


async def _run_deletion_impact(run_id: str, db: AsyncSession) -> dict:
    await _data_run_or_404(run_id, db)
    session_ids = await _session_ids_for_run(run_id, db)
    if not session_ids:
        questionnaire_count = int(await db.scalar(
            select(func.count(QuestionnaireResponse.id)).where(QuestionnaireResponse.run_id == run_id)
        ) or 0)
        return {
            "session_count": 0, "audio_chunk_count": 0, "audio_file_count": 0,
            "transcript_version_count": 0, "transcript_segment_count": 0,
            "extraction_job_count": 0, "candidate_count": 0, "candidate_revision_count": 0,
            "coding_record_count": 0, "questionnaire_response_count": questionnaire_count,
        }
    coding_ids = select(CodedSegment.id).where(CodedSegment.session_id.in_(session_ids))
    unit_ids = select(CodingUnit.id).where(CodingUnit.session_id.in_(session_ids))
    jobs = list((await db.scalars(select(AsrJob).where(AsrJob.session_id.in_(session_ids)))).all())
    chunks = list((await db.scalars(select(AudioChunk).where(
        AudioChunk.session_id.in_(session_ids)
    ))).all())
    audio_files = {
        path for job in jobs for path in (job.source_audio_path, job.canonical_audio_path) if path
    }
    audio_files.update(chunk.storage_path for chunk in chunks if chunk.storage_path)
    coding_record_count = 0
    for statement in (
        select(func.count(CodedSegment.id)).where(CodedSegment.session_id.in_(session_ids)),
        select(func.count(CodingAnnotation.id)).where(CodingAnnotation.coding_id.in_(coding_ids)),
        select(func.count(CodingAdjudication.id)).where(CodingAdjudication.coding_id.in_(coding_ids)),
        select(func.count(CodingUnit.id)).where(CodingUnit.session_id.in_(session_ids)),
        select(func.count(CodingUnitAnnotation.id)).where(CodingUnitAnnotation.unit_id.in_(unit_ids)),
        select(func.count(CodingUnitAdjudication.id)).where(CodingUnitAdjudication.unit_id.in_(unit_ids)),
    ):
        coding_record_count += int(await db.scalar(statement) or 0)
    return {
        "session_count": len(session_ids),
        "audio_chunk_count": len(chunks),
        "audio_file_count": len(audio_files),
        "transcript_version_count": int(await db.scalar(select(func.count(TranscriptVersion.id)).where(
            TranscriptVersion.session_id.in_(session_ids)
        )) or 0),
        "transcript_segment_count": int(await db.scalar(select(func.count(TranscriptSegment.id)).where(
            TranscriptSegment.session_id.in_(session_ids)
        )) or 0),
        "extraction_job_count": int(await db.scalar(select(func.count(ExtractionJob.id)).where(
            ExtractionJob.session_id.in_(session_ids)
        )) or 0),
        "candidate_count": int(await db.scalar(select(func.count(ExtractionCandidate.id)).where(
            ExtractionCandidate.session_id.in_(session_ids)
        )) or 0),
        "candidate_revision_count": int(await db.scalar(select(func.count(ExtractionCandidateRevision.id)).where(
            ExtractionCandidateRevision.session_id.in_(session_ids)
        )) or 0),
        "coding_record_count": coding_record_count,
        "questionnaire_response_count": int(await db.scalar(select(func.count(QuestionnaireResponse.id)).where(
            QuestionnaireResponse.run_id == run_id
        )) or 0),
    }


@router.get("/data-records/{run_id}/deletion-impact")
async def get_run_deletion_impact(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    del current_user
    return await _run_deletion_impact(run_id, db)


@router.post("/data-records/bulk-deletion-impact")
async def get_bulk_run_deletion_impact(
    data: BulkDataImpactRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    del current_user
    impacts: dict[str, dict] = {}
    totals = {
        "session_count": 0, "audio_chunk_count": 0, "audio_file_count": 0,
        "transcript_version_count": 0, "transcript_segment_count": 0,
        "extraction_job_count": 0, "candidate_count": 0,
        "candidate_revision_count": 0, "coding_record_count": 0,
        "questionnaire_response_count": 0,
    }
    for run_id in data.run_ids:
        impact = await _run_deletion_impact(run_id, db)
        impacts[run_id] = impact
        for key in totals:
            totals[key] += int(impact.get(key) or 0)
    return {"run_count": len(impacts), "totals": totals, "items": impacts}


@router.get("/data-records")
async def list_data_records(
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
    category: str = "overview",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Return one page of aggregate-only research records, never full child rows."""
    page_size = min(100, max(10, page_size))
    page = max(1, page)
    if category not in {"overview", "audio", "transcripts", "questionnaire"}:
        raise HTTPException(status_code=422, detail="未知的数据分类")

    session_count = select(func.count(AssessmentSession.id)).where(
        AssessmentSession.run_id == AssessmentRun.id
    ).correlate(AssessmentRun).scalar_subquery()
    audio_count = (
        select(func.count(AudioChunk.id))
        .join(AssessmentSession, AssessmentSession.id == AudioChunk.session_id)
        .where(AssessmentSession.run_id == AssessmentRun.id)
        .correlate(AssessmentRun).scalar_subquery()
    )
    audio_size = (
        select(func.coalesce(func.sum(AudioChunk.size_bytes), 0))
        .join(AssessmentSession, AssessmentSession.id == AudioChunk.session_id)
        .where(AssessmentSession.run_id == AssessmentRun.id)
        .correlate(AssessmentRun).scalar_subquery()
    )
    transcript_count = (
        select(func.count(TranscriptSegment.id))
        .join(AssessmentSession, AssessmentSession.id == TranscriptSegment.session_id)
        .where(AssessmentSession.run_id == AssessmentRun.id)
        .correlate(AssessmentRun).scalar_subquery()
    )
    dialogue_count = (
        select(func.count(DialogueTurn.id))
        .join(AssessmentSession, AssessmentSession.id == DialogueTurn.session_id)
        .where(AssessmentSession.run_id == AssessmentRun.id)
        .correlate(AssessmentRun).scalar_subquery()
    )
    coding_count = (
        select(func.count(CodedSegment.id))
        .join(AssessmentSession, AssessmentSession.id == CodedSegment.session_id)
        .where(AssessmentSession.run_id == AssessmentRun.id)
        .correlate(AssessmentRun).scalar_subquery()
    )
    questionnaire_count = select(func.count(QuestionnaireResponse.id)).where(
        QuestionnaireResponse.run_id == AssessmentRun.id
    ).correlate(AssessmentRun).scalar_subquery()

    base_conditions = []
    normalized_keyword = keyword.strip()
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        base_conditions.append(or_(
            User.username.ilike(pattern),
            User.name.ilike(pattern),
            User.class_group.ilike(pattern),
            AssessmentRun.questionnaire_participant_name.ilike(pattern),
        ))

    category_condition = {
        "overview": None,
        "audio": audio_count > 0,
        "transcripts": (transcript_count + dialogue_count + coding_count) > 0,
        "questionnaire": or_(
            questionnaire_count > 0,
            func.coalesce(AssessmentRun.questionnaire_participant_name, "") != "",
        ),
    }[category]
    filtered_conditions = list(base_conditions)
    if category_condition is not None:
        filtered_conditions.append(category_condition)

    total = int(await db.scalar(
        select(func.count(AssessmentRun.id))
        .join(User, User.id == AssessmentRun.user_id)
        .where(*filtered_conditions)
    ) or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    safe_page = min(page, total_pages)

    category_row = (await db.execute(
        select(
            func.count(AssessmentRun.id),
            func.coalesce(func.sum(case((audio_count > 0, 1), else_=0)), 0),
            func.coalesce(func.sum(case(((transcript_count + dialogue_count + coding_count) > 0, 1), else_=0)), 0),
            func.coalesce(func.sum(case((or_(
                questionnaire_count > 0,
                func.coalesce(AssessmentRun.questionnaire_participant_name, "") != "",
            ), 1), else_=0)), 0),
        )
        .join(User, User.id == AssessmentRun.user_id)
        .where(*base_conditions)
    )).one()

    rows = (await db.execute(
        select(
            AssessmentRun, User,
            session_count.label("session_count"),
            audio_count.label("audio_chunk_count"),
            audio_size.label("audio_size_bytes"),
            transcript_count.label("transcript_count"),
            dialogue_count.label("dialogue_count"),
            coding_count.label("coded_segment_count"),
            questionnaire_count.label("questionnaire_response_count"),
        )
        .join(User, User.id == AssessmentRun.user_id)
        .where(*filtered_conditions)
        .order_by(AssessmentRun.started_at.desc(), AssessmentRun.id.desc())
        .offset((safe_page - 1) * page_size)
        .limit(page_size)
    )).all()

    run_ids = [run.id for run, *_rest in rows]
    task_map: dict[str, list[dict]] = {run_id: [] for run_id in run_ids}
    if run_ids:
        session_audio_count = select(func.count(AudioChunk.id)).where(
            AudioChunk.session_id == AssessmentSession.id
        ).correlate(AssessmentSession).scalar_subquery()
        session_transcript_count = select(func.count(TranscriptSegment.id)).where(
            TranscriptSegment.session_id == AssessmentSession.id
        ).correlate(AssessmentSession).scalar_subquery()
        task_rows = (await db.execute(
            select(
                AssessmentSession, AssessmentTask,
                session_audio_count.label("audio_chunk_count"),
                session_transcript_count.label("transcript_count"),
            )
            .join(AssessmentTask, AssessmentTask.id == AssessmentSession.task_id)
            .where(AssessmentSession.run_id.in_(run_ids))
            .order_by(AssessmentSession.run_id, AssessmentSession.sequence_no)
        )).all()
        for session, task, task_audio_count, task_transcript_count in task_rows:
            task_map.setdefault(session.run_id or "", []).append({
                "session_id": session.id,
                "task_title": task.title,
                "sequence_no": session.sequence_no,
                "status": session.status,
                "started_at": as_utc(session.start_time),
                "completed_at": as_utc(session.end_time) if session.end_time else None,
                "audio_chunk_count": int(task_audio_count or 0),
                "transcript_count": int(task_transcript_count or 0),
            })

    records = []
    for (
        run, user, run_session_count, run_audio_count, run_audio_size,
        run_transcript_count, run_dialogue_count, run_coding_count,
        run_questionnaire_count,
    ) in rows:
        records.append({
            "run_id": run.id,
            "user_id": user.id,
            "username": user.username,
            "name": user.name,
            "class_group": user.class_group,
            "questionnaire_participant_name": run.questionnaire_participant_name,
            "status": run.status,
            "current_stage": run.current_stage,
            "started_at": as_utc(run.started_at),
            "completed_at": as_utc(run.completed_at) if run.completed_at else None,
            "session_count": int(run_session_count or 0),
            "audio_chunk_count": int(run_audio_count or 0),
            "audio_size_bytes": int(run_audio_size or 0),
            "transcript_count": int(run_transcript_count or 0),
            "dialogue_count": int(run_dialogue_count or 0),
            "coded_segment_count": int(run_coding_count or 0),
            "questionnaire_response_count": int(run_questionnaire_count or 0),
            "questionnaire_enabled": run.questionnaire_enabled,
            "tasks": task_map.get(run.id, []),
        })
    return {
        "items": records,
        "total": total,
        "page": safe_page,
        "page_size": page_size,
        "total_pages": total_pages,
        "category_counts": {
            "overview": int(category_row[0] or 0),
            "audio": int(category_row[1] or 0),
            "transcripts": int(category_row[2] or 0),
            "questionnaire": int(category_row[3] or 0),
        },
    }


@router.delete("/data-records/{run_id}/audio")
async def delete_run_audio(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Delete browser chunks and canonical/source audio while retaining transcripts."""
    await _data_run_or_404(run_id, db)
    session_ids = await _session_ids_for_run(run_id, db)
    if not session_ids:
        return {"status": "success", "message": "该测评没有录音数据", "deleted_records": 0}

    chunk_result = await db.execute(
        select(AudioChunk).where(AudioChunk.session_id.in_(session_ids))
    )
    chunks = list(chunk_result.scalars().all())
    job_result = await db.execute(
        select(AsrJob).where(AsrJob.session_id.in_(session_ids))
    )
    jobs = list(job_result.scalars().all())
    storage_paths = {
        path
        for path in [
            *(item.storage_path for item in chunks),
            *(item.source_audio_path for item in jobs),
            *(item.canonical_audio_path for item in jobs),
        ]
        if path
    }

    await db.execute(delete(AudioChunk).where(AudioChunk.session_id.in_(session_ids)))
    await db.execute(
        update(AsrJob)
        .where(AsrJob.session_id.in_(session_ids))
        .values(
            source_audio_path=None,
            canonical_audio_path=None,
            status="audio_deleted",
            error_code="audio_deleted_by_admin",
            error_message="录音已由管理员删除",
        )
    )
    db.add(AuditLog(
        actor_id=current_user.id,
        action="delete_run_audio",
        target_type="assessment_run",
        target_id=run_id,
        detail={"audio_chunk_count": len(chunks), "file_count": len(storage_paths)},
    ))
    await db.commit()
    deleted_files, failed_files = _remove_audio_files(storage_paths)
    return {
        "status": "success",
        "message": "录音数据已删除",
        "deleted_records": len(chunks),
        "deleted_files": deleted_files,
        "failed_files": failed_files,
    }


@router.delete("/data-records/{run_id}/questionnaire")
async def delete_run_questionnaire(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Delete questionnaire answers and the participant-provided WeChat/name field."""
    run = await _data_run_or_404(run_id, db)
    count = await db.scalar(
        select(func.count(QuestionnaireResponse.id)).where(
            QuestionnaireResponse.run_id == run_id
        )
    ) or 0
    await db.execute(
        delete(QuestionnaireResponse).where(QuestionnaireResponse.run_id == run_id)
    )
    run.questionnaire_participant_name = None
    db.add(AuditLog(
        actor_id=current_user.id,
        action="delete_run_questionnaire",
        target_type="assessment_run",
        target_id=run_id,
        detail={"response_count": count},
    ))
    await db.commit()
    return {
        "status": "success",
        "message": "问卷作答和问卷填写的微信名已删除",
        "deleted_records": count,
    }


@router.delete("/data-records/{run_id}/transcripts")
async def delete_run_transcripts(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Delete transcript, dialogue and derived coding data but keep recordings."""
    await _data_run_or_404(run_id, db)
    session_ids = await _session_ids_for_run(run_id, db)
    if not session_ids:
        return {"status": "success", "message": "该测评没有转录数据", "deleted_records": 0}

    impact = await _run_deletion_impact(run_id, db)
    transcript_count = await db.scalar(
        select(func.count(TranscriptSegment.id)).where(
            TranscriptSegment.session_id.in_(session_ids)
        )
    ) or 0
    coding_ids = list((await db.execute(
        select(CodedSegment.id).where(CodedSegment.session_id.in_(session_ids))
    )).scalars().all())
    unit_ids = list((await db.execute(
        select(CodingUnit.id).where(CodingUnit.session_id.in_(session_ids))
    )).scalars().all())
    if coding_ids:
        await db.execute(delete(CodingAnnotation).where(CodingAnnotation.coding_id.in_(coding_ids)))
        await db.execute(delete(CodingAdjudication).where(CodingAdjudication.coding_id.in_(coding_ids)))
    if unit_ids:
        await db.execute(delete(CodingUnitAnnotation).where(CodingUnitAnnotation.unit_id.in_(unit_ids)))
        await db.execute(delete(CodingUnitAdjudication).where(CodingUnitAdjudication.unit_id.in_(unit_ids)))
        await db.execute(delete(CodingUnit).where(CodingUnit.id.in_(unit_ids)))
    await db.execute(delete(CodedSegment).where(CodedSegment.session_id.in_(session_ids)))
    await db.execute(delete(DialogueTurn).where(DialogueTurn.session_id.in_(session_ids)))
    await db.execute(delete(ExtractionCandidateRevision).where(ExtractionCandidateRevision.session_id.in_(session_ids)))
    await db.execute(delete(ExtractionCandidate).where(ExtractionCandidate.session_id.in_(session_ids)))
    await db.execute(update(ExtractionJob).where(
        ExtractionJob.session_id.in_(session_ids)
    ).values(supersedes_job_id=None))
    await db.execute(delete(ExtractionJob).where(ExtractionJob.session_id.in_(session_ids)))
    await db.execute(delete(TranscriptSegment).where(TranscriptSegment.session_id.in_(session_ids)))
    await db.execute(delete(TranscriptVersion).where(TranscriptVersion.session_id.in_(session_ids)))
    await db.execute(
        update(AsrJob)
        .where(AsrJob.session_id.in_(session_ids))
        .values(
            status="transcript_deleted",
            error_code="transcript_deleted_by_admin",
            error_message="转录及分析记录已由管理员删除",
        )
    )
    db.add(AuditLog(
        actor_id=current_user.id,
        action="delete_run_transcripts",
        target_type="assessment_run",
        target_id=run_id,
        detail={"transcript_count": transcript_count, "deletion_impact": impact},
    ))
    await db.commit()
    return {
        "status": "success",
        "message": "转录、对话和衍生编码数据已删除",
        "deleted_records": transcript_count,
    }


@router.delete("/data-records/{run_id}")
async def delete_complete_run_record(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Delete one complete assessment run and all dependent research records."""
    run = await _data_run_or_404(run_id, db)
    impact = await _run_deletion_impact(run_id, db)
    session_ids = await _session_ids_for_run(run_id, db)
    storage_paths: set[str] = set()
    await db.execute(delete(AnalysisJob).where(AnalysisJob.run_id == run_id))
    if session_ids:
        chunks = list((await db.execute(
            select(AudioChunk).where(AudioChunk.session_id.in_(session_ids))
        )).scalars().all())
        jobs = list((await db.execute(
            select(AsrJob).where(AsrJob.session_id.in_(session_ids))
        )).scalars().all())
        storage_paths.update(item.storage_path for item in chunks if item.storage_path)
        storage_paths.update(item.source_audio_path for item in jobs if item.source_audio_path)
        storage_paths.update(item.canonical_audio_path for item in jobs if item.canonical_audio_path)

        coding_ids = list((await db.execute(
            select(CodedSegment.id).where(CodedSegment.session_id.in_(session_ids))
        )).scalars().all())
        unit_ids = list((await db.execute(
            select(CodingUnit.id).where(CodingUnit.session_id.in_(session_ids))
        )).scalars().all())
        profile_ids = list((await db.execute(
            select(MetacognitiveProfile.id).where(or_(
                MetacognitiveProfile.run_id == run_id,
                MetacognitiveProfile.session_id.in_(session_ids),
            ))
        )).scalars().all())
        if coding_ids:
            await db.execute(delete(CodingAnnotation).where(CodingAnnotation.coding_id.in_(coding_ids)))
            await db.execute(delete(CodingAdjudication).where(CodingAdjudication.coding_id.in_(coding_ids)))
        if unit_ids:
            await db.execute(delete(CodingUnitAnnotation).where(CodingUnitAnnotation.unit_id.in_(unit_ids)))
            await db.execute(delete(CodingUnitAdjudication).where(CodingUnitAdjudication.unit_id.in_(unit_ids)))
            await db.execute(delete(CodingUnit).where(CodingUnit.id.in_(unit_ids)))
        if profile_ids:
            await db.execute(delete(LearningSuggestion).where(LearningSuggestion.profile_id.in_(profile_ids)))
        await db.execute(delete(ConsistencyReport).where(ConsistencyReport.session_id.in_(session_ids)))
        await db.execute(delete(MetacognitiveProfile).where(MetacognitiveProfile.id.in_(profile_ids)))
        await db.execute(delete(CodedSegment).where(CodedSegment.session_id.in_(session_ids)))
        await db.execute(delete(DialogueTurn).where(DialogueTurn.session_id.in_(session_ids)))
        await db.execute(delete(InteractionEvent).where(InteractionEvent.session_id.in_(session_ids)))
        await db.execute(delete(ExtractionCandidateRevision).where(ExtractionCandidateRevision.session_id.in_(session_ids)))
        await db.execute(delete(ExtractionCandidate).where(ExtractionCandidate.session_id.in_(session_ids)))
        await db.execute(update(ExtractionJob).where(
            ExtractionJob.session_id.in_(session_ids)
        ).values(supersedes_job_id=None))
        await db.execute(delete(ExtractionJob).where(ExtractionJob.session_id.in_(session_ids)))
        await db.execute(delete(TranscriptSegment).where(TranscriptSegment.session_id.in_(session_ids)))
        await db.execute(delete(TranscriptVersion).where(TranscriptVersion.session_id.in_(session_ids)))
        await db.execute(delete(AsrJob).where(AsrJob.session_id.in_(session_ids)))
        await db.execute(delete(AudioChunk).where(AudioChunk.session_id.in_(session_ids)))
        await db.execute(delete(AssessmentSession).where(AssessmentSession.id.in_(session_ids)))

    await db.execute(delete(RunQualityReview).where(RunQualityReview.run_id == run_id))
    await db.execute(delete(QuestionnaireResponse).where(QuestionnaireResponse.run_id == run_id))
    await db.execute(delete(AssessmentRun).where(AssessmentRun.id == run_id))
    db.add(AuditLog(
        actor_id=current_user.id,
        action="delete_complete_run",
        target_type="assessment_run",
        target_id=run_id,
        detail={
            "user_id": run.user_id,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "audio_file_count": len(storage_paths),
            "deletion_impact": impact,
        },
    ))
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="该测评仍被其他研究记录引用，暂不能整批删除；请先删除相关编码或报告",
        ) from error
    deleted_files, failed_files = _remove_audio_files(storage_paths)
    return {
        "status": "success",
        "message": "整次测评记录已删除",
        "deleted_files": deleted_files,
        "failed_files": failed_files,
    }


@router.get("/users/{user_id}/sessions")
async def get_user_sessions(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """获取指定用户的所有会话，按任务分组"""
    from app.models.task import AssessmentTask

    sessions_result = await db.execute(
        select(AssessmentSession).where(AssessmentSession.user_id == user_id)
    )
    sessions = sessions_result.scalars().all()

    # 按 task_id 分组，统计每个任务的对话数
    task_map: dict[str, dict] = {}
    for s in sessions:
        tid = s.task_id
        if tid not in task_map:
            task = await db.get(AssessmentTask, tid)
            task_map[tid] = {
                "task_id": tid,
                "task_title": task.title if task else "未知任务",
                "session_ids": [],
                "dialogue_count": 0,
            }
        task_map[tid]["session_ids"].append(s.id)

    # 统计对话数
    for info in task_map.values():
        count_result = await db.execute(
            select(DialogueTurn).where(DialogueTurn.session_id.in_(info["session_ids"]))
        )
        info["dialogue_count"] = len(list(count_result.scalars().all()))

    return list(task_map.values())


@router.get("/users/{user_id}/dialogue")
async def get_user_dialogue(
    user_id: str,
    task_id: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """获取指定用户+任务的对话记录"""
    query = select(AssessmentSession.id).where(AssessmentSession.user_id == user_id)
    if task_id:
        query = query.where(AssessmentSession.task_id == task_id)
    sessions_result = await db.execute(query)
    session_ids = [row[0] for row in sessions_result]

    if not session_ids:
        return []

    turns_result = await db.execute(
        select(DialogueTurn)
        .where(DialogueTurn.session_id.in_(session_ids))
        .order_by(DialogueTurn.timestamp.asc())
    )
    return [
        {
            "id": t.id,
            "role": t.role,
            "content": t.content,
            "timestamp": t.timestamp,
        }
        for t in turns_result.scalars().all()
    ]


@router.delete("/users/{user_id}/history")
async def clear_user_history(
    user_id: str,
    task_id: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """按任务清空用户的对话历史；不传 task_id 则清空全部"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 查找会话
    query = select(AssessmentSession.id).where(AssessmentSession.user_id == user_id)
    if task_id:
        query = query.where(AssessmentSession.task_id == task_id)
    sessions_result = await db.execute(query)
    session_ids = [row[0] for row in sessions_result]

    if not session_ids:
        return {"status": "success", "message": "该任务下无对话历史", "deleted_turns": 0}

    # 删除编码片段
    seg_result = await db.execute(
        select(CodedSegment).where(CodedSegment.session_id.in_(session_ids))
    )
    for seg in seg_result.scalars().all():
        await db.delete(seg)

    # 删除对话记录
    turn_result = await db.execute(
        select(DialogueTurn).where(DialogueTurn.session_id.in_(session_ids))
    )
    deleted = 0
    for turn in turn_result.scalars().all():
        await db.delete(turn)
        deleted += 1

    await db.commit()
    return {"status": "success", "message": "对话历史已清空", "deleted_turns": deleted}


@router.get("/protocol-config", response_model=ProtocolConfigOut)
async def get_protocol_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """读取新测评使用的协议开关与多模态评分权重；进行中的测评继续使用自己的快照。"""
    del current_user
    config = await load_protocol_config(db)
    return ProtocolConfigOut(
        questionnaire_enabled=config.questionnaire_enabled,
        behavior_weight=config.behavior_weight,
        questionnaire_weight=config.questionnaire_weight,
        updated_at=config.updated_at,
    )


@router.put("/protocol-config", response_model=ProtocolConfigOut)
async def update_protocol_config(
    data: ProtocolConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """保存协议开关与多模态加权权重，只影响保存后创建的新测评与报告。"""
    del current_user
    config = await save_protocol_config(
        db,
        questionnaire_enabled=data.questionnaire_enabled,
        behavior_weight=data.behavior_weight,
        questionnaire_weight=data.questionnaire_weight,
    )
    return ProtocolConfigOut(
        questionnaire_enabled=config.questionnaire_enabled,
        behavior_weight=config.behavior_weight,
        questionnaire_weight=config.questionnaire_weight,
        updated_at=config.updated_at,
    )

@router.get(
    "/model-services/config",
    response_model=ModelServicesConfigOut,
)
async def get_model_services_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """读取脱敏后的运行时模型配置；密钥只返回是否已配置。"""
    del current_user
    await load_runtime_model_settings(db, settings)
    return model_services_config_view(settings)


@router.put(
    "/model-services/config",
    response_model=ModelServicesConfigOut,
)
async def update_model_services_config(
    data: ModelServicesConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """加密保存模型服务配置并立即应用到当前服务进程。"""
    return await save_runtime_model_settings(data, db, settings, current_user.id)


@router.get(
    "/model-services/config/history",
    response_model=list[ModelConfigHistoryOut],
)
async def get_model_services_config_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    del current_user
    return await list_runtime_model_history(db)


@router.post(
    "/model-services/config/history/{history_id}/rollback",
    response_model=ModelServicesConfigOut,
)
async def rollback_model_services_config(
    history_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    try:
        return await rollback_runtime_model_settings(
            history_id, db, settings, current_user.id
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/model-services/diagnostics",
    response_model=ModelServicesDiagnosticsOut,
)
async def diagnose_model_services(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """运行一次极小的真实调用，检查 LLM、ASR 与音频公网链路。"""
    del current_user
    await load_runtime_model_settings(db, settings)
    checked_at = datetime.now(timezone.utc)
    llm, embedding, asr, audio = await ModelDiagnosticsService(settings).run()

    month_start = checked_at.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).replace(tzinfo=None)
    used_ms = await db.scalar(
        select(func.coalesce(func.sum(AsrJob.audio_duration_ms), 0)).where(
            AsrJob.provider == "volcengine",
            AsrJob.status == "completed",
            AsrJob.created_at >= month_start,
        )
    )
    local_asr_hours = round(float(used_ms or 0) / 3_600_000, 3)

    core_statuses = {llm.status, embedding.status, asr.status, audio.status}
    if core_statuses == {"ready"}:
        overall_status = "ready"
    elif "ready" in core_statuses or "warning" in core_statuses:
        overall_status = "degraded"
    else:
        overall_status = "unavailable"

    return ModelServicesDiagnosticsOut(
        overall_status=overall_status,
        checked_at=checked_at,
        llm=llm,
        embedding=embedding,
        asr=asr,
        audio_public_url=audio,
        llm_quota=QuotaDiagnosticOut(
            status="console_required",
            unit="Token",
            console_url=(
                "https://console.volcengine.com/ark/"
                "region:ark+cn-beijing/usage"
            ),
            message=(
                "方舟服务 API Key 不提供账户精确余量；"
                "请在方舟用量统计页查看 Token 用量与免费额度。"
            ),
        ),
        asr_quota=QuotaDiagnosticOut(
            status="console_required",
            unit="小时",
            local_usage=local_asr_hours,
            period=checked_at.strftime("%Y-%m"),
            console_url="https://console.volcengine.com/speech/app",
            message=(
                "本页仅统计本系统本月已完成的火山 ASR 音频时长；"
                "精确资源包余量与其他应用用量请以豆包语音控制台为准。"
            ),
        ),
    )
