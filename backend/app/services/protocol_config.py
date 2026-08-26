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
    behavior_weight: float = 0.6
    questionnaire_weight: float = 0.4
    updated_at: datetime | None = None


def _decode(value: str) -> tuple[bool, float, float]:
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return DEFAULT_QUESTIONNAIRE_ENABLED, 0.6, 0.4
    if not isinstance(payload, dict):
        return DEFAULT_QUESTIONNAIRE_ENABLED, 0.6, 0.4
    q_enabled = payload.get("questionnaire_enabled") is True
    try:
        b_weight = max(0.0, min(1.0, float(payload.get("behavior_weight", 0.6))))
    except (TypeError, ValueError):
        b_weight = 0.6
    try:
        q_weight = max(0.0, min(1.0, float(payload.get("questionnaire_weight", 0.4))))
    except (TypeError, ValueError):
        q_weight = 0.4
    return q_enabled, b_weight, q_weight


async def load_protocol_config(db: AsyncSession) -> ProtocolRuntimeConfig:
    row = await db.get(SystemConfig, CONFIG_KEY)
    if row is None:
        return ProtocolRuntimeConfig(DEFAULT_QUESTIONNAIRE_ENABLED, 0.6, 0.4)
    q_enabled, b_weight, q_weight = _decode(row.config_value)
    return ProtocolRuntimeConfig(
        questionnaire_enabled=q_enabled,
        behavior_weight=b_weight,
        questionnaire_weight=q_weight,
        updated_at=row.updated_at,
    )


async def save_protocol_config(
    db: AsyncSession,
    *,
    questionnaire_enabled: bool,
    behavior_weight: float = 0.6,
    questionnaire_weight: float = 0.4,
) -> ProtocolRuntimeConfig:
    serialized = json.dumps(
        {
            "questionnaire_enabled": questionnaire_enabled,
            "behavior_weight": round(behavior_weight, 3),
            "questionnaire_weight": round(questionnaire_weight, 3),
        },
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
        behavior_weight=behavior_weight,
        questionnaire_weight=questionnaire_weight,
        updated_at=row.updated_at,
    )
