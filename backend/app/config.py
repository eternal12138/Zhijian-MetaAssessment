"""
应用配置，基于 pydantic-settings 从环境变量 / .env 加载。
"""
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"


def _is_absolute_path(value: str) -> bool:
    candidate = value.strip()
    expanded = str(Path(candidate).expanduser())
    return (
        Path(expanded).is_absolute()
        or PurePosixPath(candidate).is_absolute()
        or PureWindowsPath(candidate).is_absolute()
    )


class Settings(BaseSettings):
    # ---- 应用 ----
    APP_NAME: str = "知见 AI 元认知测评"
    APP_VERSION: str = "0.2.0"
    APP_DEBUG: bool = True
    ENABLE_API_DOCS: bool = True
    ALLOW_PUBLIC_REGISTRATION: bool = False
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    TRUSTED_HOSTS: str = "localhost,127.0.0.1"
    SECURITY_HEADERS_ENABLED: bool = True
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_PER_MINUTE: int = Field(default=20, ge=5, le=600)
    RATE_LIMIT_GENERAL_PER_MINUTE: int = Field(default=300, ge=60, le=10000)
    RATE_LIMIT_BYPASS_LOCAL_DEBUG: bool = True

    # ---- 数据库 ----
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "metacognition_db"
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0, le=100)
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60)
    DB_ECHO: bool = False

    # ---- JWT ----
    SECRET_KEY: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 1440  # 24 小时
    LOGIN_MAX_FAILED_ATTEMPTS: int = 8
    LOGIN_LOCKOUT_MINUTES: int = 15

    # ---- LLM（OpenAI 兼容接口：Ollama / 火山引擎 / DeepSeek 均可）----
    LLM_API_KEY: str = "ollama"
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_MODEL: str = "deepseek-r1:8b"
    LLM_TEMPERATURE: float = 0.7
    LLM_TOP_P: float = 0.9
    LLM_MAX_TOKENS: int = 2048
    REPORT_USE_LLM: bool = True
    REPORT_LLM_TIMEOUT_SECONDS: float = 20.0
    METACOGNITIVE_EXTRACTION_ENABLED: bool = True
    METACOGNITIVE_EXTRACTOR_VERSION: str = "1.0.0"
    METACOGNITIVE_EXTRACTION_TIMEOUT_SECONDS: float = 60.0
    METACOGNITIVE_EXTRACTION_MAX_RETRIES: int = Field(default=2, ge=0, le=5)

    # ---- Qwen 文本嵌入与分类模型训练 ----
    QWEN_EMBEDDING_API_KEY: str = ""
    QWEN_EMBEDDING_BASE_URL: str = ""
    QWEN_EMBEDDING_MODEL: str = "qwen3.7-text-embedding"
    QWEN_EMBEDDING_DIMENSIONS: int = Field(default=1024, ge=256, le=2560)
    QWEN_EMBEDDING_BATCH_SIZE: int = Field(default=20, ge=1, le=20)
    QWEN_EMBEDDING_TIMEOUT_SECONDS: float = Field(default=60, ge=5, le=300)
    # Provider-neutral aliases. Empty values fall back to the Qwen settings so
    # existing administrator configuration remains compatible.
    EMBEDDING_PROVIDER: str = "openai_compatible"
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = ""
    EMBEDDING_VERSION: str = "default"
    EMBEDDING_DIMENSION: int = Field(default=1024, ge=1, le=65536)
    EMBEDDING_NORMALIZED: bool = True
    EMBEDDING_INSTRUCTION: str = ""
    EMBEDDING_TIMEOUT: float = Field(default=60, ge=1, le=600)
    EMBEDDING_BATCH_SIZE: int = Field(default=20, ge=1, le=256)
    EMBEDDING_MAX_RETRIES: int = Field(default=4, ge=0, le=10)
    EMBEDDING_FALLBACK_ENABLED: bool = False
    TFIDF_FALLBACK_MODEL_PATH: str = ""
    MODEL_TRAINING_DIR: str = "models/training"

    # ---- 语音 ----
    ASR_PROVIDER: str = "disabled"
    ASR_API_KEY: str = ""
    ASR_BASE_URL: str = ""
    ASR_MODEL: str = "whisper-1"
    ASR_LANGUAGE: str = ""
    ASR_TIMEOUT_SECONDS: float = 180.0
    ASR_MAX_RETRIES: int = 3
    ASR_CONFIG_VERSION: str = "2026.1"
    ASR_POLL_INTERVAL_SECONDS: float = 2.0
    ASR_PUBLIC_BASE_URL: str = ""
    ASR_AUDIO_SIGNING_SECRET: str = ""
    ASR_AUDIO_URL_TTL_SECONDS: int = 600
    VOLCENGINE_ASR_API_KEY: str = ""
    VOLCENGINE_ASR_AUTH_MODE: str = "auto"
    VOLCENGINE_ASR_APP_ID: str = ""
    VOLCENGINE_ASR_ACCESS_KEY: str = ""
    VOLCENGINE_ASR_RESOURCE_ID: str = "volc.seedasr.auc"
    VOLCENGINE_ASR_SUBMIT_URL: str = (
        "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    )
    VOLCENGINE_ASR_QUERY_URL: str = (
        "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
    )
    VOLCENGINE_ASR_QUERY_INTERVAL_SECONDS: float = 3.0
    VOLCENGINE_ASR_MAX_WAIT_SECONDS: float = 600.0
    FFMPEG_PATH: str = "ffmpeg"
    AUDIO_UPLOAD_DIR: str = "uploads/audio"
    AUDIO_CHUNK_MAX_BYTES: int = 8 * 1024 * 1024
    NARRATION_UPLOAD_MAX_BYTES: int = 20 * 1024 * 1024
    RESEARCH_EXPORT_DIR: str = "exports/research"
    RESEARCH_EXPORT_MIN_FREE_BYTES: int = Field(
        default=1024 * 1024 * 1024,
        ge=64 * 1024 * 1024,
    )

    @model_validator(mode="after")
    def validate_production_security(self):
        if not self.APP_DEBUG:
            if self.SECRET_KEY in {
                "dev-secret-change-in-production",
                "dev-secret-key-change-in-production",
                "change-me-to-a-random-secret-key",
            } or self.SECRET_KEY.startswith("CHANGE_ME") or len(self.SECRET_KEY) < 32:
                raise ValueError("生产环境必须配置至少 32 字符的高强度 SECRET_KEY")
            if self.ALLOW_PUBLIC_REGISTRATION:
                raise ValueError("生产环境不允许开启公开注册")
            if self.ENABLE_API_DOCS:
                raise ValueError("生产环境必须关闭 API 文档")
            if not self.SECURITY_HEADERS_ENABLED:
                raise ValueError("生产环境必须启用安全响应头")
            if not self.RATE_LIMIT_ENABLED:
                raise ValueError("生产环境必须启用 API 安全限流")
            if "*" in self.cors_origins:
                raise ValueError("生产环境 CORS_ORIGINS 不能使用通配符")
            if not self.cors_origins or any(
                not origin.startswith("https://")
                for origin in self.cors_origins
            ):
                raise ValueError("生产环境 CORS_ORIGINS 必须使用 HTTPS")
            if not self.trusted_hosts or "*" in self.trusted_hosts:
                raise ValueError("生产环境 TRUSTED_HOSTS 必须显式配置")
            if self.DB_USER.strip().lower() == "root":
                raise ValueError("生产环境数据库必须使用最小权限的独立账号")
            if (
                not self.DB_PASSWORD
                or self.DB_PASSWORD.startswith("CHANGE_ME")
                or self.DB_PASSWORD == "your_password_here"
            ):
                raise ValueError("生产环境必须配置独立数据库密码")
            if not _is_absolute_path(self.AUDIO_UPLOAD_DIR):
                raise ValueError("生产环境 AUDIO_UPLOAD_DIR 必须使用绝对路径")
            if not _is_absolute_path(self.RESEARCH_EXPORT_DIR):
                raise ValueError("生产环境 RESEARCH_EXPORT_DIR 必须使用绝对路径")
            if not _is_absolute_path(self.MODEL_TRAINING_DIR):
                raise ValueError("生产环境 MODEL_TRAINING_DIR 必须使用绝对路径")
            if self.ASR_PROVIDER.strip().lower() == "volcengine":
                api_key = self.VOLCENGINE_ASR_API_KEY.strip()
                app_id = self.VOLCENGINE_ASR_APP_ID.strip()
                access_key = self.VOLCENGINE_ASR_ACCESS_KEY.strip()
                auth_mode = self.VOLCENGINE_ASR_AUTH_MODE.strip().lower()
                api_key_ready = bool(
                    api_key and not api_key.startswith("CHANGE_ME")
                )
                legacy_credentials_ready = bool(
                    app_id
                    and access_key
                    and not app_id.startswith("CHANGE_ME")
                    and not access_key.startswith("CHANGE_ME")
                )
                credentials_ready = (
                    api_key_ready
                    if auth_mode == "api_key"
                    else legacy_credentials_ready
                    if auth_mode == "legacy"
                    else api_key_ready or legacy_credentials_ready
                )
                if not credentials_ready:
                    raise ValueError(
                        "火山引擎 ASR 必须配置 API Key，或同时配置 App ID 与 Access Key"
                    )
                if not self.ASR_PUBLIC_BASE_URL.startswith("https://"):
                    raise ValueError(
                        "生产环境火山引擎 ASR 必须配置 HTTPS 的 ASR_PUBLIC_BASE_URL"
                    )
                if (
                    len(self.ASR_AUDIO_SIGNING_SECRET) < 32
                    or self.ASR_AUDIO_SIGNING_SECRET.startswith("CHANGE_ME")
                ):
                    raise ValueError(
                        "生产环境 ASR_AUDIO_SIGNING_SECRET 至少需要 32 个字符"
                    )
        return self

    @property
    def cors_origins(self) -> list[str]:
        """允许通过逗号配置多个前端来源。"""
        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def trusted_hosts(self) -> list[str]:
        return [
            host.strip()
            for host in self.TRUSTED_HOSTS.split(",")
            if host.strip()
        ]

    @property
    def audio_upload_path(self) -> Path:
        """将相对上传目录稳定地锚定到 backend，而不是当前工作目录。"""
        configured_path = Path(self.AUDIO_UPLOAD_DIR).expanduser()
        if configured_path.is_absolute():
            return configured_path.resolve()
        return (BACKEND_DIR / configured_path).resolve()

    @property
    def research_export_path(self) -> Path:
        configured_path = Path(self.RESEARCH_EXPORT_DIR).expanduser()
        if configured_path.is_absolute():
            return configured_path.resolve()
        return (BACKEND_DIR / configured_path).resolve()

    @property
    def model_training_path(self) -> Path:
        configured_path = Path(self.MODEL_TRAINING_DIR).expanduser()
        if configured_path.is_absolute():
            return configured_path.resolve()
        return (BACKEND_DIR / configured_path).resolve()

    @property
    def asr_provider_ready(self) -> bool:
        provider = self.ASR_PROVIDER.strip().lower()
        if provider in {"", "disabled"}:
            return False
        if provider in {"openai_compatible", "whisper"}:
            return bool(self.ASR_BASE_URL.strip())
        if provider == "volcengine":
            auth_mode = self.VOLCENGINE_ASR_AUTH_MODE.strip().lower()
            api_key_ready = bool(self.VOLCENGINE_ASR_API_KEY.strip())
            legacy_credentials_ready = bool(
                    self.VOLCENGINE_ASR_APP_ID.strip()
                    and self.VOLCENGINE_ASR_ACCESS_KEY.strip()
            )
            credentials_ready = (
                api_key_ready
                if auth_mode == "api_key"
                else legacy_credentials_ready
                if auth_mode == "legacy"
                else api_key_ready or legacy_credentials_ready
            )
            return bool(
                credentials_ready
                and self.ASR_PUBLIC_BASE_URL.strip()
                and self.ASR_AUDIO_SIGNING_SECRET.strip()
            )
        return False

    @property
    def database_url(self) -> str:
        """SQLAlchemy async 连接字符串 (aiomysql)"""
        return (
            f"mysql+aiomysql://{quote_plus(self.DB_USER)}:"
            f"{quote_plus(self.DB_PASSWORD)}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            "?charset=utf8mb4"
        )

    @property
    def database_url_sync(self) -> str:
        """同步连接字符串 (pymysql, 供 Alembic 使用)"""
        return (
            f"mysql+pymysql://{quote_plus(self.DB_USER)}:"
            f"{quote_plus(self.DB_PASSWORD)}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            "?charset=utf8mb4"
        )

    model_config = {
        "env_file": ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
