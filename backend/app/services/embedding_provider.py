"""Provider-neutral, privacy-preserving remote text embeddings."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence
from urllib.parse import urlparse

import httpx
import numpy as np

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class EmbeddingConfigurationError(ValueError):
    pass


class EmbeddingProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str
    model: str
    version: str
    dimensions: int
    base_url: str
    api_key: str = field(repr=False)
    normalized: bool = True
    instruction: str | None = None
    batch_size: int = 20
    timeout_seconds: float = 60.0
    max_retries: int = 4

    def validate(self, *, require_api_key: bool = True) -> None:
        if not self.provider.strip():
            raise EmbeddingConfigurationError("EMBEDDING_PROVIDER 不能为空")
        if not self.model.strip() or not self.version.strip():
            raise EmbeddingConfigurationError("Embedding 模型及版本不能为空")
        parsed = urlparse(self.base_url.strip())
        if parsed.scheme != "https" or not parsed.netloc:
            raise EmbeddingConfigurationError("EMBEDDING_API_BASE 必须是有效的 HTTPS 地址")
        if require_api_key and not self.api_key.strip():
            raise EmbeddingConfigurationError("EMBEDDING_API_KEY 未配置")
        if not 1 <= self.dimensions <= 65536:
            raise EmbeddingConfigurationError("EMBEDDING_DIMENSION 不合法")
        if not 1 <= self.batch_size <= 256:
            raise EmbeddingConfigurationError("EMBEDDING_BATCH_SIZE 必须在 1 到 256 之间")
        if not 1 <= self.timeout_seconds <= 600:
            raise EmbeddingConfigurationError("EMBEDDING_TIMEOUT 必须在 1 到 600 秒之间")
        if not 0 <= self.max_retries <= 10:
            raise EmbeddingConfigurationError("EMBEDDING_MAX_RETRIES 必须在 0 到 10 之间")

    @property
    def endpoint(self) -> str:
        normalized = self.base_url.rstrip("/")
        return normalized if normalized.endswith("/embeddings") else f"{normalized}/embeddings"

    @property
    def instruction_hash(self) -> str:
        return hashlib.sha256((self.instruction or "").encode("utf-8")).hexdigest()

    def identity(self) -> dict[str, object]:
        return {
            "embedding_provider": self.provider,
            "embedding_model": self.model,
            "embedding_version": self.version,
            "embedding_dimension": self.dimensions,
            "embedding_normalized": self.normalized,
            "embedding_instruction": self.instruction,
        }


@dataclass(frozen=True)
class EmbeddingCall:
    vectors: np.ndarray
    request_latencies_ms: tuple[float, ...]
    request_count: int
    failed_request_count: int
    batch_sizes: tuple[int, ...]


class EmbeddingProvider(ABC):
    config: EmbeddingConfig

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingCall:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embedding_cache_key(config: EmbeddingConfig, text: str) -> str:
    material = {
        "text_hash": text_hash(text.strip()),
        **config.identity(),
    }
    encoded = "\0".join(f"{key}={material[key]}" for key in sorted(material))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_vectors(vectors: np.ndarray) -> np.ndarray:
    values = np.asarray(vectors, dtype=np.float32)
    if values.ndim != 2 or np.any(~np.isfinite(values)):
        raise EmbeddingProviderError("Embedding API 返回了非法向量")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise EmbeddingProviderError("Embedding API 返回了零向量")
    return values / norms


class RemoteEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible remote provider with pooled async HTTP and retries."""

    def __init__(
        self,
        config: EmbeddingConfig,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        config.validate()
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout_seconds),
            transport=transport,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={
                "Authorization": f"Bearer {config.api_key.strip()}",
                "Content-Type": "application/json",
                "User-Agent": "ZhijianMetacognition/EmbeddingProvider-1",
            },
        )
        self._sleep = sleep

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "RemoteEmbeddingProvider":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def embed(self, texts: list[str]) -> EmbeddingCall:
        normalized_texts = [str(text).strip() for text in texts]
        if not normalized_texts:
            raise ValueError("Embedding 输入不能为空")
        if any(not text for text in normalized_texts):
            raise ValueError("Embedding 输入不能包含空文本")
        all_vectors: list[np.ndarray] = []
        latencies: list[float] = []
        batch_sizes: list[int] = []
        failed_requests = 0
        for start in range(0, len(normalized_texts), self.config.batch_size):
            batch = normalized_texts[start:start + self.config.batch_size]
            vectors, latency, failures = await self._embed_batch(batch)
            all_vectors.append(vectors)
            latencies.append(latency)
            batch_sizes.append(len(batch))
            failed_requests += failures
        matrix = np.vstack(all_vectors).astype(np.float32)
        if matrix.shape != (len(normalized_texts), self.config.dimensions):
            raise EmbeddingProviderError(
                f"Embedding 数量或维度异常：期望 ({len(normalized_texts)}, {self.config.dimensions})，实际 {matrix.shape}"
            )
        return EmbeddingCall(
            vectors=matrix,
            request_latencies_ms=tuple(latencies),
            request_count=len(latencies),
            failed_request_count=failed_requests,
            batch_sizes=tuple(batch_sizes),
        )

    async def _embed_batch(self, texts: list[str]) -> tuple[np.ndarray, float, int]:
        input_texts = (
            [f"{self.config.instruction}{text}" for text in texts]
            if self.config.instruction else texts
        )
        payload = {
            "model": self.config.model,
            "input": input_texts,
            "dimensions": self.config.dimensions,
            "encoding_format": "float",
        }
        batch_fingerprint = hashlib.sha256(
            "\0".join(text_hash(text) for text in texts).encode("ascii")
        ).hexdigest()[:16]
        failed_attempts = 0
        for attempt in range(self.config.max_retries + 1):
            started = time.perf_counter()
            response: httpx.Response | None = None
            try:
                response = await self._client.post(self.config.endpoint, json=payload)
                latency_ms = (time.perf_counter() - started) * 1000
                if response.status_code in RETRYABLE_STATUS_CODES:
                    raise EmbeddingProviderError(
                        f"Embedding API 暂时不可用（HTTP {response.status_code}）",
                        retryable=True,
                        status_code=response.status_code,
                    )
                response.raise_for_status()
                vectors = self._parse(response, len(texts))
                logger.info(
                    "embedding request completed provider=%s model=%s batch=%s hash=%s latency_ms=%.1f",
                    self.config.provider, self.config.model, len(texts), batch_fingerprint, latency_ms,
                )
                return vectors, latency_ms, failed_attempts
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                raise EmbeddingProviderError(
                    f"Embedding API 拒绝请求（HTTP {status}）",
                    retryable=False,
                    status_code=status,
                ) from error
            except (httpx.TimeoutException, httpx.NetworkError, EmbeddingProviderError) as error:
                retryable = not isinstance(error, EmbeddingProviderError) or error.retryable
                failed_attempts += 1
                if not retryable or attempt >= self.config.max_retries:
                    logger.warning(
                        "embedding request failed provider=%s model=%s batch=%s hash=%s attempts=%s error=%s",
                        self.config.provider, self.config.model, len(texts), batch_fingerprint,
                        attempt + 1, type(error).__name__,
                    )
                    if isinstance(error, EmbeddingProviderError):
                        raise
                    raise EmbeddingProviderError(
                        f"Embedding API 网络请求失败：{type(error).__name__}", retryable=True
                    ) from error
                retry_after = response.headers.get("Retry-After") if response is not None else None
                try:
                    delay = min(float(retry_after), 30.0) if retry_after else min(2**attempt, 15.0)
                except (TypeError, ValueError):
                    delay = min(2**attempt, 15.0)
                await self._sleep(delay)
        raise EmbeddingProviderError("Embedding API 请求失败", retryable=True)

    def _parse(self, response: httpx.Response, expected_count: int) -> np.ndarray:
        try:
            body = response.json()
            items = sorted(body["data"], key=lambda item: int(item["index"]))
            vectors = np.asarray([item["embedding"] for item in items], dtype=np.float32)
        except (KeyError, TypeError, ValueError) as error:
            raise EmbeddingProviderError("Embedding API 响应格式无效") from error
        if len(items) != expected_count:
            raise EmbeddingProviderError(
                f"Embedding API 返回数量异常：期望 {expected_count}，实际 {len(items)}"
            )
        if vectors.shape != (expected_count, self.config.dimensions):
            raise EmbeddingProviderError(
                f"Embedding API 返回维度异常：期望 {self.config.dimensions}，实际 {vectors.shape}"
            )
        return normalize_vectors(vectors) if self.config.normalized else vectors


def assert_embedding_identity(expected: dict[str, object], actual: EmbeddingConfig) -> None:
    current = actual.identity()
    mismatches = {
        key: {"trained": expected.get(key), "runtime": current.get(key)}
        for key in current
        if expected.get(key) != current.get(key)
    }
    if mismatches:
        raise EmbeddingConfigurationError(
            f"运行时 Embedding 配置与训练配置不一致：{mismatches}"
        )
