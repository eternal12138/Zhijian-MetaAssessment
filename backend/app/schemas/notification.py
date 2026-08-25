from datetime import datetime

from app.schemas.base import ApiModel as BaseModel


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    content: str
    target_url: str
    priority: str
    is_read: bool
    metadata: dict | None = None
    created_at: datetime
    read_at: datetime | None = None


class UnreadCountOut(BaseModel):
    count: int


class MarkAllReadOut(BaseModel):
    updated: int
