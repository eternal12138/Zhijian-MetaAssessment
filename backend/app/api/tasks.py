"""任务路由 —— 教师发布 / 学生查看"""
import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User
from app.models.task import AssessmentTask, QuestionPath
from app.schemas.task import TaskCreate, TaskOut, TaskPublish
from app.core.security import get_current_user, require_role

router = APIRouter(prefix="/tasks", tags=["测评任务"])


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取所有已发布的任务（学生端）"""
    result = await db.execute(
        select(AssessmentTask)
        .where(AssessmentTask.status == "published")
        .options(selectinload(AssessmentTask.question_paths))
        .order_by(AssessmentTask.published_at.desc())
    )
    tasks = result.scalars().all()
    return [_task_to_out(t) for t in tasks]


@router.get("/all", response_model=list[TaskOut])
async def list_all_tasks(
    user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    """获取全部任务（教师端，含草稿）"""
    result = await db.execute(
        select(AssessmentTask)
        .options(selectinload(AssessmentTask.question_paths))
        .order_by(AssessmentTask.created_at.desc())
    )
    return [_task_to_out(t) for t in result.scalars().all()]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取任务详情"""
    result = await db.execute(
        select(AssessmentTask)
        .where(AssessmentTask.id == task_id)
        .options(selectinload(AssessmentTask.question_paths))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "published" and user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="任务尚未发布")
    return _task_to_out(task)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    data: TaskCreate,
    user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    """创建新任务"""
    task = AssessmentTask(
        title=data.title,
        subject=data.subject,
        description=data.description,
        scenario=data.scenario,
        estimated_minutes=data.estimated_minutes,
        requires_voice=data.requires_voice,
        protocol_order=data.protocol_order,
        stimulus_data=data.stimulus_data,
        publisher_id=user.id,
    )
    db.add(task)
    await db.flush()

    for qp in data.question_paths:
        db.add(QuestionPath(
            task_id=task.id,
            dimension=qp.dimension,
            stage=qp.stage,
            prompt_template=qp.prompt_template,
            trigger_keywords=json.dumps(qp.trigger_keywords, ensure_ascii=False),
        ))

    await db.flush()
    result = await db.execute(
        select(AssessmentTask)
        .where(AssessmentTask.id == task.id)
        .options(selectinload(AssessmentTask.question_paths))
    )
    return _task_to_out(result.scalar_one())


@router.post("/{task_id}/publish", response_model=TaskOut)
async def publish_task(
    task_id: str,
    data: TaskPublish,
    user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    """发布任务"""
    result = await db.execute(
        select(AssessmentTask)
        .where(AssessmentTask.id == task_id)
        .options(selectinload(AssessmentTask.question_paths))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if user.role != "admin" and task.publisher_id != user.id:
        raise HTTPException(status_code=403, detail="只能发布自己创建的任务")
    task.status = "published"
    task.deadline = data.deadline
    await db.flush()
    await db.refresh(task)
    return _task_to_out(task)


def _task_to_out(task: AssessmentTask) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        subject=task.subject,
        description=task.description,
        scenario=task.scenario,
        estimated_minutes=task.estimated_minutes,
        requires_voice=task.requires_voice,
        protocol_order=task.protocol_order,
        stimulus_data=task.stimulus_data,
        status=task.status,
        publisher_id=task.publisher_id,
        published_at=task.published_at,
        deadline=task.deadline,
        created_at=task.created_at,
        question_paths=[
            QuestionPath(
                id=qp.id,
                dimension=qp.dimension,
                stage=qp.stage,
                prompt_template=qp.prompt_template,
                trigger_keywords=json.loads(qp.trigger_keywords) if qp.trigger_keywords else [],
            ) for qp in (task.question_paths or [])
        ],
    )
