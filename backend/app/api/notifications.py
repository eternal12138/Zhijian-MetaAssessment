"""Authenticated in-app notification endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.time import utc_now_naive
from app.database import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import MarkAllReadOut, NotificationOut, UnreadCountOut

router = APIRouter(prefix="/notifications", tags=["消息通知"])


def _out(item: Notification) -> NotificationOut:
    return NotificationOut(
        id=item.id,
        type=item.type,
        title=item.title,
        content=item.content,
        target_url=item.target_url,
        priority=item.priority,
        is_read=item.is_read,
        metadata=item.extra_data,
        created_at=item.created_at,
        read_at=item.read_at,
    )


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    statement = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        statement = statement.where(Notification.is_read.is_(False))
    result = await db.execute(
        statement.order_by(Notification.created_at.desc()).limit(limit)
    )
    return [_out(item) for item in result.scalars().all()]


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
    )
    return UnreadCountOut(count=int(count or 0))


@router.post("/read-all", response_model=MarkAllReadOut)
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
        .values(
            is_read=True,
            read_at=utc_now_naive(),
        )
    )
    return MarkAllReadOut(updated=int(result.rowcount or 0))


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    if not item.is_read:
        item.is_read = True
        item.read_at = utc_now_naive()
        await db.flush()
    return _out(item)
