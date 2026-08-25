"""Encrypted, database-backed runtime configuration for model services."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.system_config import SystemConfig, SystemConfigHistory
from app.models.user import User
from app.schemas.model_services_config import (
    ModelServicesConfigOut,
    ModelServicesConfigUpdate,
)

CONFIG_KEY = "model_services_runtime"
SECRET_FIELDS = {
    "LLM_API_KEY",
    "VOLCENGINE_ASR_API_KEY",
    "VOLCENGINE_ASR_ACCESS_KEY",
    "ASR_AUDIO_SIGNING_SECRET",
    "QWEN_EMBEDDING_API_KEY",
    "EMBEDDING_API_KEY",
}
VALUE_FIELDS = {
    "REPORT_USE_LLM",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_TEMPERATURE",
    "LLM_TOP_P",
    "LLM_MAX_TOKENS",
    "REPORT_LLM_TIMEOUT_SECONDS",
    "ASR_PROVIDER",
    "ASR_MODEL",
    "ASR_LANGUAGE",
    "ASR_MAX_RETRIES",
    "ASR_CONFIG_VERSION",
    "ASR_POLL_INTERVAL_SECONDS",
    "VOLCENGINE_ASR_AUTH_MODE",
    "VOLCENGINE_ASR_APP_ID",
    "VOLCENGINE_ASR_RESOURCE_ID",
    "VOLCENGINE_ASR_SUBMIT_URL",
    "VOLCENGINE_ASR_QUERY_URL",
    "ASR_PUBLIC_BASE_URL",
    "ASR_TIMEOUT_SECONDS",
    "VOLCENGINE_ASR_QUERY_INTERVAL_SECONDS",
    "VOLCENGINE_ASR_MAX_WAIT_SECONDS",
    "ASR_AUDIO_URL_TTL_SECONDS",
    "QWEN_EMBEDDING_BASE_URL",
    "QWEN_EMBEDDING_MODEL",
    "QWEN_EMBEDDING_DIMENSIONS",
    "QWEN_EMBEDDING_BATCH_SIZE",
    "QWEN_EMBEDDING_TIMEOUT_SECONDS",
    "EMBEDDING_API_BASE",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_BATCH_SIZE",
    "EMBEDDING_TIMEOUT",
}


def _fernet(settings: Settings) -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    )
    return Fernet(key)


def _encrypt(value: str, settings: Settings) -> str:
    return _fernet(settings).encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str, settings: Settings) -> str | None:
    try:
        return _fernet(settings).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        return None


def _parse(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"version": 1, "values": {}, "secrets": {}}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"version": 1, "values": {}, "secrets": {}}
    if not isinstance(parsed, dict):
        return {"version": 1, "values": {}, "secrets": {}}
    values = parsed.get("values")
    encrypted = parsed.get("secrets")
    return {
        "version": 1,
        "values": values if isinstance(values, dict) else {},
        "secrets": encrypted if isinstance(encrypted, dict) else {},
    }


def _apply(document: dict[str, Any], settings: Settings) -> None:
    values = document["values"]
    for field in VALUE_FIELDS:
        if field in values:
            setattr(settings, field, values[field])
    encrypted = document["secrets"]
    for field in SECRET_FIELDS:
        token = encrypted.get(field)
        if isinstance(token, str):
            decrypted = _decrypt(token, settings)
            if decrypted is not None:
                setattr(settings, field, decrypted)


async def load_runtime_model_settings(
    db: AsyncSession,
    settings: Settings | None = None,
) -> Settings:
    active = settings or get_settings()
    row = await db.get(SystemConfig, CONFIG_KEY)
    if row is not None:
        _apply(_parse(row.config_value), active)
    return active


def model_services_config_view(
    settings: Settings | None = None,
) -> ModelServicesConfigOut:
    active = settings or get_settings()
    return ModelServicesConfigOut(
        report_use_llm=active.REPORT_USE_LLM,
        llm_base_url=active.LLM_BASE_URL,
        llm_model=active.LLM_MODEL,
        llm_api_key_configured=bool(active.LLM_API_KEY.strip()),
        llm_temperature=active.LLM_TEMPERATURE,
        llm_top_p=active.LLM_TOP_P,
        llm_max_tokens=active.LLM_MAX_TOKENS,
        report_llm_timeout_seconds=active.REPORT_LLM_TIMEOUT_SECONDS,
        # Keep the existing admin API stable while exposing the effective,
        # provider-neutral embedding configuration.
        qwen_embedding_base_url=active.EMBEDDING_API_BASE or active.QWEN_EMBEDDING_BASE_URL,
        qwen_embedding_model=active.EMBEDDING_MODEL or active.QWEN_EMBEDDING_MODEL,
        qwen_embedding_api_key_configured=bool(
            active.EMBEDDING_API_KEY.strip() or active.QWEN_EMBEDDING_API_KEY.strip()
        ),
        qwen_embedding_dimensions=(
            active.EMBEDDING_DIMENSION if active.EMBEDDING_MODEL
            else active.QWEN_EMBEDDING_DIMENSIONS
        ),
        qwen_embedding_batch_size=(
            active.EMBEDDING_BATCH_SIZE if active.EMBEDDING_MODEL
            else active.QWEN_EMBEDDING_BATCH_SIZE
        ),
        qwen_embedding_timeout_seconds=(
            active.EMBEDDING_TIMEOUT if active.EMBEDDING_MODEL
            else active.QWEN_EMBEDDING_TIMEOUT_SECONDS
        ),
        asr_provider=active.ASR_PROVIDER,
        volcengine_asr_auth_mode=(
            active.VOLCENGINE_ASR_AUTH_MODE
            if active.VOLCENGINE_ASR_AUTH_MODE in {"api_key", "legacy"}
            else (
                "api_key"
                if active.VOLCENGINE_ASR_API_KEY.strip()
                else "legacy"
                if (
                    active.VOLCENGINE_ASR_APP_ID.strip()
                    and active.VOLCENGINE_ASR_ACCESS_KEY.strip()
                )
                else "api_key"
            )
        ),
        volcengine_asr_api_key_configured=bool(
            active.VOLCENGINE_ASR_API_KEY.strip()
        ),
        volcengine_asr_app_id=active.VOLCENGINE_ASR_APP_ID,
        volcengine_asr_access_key_configured=bool(
            active.VOLCENGINE_ASR_ACCESS_KEY.strip()
        ),
        volcengine_asr_resource_id=active.VOLCENGINE_ASR_RESOURCE_ID,
        volcengine_asr_submit_url=active.VOLCENGINE_ASR_SUBMIT_URL,
        volcengine_asr_query_url=active.VOLCENGINE_ASR_QUERY_URL,
        asr_model=active.ASR_MODEL,
        asr_language=active.ASR_LANGUAGE,
        asr_max_retries=active.ASR_MAX_RETRIES,
        asr_config_version=active.ASR_CONFIG_VERSION,
        asr_poll_interval_seconds=active.ASR_POLL_INTERVAL_SECONDS,
        asr_public_base_url=active.ASR_PUBLIC_BASE_URL,
        asr_audio_signing_secret_configured=bool(
            active.ASR_AUDIO_SIGNING_SECRET.strip()
        ),
        asr_timeout_seconds=active.ASR_TIMEOUT_SECONDS,
        volcengine_asr_query_interval_seconds=(
            active.VOLCENGINE_ASR_QUERY_INTERVAL_SECONDS
        ),
        volcengine_asr_max_wait_seconds=active.VOLCENGINE_ASR_MAX_WAIT_SECONDS,
        asr_audio_url_ttl_seconds=active.ASR_AUDIO_URL_TTL_SECONDS,
    )


async def save_runtime_model_settings(
    data: ModelServicesConfigUpdate,
    db: AsyncSession,
    settings: Settings | None = None,
    actor_id: str | None = None,
) -> ModelServicesConfigOut:
    active = settings or get_settings()
    row = await db.get(SystemConfig, CONFIG_KEY)
    document = _parse(row.config_value if row else None)
    values = document["values"]
    values.update({
        "REPORT_USE_LLM": data.report_use_llm,
        "LLM_BASE_URL": data.llm_base_url,
        "LLM_MODEL": data.llm_model,
        "LLM_TEMPERATURE": data.llm_temperature,
        "LLM_TOP_P": data.llm_top_p,
        "LLM_MAX_TOKENS": data.llm_max_tokens,
        "REPORT_LLM_TIMEOUT_SECONDS": data.report_llm_timeout_seconds,
        "QWEN_EMBEDDING_BASE_URL": data.qwen_embedding_base_url,
        "QWEN_EMBEDDING_MODEL": data.qwen_embedding_model,
        "QWEN_EMBEDDING_DIMENSIONS": data.qwen_embedding_dimensions,
        "QWEN_EMBEDDING_BATCH_SIZE": data.qwen_embedding_batch_size,
        "QWEN_EMBEDDING_TIMEOUT_SECONDS": data.qwen_embedding_timeout_seconds,
        # The legacy Qwen-shaped form now also writes the generic runtime
        # contract so model training and production inference stay identical.
        "EMBEDDING_API_BASE": data.qwen_embedding_base_url,
        "EMBEDDING_MODEL": data.qwen_embedding_model,
        "EMBEDDING_DIMENSION": data.qwen_embedding_dimensions,
        "EMBEDDING_BATCH_SIZE": data.qwen_embedding_batch_size,
        "EMBEDDING_TIMEOUT": data.qwen_embedding_timeout_seconds,
        "ASR_PROVIDER": data.asr_provider,
        "ASR_MODEL": data.asr_model,
        "ASR_LANGUAGE": data.asr_language,
        "ASR_MAX_RETRIES": data.asr_max_retries,
        "ASR_CONFIG_VERSION": data.asr_config_version,
        "ASR_POLL_INTERVAL_SECONDS": data.asr_poll_interval_seconds,
        "VOLCENGINE_ASR_AUTH_MODE": data.volcengine_asr_auth_mode,
        "VOLCENGINE_ASR_APP_ID": data.volcengine_asr_app_id,
        "VOLCENGINE_ASR_RESOURCE_ID": data.volcengine_asr_resource_id,
        "VOLCENGINE_ASR_SUBMIT_URL": data.volcengine_asr_submit_url,
        "VOLCENGINE_ASR_QUERY_URL": data.volcengine_asr_query_url,
        "ASR_PUBLIC_BASE_URL": data.asr_public_base_url,
        "ASR_TIMEOUT_SECONDS": data.asr_timeout_seconds,
        "VOLCENGINE_ASR_QUERY_INTERVAL_SECONDS": (
            data.volcengine_asr_query_interval_seconds
        ),
        "VOLCENGINE_ASR_MAX_WAIT_SECONDS": data.volcengine_asr_max_wait_seconds,
        "ASR_AUDIO_URL_TTL_SECONDS": data.asr_audio_url_ttl_seconds,
    })
    encrypted = document["secrets"]

    secret_updates = (
        (
            "LLM_API_KEY",
            data.llm_api_key,
            data.clear_llm_api_key,
        ),
        (
            "VOLCENGINE_ASR_API_KEY",
            data.volcengine_asr_api_key,
            data.clear_volcengine_asr_api_key,
        ),
        (
            "VOLCENGINE_ASR_ACCESS_KEY",
            data.volcengine_asr_access_key,
            data.clear_volcengine_asr_access_key,
        ),
        (
            "ASR_AUDIO_SIGNING_SECRET",
            data.asr_audio_signing_secret,
            data.clear_asr_audio_signing_secret,
        ),
        (
            "QWEN_EMBEDDING_API_KEY",
            data.qwen_embedding_api_key,
            data.clear_qwen_embedding_api_key,
        ),
        (
            "EMBEDDING_API_KEY",
            data.qwen_embedding_api_key,
            data.clear_qwen_embedding_api_key,
        ),
    )
    for field, new_value, clear in secret_updates:
        if clear:
            encrypted[field] = _encrypt("", active)
            setattr(active, field, "")
        elif new_value:
            encrypted[field] = _encrypt(new_value, active)

    if (
        data.asr_provider == "volcengine"
        and not data.clear_asr_audio_signing_secret
        and not data.asr_audio_signing_secret
        and not encrypted.get("ASR_AUDIO_SIGNING_SECRET")
        and not active.ASR_AUDIO_SIGNING_SECRET.strip()
    ):
        generated = secrets.token_urlsafe(48)
        encrypted["ASR_AUDIO_SIGNING_SECRET"] = _encrypt(generated, active)

    serialized = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    if row is None:
        row = SystemConfig(config_key=CONFIG_KEY, config_value=serialized)
        db.add(row)
    else:
        row.config_value = serialized
    db.add(SystemConfigHistory(
        config_key=CONFIG_KEY,
        config_value=serialized,
        created_by=actor_id,
        summary={
            "action": "saved",
            "llm_model": data.llm_model,
            "asr_provider": data.asr_provider,
            "asr_auth_mode": data.volcengine_asr_auth_mode,
            "embedding_model": data.qwen_embedding_model,
        },
    ))
    await db.flush()
    _apply(document, active)
    return model_services_config_view(active)


async def list_runtime_model_history(db: AsyncSession, limit: int = 20) -> list[dict]:
    result = await db.execute(
        select(SystemConfigHistory, User.name)
        .outerjoin(User, User.id == SystemConfigHistory.created_by)
        .where(SystemConfigHistory.config_key == CONFIG_KEY)
        .order_by(SystemConfigHistory.created_at.desc(), SystemConfigHistory.id.desc())
        .limit(limit)
    )
    return [
        {
            "id": item.id,
            "created_at": item.created_at,
            "created_by": item.created_by,
            "created_by_name": actor_name,
            "summary": item.summary or {},
        }
        for item, actor_name in result.all()
    ]


async def rollback_runtime_model_settings(
    history_id: str,
    db: AsyncSession,
    settings: Settings | None = None,
    actor_id: str | None = None,
) -> ModelServicesConfigOut:
    active = settings or get_settings()
    snapshot = await db.get(SystemConfigHistory, history_id)
    if snapshot is None or snapshot.config_key != CONFIG_KEY:
        raise LookupError("配置历史不存在")
    row = await db.get(SystemConfig, CONFIG_KEY)
    if row is None:
        row = SystemConfig(config_key=CONFIG_KEY, config_value=snapshot.config_value)
        db.add(row)
    else:
        row.config_value = snapshot.config_value
    db.add(SystemConfigHistory(
        config_key=CONFIG_KEY,
        config_value=snapshot.config_value,
        created_by=actor_id,
        summary={"action": "rollback", "rollback_from": history_id},
    ))
    await db.flush()
    _apply(_parse(snapshot.config_value), active)
    return model_services_config_view(active)
