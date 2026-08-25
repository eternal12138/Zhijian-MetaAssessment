"""Database-backed controls for the standardized assessment protocol."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_config import SystemConfig


CONFIG_KEY = "assessment_protocol_config"
DEFAULT_QUESTIONNAIRE_ENABLED = False


@dataclass(frozen=True)
class ProtocolRuntimeConfig:
    questionnaire_enabled: bool
    updated_at: datetime | None = None


def _decode(value: str) -> bool:
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return DEFAULT_QUESTIONNAIRE_ENABLED
    if not isinstance(payload, dict):
        return DEFAULT_QUESTIONNAIRE_ENABLED
    return payload.get("questionnaire_enabled") is True


async def load_protocol_config(db: AsyncSession) -> ProtocolRuntimeConfig:
    row = await db.get(SystemConfig, CONFIG_KEY)
    if row is None:
        return ProtocolRuntimeConfig(DEFAULT_QUESTIONNAIRE_ENABLED)
    return ProtocolRuntimeConfig(
        questionnaire_enabled=_decode(row.config_value),
        updated_at=row.updated_at,
    )


async def save_protocol_config(
    db: AsyncSession,
    *,
    questionnaire_enabled: bool,
) -> ProtocolRuntimeConfig:
    serialized = json.dumps(
        {"questionnaire_enabled": questionnaire_enabled},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    row = await db.get(SystemConfig, CONFIG_KEY)
    if row is None:
        row = SystemConfig(config_key=CONFIG_KEY, config_value=serialized)
        db.add(row)
    else:
        row.config_value = serialized
    await db.flush()
    await db.refresh(row)
    return ProtocolRuntimeConfig(
        questionnaire_enabled=questionnaire_enabled,
        updated_at=row.updated_at,
    )
