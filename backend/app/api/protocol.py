"""标准化双任务出声思维测评流程。"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import can_access_user, get_current_user, require_role
from app.core.time import utc_now_naive
from app.database import get_db
from app.models.protocol import AssessmentRun, QuestionnaireResponse, TaskOrderAssignment
from app.models.scale import ScaleItem
from app.models.session import AssessmentSession
from app.models.task import AssessmentTask
from app.models.user import User
from app.schemas.protocol import (
    AssessmentProtocolOut,
    AssessmentRunOut,
    ProtocolNarrationAssetOut,
    ProtocolQuestionnaireItemOut,
    ProtocolTaskOut,
    QuestionnaireAnswerOut,
    QuestionnaireSubmitIn,
    RunCreateIn,
    RunSessionOut,
    RunStageIn,
    TaskOrderAssignmentIn,
    TaskOrderBalanceIn,
    TaskOrderOverviewOut,
    TaskOrderStudentOut,
)
from app.services.notifications import create_notification
from app.services.narration_catalog import assets_for_snapshot, narration_snapshot
from app.services.protocol_config import load_protocol_config
from app.services.questionnaire import CURRENT_QUESTIONNAIRE_SOURCE

router = APIRouter(prefix="/assessment", tags=["标准测评流程"])

PROTOCOL_VERSION = "2026.2"
NEXT_STAGE = {
    "device_check": "instructions",
    "instructions": "practice",
    "practice": "task_1",
    "task_1": "task_2",
    "task_2": "questionnaire",
}
LIKERT_LABELS = {
    1: "强烈不同意",
    2: "不同意",
    3: "比较不同意",
    4: "不确定",
    5: "比较同意",
    6: "同意",
    7: "强烈同意",
}


async def _protocol_tasks(db: AsyncSession) -> list[AssessmentTask]:
    """读取标准协议的 A、B 两个任务；protocol_order 仅定义任务身份，不再固定被试顺序。"""
    result = await db.execute(
        select(AssessmentTask)
        .where(
            AssessmentTask.status == "published",
            AssessmentTask.protocol_order > 0,
            AssessmentTask.protocol_order <= 2,
        )
        .order_by(AssessmentTask.protocol_order.asc())
    )
    return list(result.scalars().all())


def _order_code(ordered_task_ids: list[str], base_task_ids: list[str]) -> str:
    if ordered_task_ids == base_task_ids:
        return "AB"
    if ordered_task_ids == list(reversed(base_task_ids)):
        return "BA"
    return "CUSTOM"


def _ordered_tasks(
    tasks: list[AssessmentTask],
    ordered_task_ids: list[str],
) -> list[AssessmentTask] | None:
    task_map = {task.id: task for task in tasks}
    if len(ordered_task_ids) != len(tasks) or set(ordered_task_ids) != set(task_map):
        return None
    return [task_map[task_id] for task_id in ordered_task_ids]


async def _tasks_for_user(
    user: User,
    db: AsyncSession,
) -> tuple[list[AssessmentTask], str, str, str | None]:
    """返回顺序快照：进行中测评 > 人工分配 > 默认 AB。"""
    tasks = await _protocol_tasks(db)
    if len(tasks) != 2:
        raise HTTPException(status_code=503, detail="标准测评必须配置 protocol_order 为 1、2 的两个已发布任务")
    base_ids = [task.id for task in tasks]

    run_result = await db.execute(
        select(AssessmentRun)
        .where(
            AssessmentRun.user_id == user.id,
            AssessmentRun.status == "in_progress",
        )
        .order_by(AssessmentRun.started_at.desc())
        .options(selectinload(AssessmentRun.sessions))
    )
    current_run = run_result.scalars().first()
    if current_run is not None:
        run_ids = [
            session.task_id
            for session in sorted(current_run.sessions, key=lambda item: item.sequence_no)
        ][:2]
        ordered = _ordered_tasks(tasks, run_ids)
        if ordered is not None:
            return ordered, current_run.task_order_code, "active_run", current_run.order_assignment_id

    assignment = await db.scalar(
        select(TaskOrderAssignment).where(TaskOrderAssignment.user_id == user.id)
    )
    if assignment is not None:
        ordered = _ordered_tasks(tasks, list(assignment.ordered_task_ids))
        if ordered is not None:
            return ordered, assignment.order_code, "assignment", assignment.id

    return tasks, "AB", "default", None


async def _questionnaire_items(
    db: AsyncSession,
    source: str = CURRENT_QUESTIONNAIRE_SOURCE,
) -> list[ScaleItem]:
    result = await db.execute(
        select(ScaleItem)
        .where(ScaleItem.source == source)
        .order_by(
            ScaleItem.display_order.asc(),
            ScaleItem.id.asc(),
        )
    )
    return list(result.scalars().all())


def _next_stage(run: AssessmentRun) -> str | None:
    if run.current_stage == "task_2" and not run.questionnaire_enabled:
        return "review"
    return NEXT_STAGE.get(run.current_stage)


async def _get_run(
    run_id: str,
    user: User,
    db: AsyncSession,
) -> AssessmentRun:
    result = await db.execute(
        select(AssessmentRun)
        .where(AssessmentRun.id == run_id)
        .options(
            selectinload(AssessmentRun.sessions),
            selectinload(AssessmentRun.questionnaire_responses),
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="完整测评不存在")
    if run.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权访问该完整测评")
    return run


def _run_out(run: AssessmentRun) -> AssessmentRunOut:
    return AssessmentRunOut(
        id=run.id,
        user_id=run.user_id,
        status=run.status,
        current_stage=run.current_stage,
        protocol_version=run.protocol_version,
        questionnaire_enabled=run.questionnaire_enabled,
        questionnaire_source=run.questionnaire_source,
        task_order_code=run.task_order_code,
        order_assignment_id=run.order_assignment_id,
        consented_at=run.consented_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        sessions=[
            RunSessionOut(
                id=session.id,
                task_id=session.task_id,
                sequence_no=session.sequence_no,
                status=session.status,
            )
            for session in sorted(run.sessions, key=lambda item: item.sequence_no)
        ],
        questionnaire_answers=[
            QuestionnaireAnswerOut(item_id=item.item_id, value=item.value)
            for item in run.questionnaire_responses
        ],
        questionnaire_participant_name=run.questionnaire_participant_name,
    )


@router.get("/protocol", response_model=AssessmentProtocolOut)
async def get_protocol(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回当前学生应执行的任务顺序；进行中测评始终使用创建时的顺序快照。"""
    tasks, order_code, order_source, _ = await _tasks_for_user(user, db)
    active_result = await db.execute(
        select(
            AssessmentRun.questionnaire_enabled,
            AssessmentRun.questionnaire_source,
            AssessmentRun.narration_snapshot,
        )
        .where(
            AssessmentRun.user_id == user.id,
            AssessmentRun.status == "in_progress",
        )
        .order_by(AssessmentRun.started_at.desc())
    )
    active_run = active_result.first()
    questionnaire_enabled = (
        active_run.questionnaire_enabled
        if active_run is not None
        else (await load_protocol_config(db)).questionnaire_enabled
    )
    questionnaire_source = (
        active_run.questionnaire_source
        if active_run is not None
        else CURRENT_QUESTIONNAIRE_SOURCE
    )
    items = (
        await _questionnaire_items(db, questionnaire_source)
        if questionnaire_enabled else []
    )
    if questionnaire_enabled and not items:
        raise HTTPException(status_code=503, detail="任务型元认知问卷尚未配置")

    narration_assets = await assets_for_snapshot(
        db,
        active_run.narration_snapshot if active_run is not None else None,
    )

    return AssessmentProtocolOut(
        version=PROTOCOL_VERSION,
        questionnaire_enabled=questionnaire_enabled,
        questionnaire_source=questionnaire_source,
        task_order_code=order_code,
        order_source=order_source,
        tasks=[
            ProtocolTaskOut(
                id=task.id,
                title=task.title,
                description=task.description,
                scenario=task.scenario,
                estimated_minutes=task.estimated_minutes,
                protocol_order=task.protocol_order,
                stimulus_data=task.stimulus_data,
            )
            for task in tasks
        ],
        questionnaire_items=[
            ProtocolQuestionnaireItemOut(
                id=item.id,
                dimension=item.dimension,
                text=item.self_report_text,
                scale_min=item.scale_min,
                scale_max=item.scale_max,
                display_order=item.display_order,
            )
            for item in items
        ],
        likert_labels=LIKERT_LABELS,
        narration_assets=[
            ProtocolNarrationAssetOut(
                id=asset.id,
                slot_key=asset.slot_key,
                version=asset.version,
                original_filename=asset.original_filename,
                mime_type=asset.mime_type,
                size_bytes=asset.size_bytes,
                created_at=asset.created_at,
            )
            for asset in narration_assets
        ],
    )


@router.post("/runs", response_model=AssessmentRunOut, status_code=status.HTTP_201_CREATED)
async def create_run(
    data: RunCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """记录知情同意并创建包含两个任务会话的完整测评。"""
    if not data.consent:
        raise HTTPException(status_code=422, detail="必须同意知情说明后才能开始测评")
    existing_result = await db.execute(
        select(AssessmentRun)
        .where(
            AssessmentRun.user_id == user.id,
            AssessmentRun.status == "in_progress",
        )
        .order_by(AssessmentRun.started_at.desc())
        .options(
            selectinload(AssessmentRun.sessions),
            selectinload(AssessmentRun.questionnaire_responses),
        )
    )
    existing = existing_result.scalars().first()
    if existing is not None:
        return _run_out(existing)

    tasks, order_code, _, assignment_id = await _tasks_for_user(user, db)
    questionnaire_enabled = (await load_protocol_config(db)).questionnaire_enabled
    if questionnaire_enabled and not await _questionnaire_items(
        db, CURRENT_QUESTIONNAIRE_SOURCE
    ):
        raise HTTPException(status_code=503, detail="已启用问卷，但任务型元认知问卷尚未配置")

    run = AssessmentRun(
        user_id=user.id,
        status="in_progress",
        current_stage="device_check",
        protocol_version=PROTOCOL_VERSION,
        questionnaire_enabled=questionnaire_enabled,
        questionnaire_source=CURRENT_QUESTIONNAIRE_SOURCE,
        task_order_code=order_code,
        order_assignment_id=assignment_id,
        narration_snapshot=await narration_snapshot(db),
    )
    db.add(run)
    await db.flush()

    for index, task in enumerate(tasks, start=1):
        db.add(
            AssessmentSession(
                run_id=run.id,
                sequence_no=index,
                user_id=user.id,
                task_id=task.id,
                status="preparation",
                model_id="standardized-think-aloud",
                model_params={
                    "protocol_version": PROTOCOL_VERSION,
                    "neutral_prompt_only": True,
                    "silence_threshold_seconds": 15,
                },
            )
        )
    await db.flush()
    return _run_out(await _get_run(run.id, user, db))


def _protocol_task_out(task: AssessmentTask) -> ProtocolTaskOut:
    return ProtocolTaskOut(
        id=task.id,
        title=task.title,
        description=task.description,
        scenario=task.scenario,
        estimated_minutes=task.estimated_minutes,
        protocol_order=task.protocol_order,
        stimulus_data=task.stimulus_data,
    )


async def _assign_order(
    target: User,
    ordered_task_ids: list[str],
    actor: User,
    tasks: list[AssessmentTask],
    db: AsyncSession,
) -> TaskOrderAssignment:
    base_ids = [task.id for task in tasks]
    if len(set(ordered_task_ids)) != 2 or set(ordered_task_ids) != set(base_ids):
        raise HTTPException(status_code=422, detail="任务顺序必须且只能包含当前标准协议的 A、B 两项任务")
    assignment = await db.scalar(
        select(TaskOrderAssignment).where(TaskOrderAssignment.user_id == target.id)
    )
    if assignment is None:
        assignment = TaskOrderAssignment(
            user_id=target.id,
            ordered_task_ids=ordered_task_ids,
            order_code=_order_code(ordered_task_ids, base_ids),
            assigned_by=actor.id,
            assigned_at=utc_now_naive(),
        )
        db.add(assignment)
    else:
        assignment.ordered_task_ids = ordered_task_ids
        assignment.order_code = _order_code(ordered_task_ids, base_ids)
        assignment.assigned_by = actor.id
        assignment.assigned_at = utc_now_naive()
    return assignment


@router.get("/task-order/assignments", response_model=TaskOrderOverviewOut)
async def list_task_order_assignments(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=100),
    search: str = Query(default="", max_length=100),
    current_user: User = Depends(require_role("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """列出当前教师可管理学生的 AB/BA 分配；管理员可查看全部学生。"""
    tasks = await _protocol_tasks(db)
    if len(tasks) != 2:
        raise HTTPException(status_code=503, detail="标准测评必须配置两个已发布任务")
    base_ids = [task.id for task in tasks]
    statement = select(User).where(User.role == "student", User.is_active.is_(True))
    if current_user.role != "admin":
        managed_classes = [value.strip() for value in (current_user.managed_classes or "").split(",") if value.strip()]
        statement = statement.where(User.class_group.in_(managed_classes))
    keyword = search.strip()
    if keyword:
        statement = statement.where(or_(
            User.name.ilike(f"%{keyword}%"),
            User.username.ilike(f"%{keyword}%"),
            User.class_group.ilike(f"%{keyword}%"),
        ))
    total = int(await db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    users_result = await db.execute(
        statement.order_by(User.class_group.asc(), User.username.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    students = list(users_result.scalars().all())
    user_ids = [item.id for item in students]
    assignments: dict[str, TaskOrderAssignment] = {}
    in_progress_ids: set[str] = set()
    if user_ids:
        assignment_result = await db.execute(
            select(TaskOrderAssignment).where(TaskOrderAssignment.user_id.in_(user_ids))
        )
        assignments = {
            item.user_id: item for item in assignment_result.scalars().all()
        }
        run_result = await db.execute(
            select(AssessmentRun.user_id).where(
                AssessmentRun.user_id.in_(user_ids),
                AssessmentRun.status == "in_progress",
            )
        )
        in_progress_ids = {row[0] for row in run_result.all()}

    return TaskOrderOverviewOut(
        tasks=[_protocol_task_out(task) for task in tasks],
        total=total,
        page=page,
        page_size=page_size,
        students=[
            TaskOrderStudentOut(
                user_id=student.id,
                username=student.username,
                name=student.name,
                class_group=student.class_group,
                ordered_task_ids=list(assignments[student.id].ordered_task_ids)
                if student.id in assignments else base_ids,
                order_code=assignments[student.id].order_code
                if student.id in assignments else "AB",
                assigned_by=assignments[student.id].assigned_by
                if student.id in assignments else None,
                assigned_at=assignments[student.id].assigned_at
                if student.id in assignments else None,
                has_in_progress_run=student.id in in_progress_ids,
            )
            for student in students
        ],
    )


@router.put("/task-order/assignments/{user_id}", response_model=TaskOrderStudentOut)
async def set_task_order_assignment(
    user_id: str,
    data: TaskOrderAssignmentIn,
    current_user: User = Depends(require_role("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if target is None or target.role != "student":
        raise HTTPException(status_code=404, detail="学生不存在")
    if not can_access_user(current_user, target):
        raise HTTPException(status_code=403, detail="无权为该学生分配任务顺序")
    tasks = await _protocol_tasks(db)
    if len(tasks) != 2:
        raise HTTPException(status_code=503, detail="标准测评必须配置两个已发布任务")
    assignment = await _assign_order(
        target, data.ordered_task_ids, current_user, tasks, db
    )
    await db.flush()
    has_run = bool(await db.scalar(
        select(func.count(AssessmentRun.id)).where(
            AssessmentRun.user_id == target.id,
            AssessmentRun.status == "in_progress",
        )
    ))
    return TaskOrderStudentOut(
        user_id=target.id,
        username=target.username,
        name=target.name,
        class_group=target.class_group,
        ordered_task_ids=list(assignment.ordered_task_ids),
        order_code=assignment.order_code,
        assigned_by=assignment.assigned_by,
        assigned_at=assignment.assigned_at,
        has_in_progress_run=has_run,
    )


@router.post("/task-order/assignments/balance", response_model=TaskOrderOverviewOut)
async def balance_task_order_assignments(
    data: TaskOrderBalanceIn,
    current_user: User = Depends(require_role("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """按当前全局 AB/BA 数量，从较少的一组开始交替分配所选学生。"""
    tasks = await _protocol_tasks(db)
    if len(tasks) != 2:
        raise HTTPException(status_code=503, detail="标准测评必须配置两个已发布任务")
    unique_ids = list(dict.fromkeys(data.user_ids))
    result = await db.execute(
        select(User).where(User.id.in_(unique_ids), User.role == "student")
        .order_by(User.class_group.asc(), User.username.asc())
    )
    targets = list(result.scalars().all())
    if len(targets) != len(unique_ids):
        raise HTTPException(status_code=422, detail="所选用户中包含不存在或非学生账号")
    if any(not can_access_user(current_user, target) for target in targets):
        raise HTTPException(status_code=403, detail="所选学生超出当前教师管理范围")

    counts_result = await db.execute(
        select(TaskOrderAssignment.order_code, func.count(TaskOrderAssignment.id))
        .where(TaskOrderAssignment.order_code.in_(("AB", "BA")))
        .group_by(TaskOrderAssignment.order_code)
    )
    counts = {"AB": 0, "BA": 0}
    counts.update({code: count for code, count in counts_result.all()})
    next_code = "AB" if counts["AB"] <= counts["BA"] else "BA"
    base_ids = [task.id for task in tasks]
    for target in targets:
        ordered_ids = base_ids if next_code == "AB" else list(reversed(base_ids))
        await _assign_order(target, ordered_ids, current_user, tasks, db)
        next_code = "BA" if next_code == "AB" else "AB"
    await db.flush()
    return await list_task_order_assignments(
        page=1,
        page_size=50,
        search="",
        current_user=current_user,
        db=db,
    )


@router.get("/runs/current", response_model=AssessmentRunOut | None)
async def get_current_run(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回当前用户最近一条未完成测评，供刷新页面后安全恢复。"""
    result = await db.execute(
        select(AssessmentRun)
        .where(
            AssessmentRun.user_id == user.id,
            AssessmentRun.status == "in_progress",
        )
        .order_by(AssessmentRun.started_at.desc())
        .options(
            selectinload(AssessmentRun.sessions),
            selectinload(AssessmentRun.questionnaire_responses),
        )
    )
    run = result.scalars().first()
    return _run_out(run) if run is not None else None


@router.get("/runs/{run_id}", response_model=AssessmentRunOut)
async def get_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return _run_out(await _get_run(run_id, user, db))


@router.patch("/runs/{run_id}/stage", response_model=AssessmentRunOut)
async def advance_stage(
    run_id: str,
    data: RunStageIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按固定顺序推进流程，禁止跳过任务或问卷。"""
    run = await _get_run(run_id, user, db)
    if run.status != "in_progress":
        raise HTTPException(status_code=409, detail="完整测评已经结束")
    if data.stage == run.current_stage:
        return _run_out(run)

    expected = _next_stage(run)
    if data.stage != expected:
        raise HTTPException(
            status_code=409,
            detail=f"流程顺序错误：当前为 {run.current_stage}，下一阶段应为 {expected}",
        )

    sessions = sorted(run.sessions, key=lambda item: item.sequence_no)
    if data.stage == "task_2" and sessions[0].status != "completed":
        raise HTTPException(status_code=409, detail="必须先完成第一项任务")
    if data.stage == "questionnaire" and any(
        session.status != "completed" for session in sessions[:2]
    ):
        raise HTTPException(status_code=409, detail="必须先完成两项问题解决任务")
    if data.stage == "review" and (
        run.questionnaire_enabled
        or any(session.status != "completed" for session in sessions[:2])
    ):
        raise HTTPException(status_code=409, detail="当前测评必须先完成问卷")

    run.current_stage = data.stage
    await db.flush()
    return _run_out(run)


@router.post("/runs/{run_id}/questionnaire", response_model=AssessmentRunOut)
async def submit_questionnaire(
    run_id: str,
    data: QuestionnaireSubmitIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """完整、幂等地保存任务型元认知问卷。"""
    run = await _get_run(run_id, user, db)
    if not run.questionnaire_enabled:
        raise HTTPException(status_code=409, detail="本次测评未启用问卷")
    if run.current_stage != "questionnaire" or run.status != "in_progress":
        raise HTTPException(status_code=409, detail="当前不在问卷阶段")

    items = await _questionnaire_items(db, run.questionnaire_source)
    expected = {item.id: item for item in items}
    submitted = {answer.item_id: answer.value for answer in data.answers}
    if set(submitted) != set(expected):
        missing = len(set(expected) - set(submitted))
        extra = len(set(submitted) - set(expected))
        raise HTTPException(
            status_code=422,
            detail=f"问卷必须完整作答：缺少 {missing} 项，多出 {extra} 项",
        )
    for item_id, value in submitted.items():
        item = expected[item_id]
        if value < item.scale_min or value > item.scale_max:
            raise HTTPException(status_code=422, detail=f"题目 {item_id} 的作答超出范围")

    existing = {item.item_id: item for item in run.questionnaire_responses}
    for item_id, value in submitted.items():
        response = existing.get(item_id)
        if response is None:
            response = QuestionnaireResponse(
                run_id=run.id,
                user_id=user.id,
                item_id=item_id,
            )
            run.questionnaire_responses.append(response)
        response.value = value

    run.questionnaire_participant_name = data.participant_name

    run.current_stage = "review"
    await db.flush()
    return _run_out(await _get_run(run.id, user, db))


@router.post("/runs/{run_id}/complete", response_model=AssessmentRunOut)
async def complete_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """核验两项任务及本次协议要求的可选问卷后完成标准测评。"""
    run = await _get_run(run_id, user, db)
    if run.status == "completed":
        return _run_out(run)
    if run.current_stage != "review":
        detail = "请先完成任务和问卷" if run.questionnaire_enabled else "请先完成两项任务"
        raise HTTPException(status_code=409, detail=detail)

    if len(run.sessions) < 2 or any(
        session.status != "completed" for session in run.sessions[:2]
    ):
        raise HTTPException(status_code=409, detail="两项任务尚未全部完成")
    if run.questionnaire_enabled:
        expected_items = await _questionnaire_items(db, run.questionnaire_source)
        if len(run.questionnaire_responses) != len(expected_items):
            raise HTTPException(status_code=409, detail="问卷尚未完整提交")

    run.status = "completed"
    run.current_stage = "completed"
    run.completed_at = utc_now_naive()
    await create_notification(
        db,
        user_id=run.user_id,
        type="assessment",
        title="测评已完成",
        content=(
            "两项任务和任务后问卷已成功提交。数据将进入转录与研究复核，"
            "个人报告正式发布后系统会通知你。"
            if run.questionnaire_enabled
            else "两项出声思维任务已成功提交。数据将进入转录与研究复核，"
            "个人报告正式发布后系统会通知你。"
        ),
        target_url=f"/report?run={run.id}",
        event_key=f"run-completed:{run.id}:{run.user_id}",
        metadata={
            "run_id": run.id,
            "questionnaire_enabled": run.questionnaire_enabled,
        },
    )
    await db.flush()
    return _run_out(run)
