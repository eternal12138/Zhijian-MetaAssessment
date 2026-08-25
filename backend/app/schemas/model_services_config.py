"""Safe administrator input/output models for runtime model configuration."""
from __future__ import annotations

from urllib.parse import urlparse

from datetime import datetime

from pydantic import Field, field_validator
from app.schemas.base import ApiModel as BaseModel

SUPPORTED_ASR_LANGUAGES = {
    "",
    "zh-CN",
    "en-US",
    "ja-JP",
    "id-ID",
    "es-MX",
    "pt-BR",
    "de-DE",
    "fr-FR",
    "ko-KR",
    "fil-PH",
    "ms-MY",
    "th-TH",
    "ar-SA",
    "it-IT",
    "bn-BD",
    "el-GR",
    "nl-NL",
    "ru-RU",
    "tr-TR",
    "vi-VN",
    "pl-PL",
    "ro-RO",
    "ne-NP",
    "uk-UA",
    "yue-CN",
}


def _https_url(value: str, field_label: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized.startswith("https://"):
        raise ValueError(f"{field_label} 必须使用 https://")
    return normalized


class ModelServicesConfigUpdate(BaseModel):
    report_use_llm: bool = True
    llm_base_url: str = Field(min_length=8, max_length=500)
    llm_model: str = Field(min_length=1, max_length=200)
    llm_api_key: str | None = Field(default=None, max_length=1000)
    clear_llm_api_key: bool = False
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_top_p: float = Field(default=0.9, gt=0, le=1)
    llm_max_tokens: int = Field(default=2048, ge=1, le=32768)
    report_llm_timeout_seconds: float = Field(default=20, ge=3, le=180)

    qwen_embedding_base_url: str = Field(default="", max_length=500)
    qwen_embedding_model: str = Field(default="qwen3.7-text-embedding", min_length=1, max_length=200)
    qwen_embedding_api_key: str | None = Field(default=None, max_length=1000)
    clear_qwen_embedding_api_key: bool = False
    qwen_embedding_dimensions: int = Field(default=1024, ge=1, le=65536)
    qwen_embedding_batch_size: int = Field(default=20, ge=1, le=256)
    qwen_embedding_timeout_seconds: float = Field(default=60, ge=1, le=600)

    asr_provider: str = Field(default="disabled", pattern="^(disabled|volcengine)$")
    volcengine_asr_auth_mode: str = Field(
        default="api_key",
        pattern="^(api_key|legacy)$",
    )
    volcengine_asr_api_key: str | None = Field(default=None, max_length=1000)
    clear_volcengine_asr_api_key: bool = False
    volcengine_asr_app_id: str = Field(default="", max_length=200)
    volcengine_asr_access_key: str | None = Field(default=None, max_length=1000)
    clear_volcengine_asr_access_key: bool = False
    volcengine_asr_resource_id: str = Field(min_length=1, max_length=200)
    volcengine_asr_submit_url: str = Field(min_length=8, max_length=500)
    volcengine_asr_query_url: str = Field(min_length=8, max_length=500)
    asr_model: str = Field(default="bigmodel", min_length=1, max_length=200)
    asr_language: str = Field(default="", max_length=20)
    asr_max_retries: int = Field(default=3, ge=0, le=10)
    asr_config_version: str = Field(default="2026.1", min_length=1, max_length=50)
    asr_poll_interval_seconds: float = Field(default=2, ge=0.5, le=30)
    asr_public_base_url: str = Field(default="", max_length=500)
    asr_audio_signing_secret: str | None = Field(default=None, max_length=1000)
    clear_asr_audio_signing_secret: bool = False
    asr_timeout_seconds: float = Field(default=180, ge=10, le=600)
    volcengine_asr_query_interval_seconds: float = Field(default=3, ge=0.5, le=30)
    volcengine_asr_max_wait_seconds: float = Field(default=600, ge=30, le=1800)
    asr_audio_url_ttl_seconds: int = Field(default=600, ge=60, le=3600)

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_service_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        is_local_http = (
            parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        if parsed.scheme != "https" and not is_local_http:
            raise ValueError(
                "LLM 服务地址必须使用 https://；本地开发仅允许 localhost、127.0.0.1 或 ::1"
            )
        return normalized

    @field_validator(
        "volcengine_asr_submit_url",
        "volcengine_asr_query_url",
    )
    @classmethod
    def validate_asr_service_url(cls, value: str) -> str:
        return _https_url(value, "ASR 云服务地址")

    @field_validator("qwen_embedding_base_url")
    @classmethod
    def validate_qwen_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if normalized and not normalized.startswith("https://"):
            raise ValueError("Qwen 嵌入服务地址必须使用 https://")
        return normalized

    @field_validator("asr_public_base_url")
    @classmethod
    def validate_public_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if normalized and not normalized.startswith("https://"):
            raise ValueError("音频公网地址必须使用 https://")
        return normalized

    @field_validator("asr_language")
    @classmethod
    def validate_asr_language(cls, value: str) -> str:
        normalized = value.strip()
        normalized = {
            "auto": "",
            "zh": "zh-CN",
            "en": "en-US",
            "ja": "ja-JP",
            "ko": "ko-KR",
        }.get(normalized, normalized)
        if normalized not in SUPPORTED_ASR_LANGUAGES:
            raise ValueError("不支持的豆包录音文件识别语言代码")
        return normalized

    @field_validator(
        "llm_api_key",
        "volcengine_asr_api_key",
        "volcengine_asr_access_key",
        "asr_audio_signing_secret",
        "qwen_embedding_api_key",
    )
    @classmethod
    def normalize_optional_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ModelServicesConfigOut(BaseModel):
    report_use_llm: bool
    llm_base_url: str
    llm_model: str
    llm_api_key_configured: bool
    llm_temperature: float
    llm_top_p: float
    llm_max_tokens: int
    report_llm_timeout_seconds: float
    qwen_embedding_base_url: str
    qwen_embedding_model: str
    qwen_embedding_api_key_configured: bool
    qwen_embedding_dimensions: int
    qwen_embedding_batch_size: int
    qwen_embedding_timeout_seconds: float

    asr_provider: str
    volcengine_asr_auth_mode: str
    volcengine_asr_api_key_configured: bool
    volcengine_asr_app_id: str
    volcengine_asr_access_key_configured: bool
    volcengine_asr_resource_id: str
    volcengine_asr_submit_url: str
    volcengine_asr_query_url: str
    asr_model: str
    asr_language: str
    asr_max_retries: int
    asr_config_version: str
    asr_poll_interval_seconds: float
    asr_public_base_url: str
    asr_audio_signing_secret_configured: bool
    asr_timeout_seconds: float
    volcengine_asr_query_interval_seconds: float
    volcengine_asr_max_wait_seconds: float
    asr_audio_url_ttl_seconds: int
    storage: str = "encrypted_database"


class ModelConfigHistoryOut(BaseModel):
    id: str
    created_at: datetime
    created_by: str | None = None
    created_by_name: str | None = None
    summary: dict = Field(default_factory=dict)
