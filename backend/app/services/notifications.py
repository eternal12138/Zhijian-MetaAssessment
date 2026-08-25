"""Notification creation helpers used by domain events."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.user import User


async def create_notification(
    db: AsyncSession,
    *,
    user_id: str,
    type: str,
    title: str,
    content: str,
    target_url: str,
    event_key: str | None = None,
    priority: str = "normal",
    metadata: dict | None = None,
) -> Notification | None:
    if not target_url.startswith("/") or target_url.startswith("//"):
        raise ValueError("notification target must be an internal path")
    if event_key:
        result = await db.execute(
            select(Notification.id).where(Notification.event_key == event_key)
        )
        if result.scalar_one_or_none():
            return None
    notification = Notification(
        user_id=user_id,
        event_key=event_key,
        type=type,
        title=title[:128],
        content=content[:1000],
        target_url=target_url[:512],
        priority=priority,
        extra_data=metadata,
    )
    db.add(notification)
    await db.flush()
    return notification


async def notify_reviewers(
    db: AsyncSession,
    *,
    student: User,
    event_key_prefix: str,
    title: str,
    content: str,
    metadata: dict | None = None,
) -> int:
    result = await db.execute(
        select(User).where(
            User.is_active.is_(True),
            User.role.in_(("teacher", "admin")),
        )
    )
    count = 0
    for reviewer in result.scalars().all():
        if reviewer.role == "teacher":
            managed = {
                item.strip()
                for item in (reviewer.managed_classes or "").split(",")
                if item.strip()
            }
            if not student.class_group or student.class_group not in managed:
                continue
        created = await create_notification(
            db,
            user_id=reviewer.id,
            type="review",
            title=title,
            content=content,
            target_url="/review",
            event_key=f"{event_key_prefix}:{reviewer.id}",
            priority="important",
            metadata=metadata,
        )
        count += int(created is not None)
    return count
