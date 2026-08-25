"""Alibaba Cloud Model Studio qwen3.7 embedding client and durable cache."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import numpy as np


RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class EmbeddingConfigurationError(ValueError):
    """Raised when the provider configuration is incomplete or unsafe."""


class EmbeddingProviderError(RuntimeError):
    """Raised when the remote provider cannot return valid vectors."""


@dataclass(frozen=True)
class QwenEmbeddingConfig:
    api_key: str
    base_url: str
    model: str = "qwen3.7-text-embedding"
    dimensions: int = 1024
    batch_size: int = 20
    timeout_seconds: float = 60.0
    max_retries: int = 5

    def validate(self, *, require_api_key: bool = True) -> None:
        if require_api_key and not self.api_key.strip():
            raise EmbeddingConfigurationError("未配置 DASHSCOPE_API_KEY")
        normalized = self.base_url.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.netloc:
            raise EmbeddingConfigurationError("QWEN_EMBEDDING_BASE_URL 必须是有效的HTTPS地址")
        if "{workspaceid}" in normalized.lower() or "change_me" in normalized.lower():
            raise EmbeddingConfigurationError("请将向量服务地址中的WorkspaceId占位符替换为真实值")
        if self.model != "qwen3.7-text-embedding":
            raise EmbeddingConfigurationError("当前研究协议固定使用 qwen3.7-text-embedding")
        if self.dimensions not in {256, 512, 768, 1024, 1536, 2048, 2560}:
            raise EmbeddingConfigurationError("qwen3.7向量维度必须是官方支持值")
        if not 1 <= self.batch_size <= 20:
            raise EmbeddingConfigurationError("qwen3.7单批文本数量必须在1到20之间")
        if not 5 <= self.timeout_seconds <= 300:
            raise EmbeddingConfigurationError("向量请求超时必须在5到300秒之间")
        if not 0 <= self.max_retries <= 10:
            raise EmbeddingConfigurationError("重试次数必须在0到10之间")

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.strip().rstrip('/')}/embeddings"


@dataclass(frozen=True)
class EmbeddingBatchResult:
    vectors: np.ndarray
    request_id: str
    total_tokens: int


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(model: str, dimensions: int, text: str) -> str:
    material = f"{model}\n{dimensions}\n{text}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def normalize_vectors(vectors: np.ndarray) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if np.any(~np.isfinite(array)) or np.any(norms <= 0):
        raise EmbeddingProviderError("向量服务返回了空向量或非有限数值")
    return array / norms


class QwenEmbeddingClient:
    def __init__(
        self,
        config: QwenEmbeddingConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self._client = httpx.Client(
            timeout=config.timeout_seconds,
            transport=transport,
            headers={
                "Authorization": f"Bearer {config.api_key.strip()}",
                "Content-Type": "application/json",
                "User-Agent": "ZhijianMetacognitionResearch/1.0",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "QwenEmbeddingClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def embed(self, texts: list[str]) -> EmbeddingBatchResult:
        if not texts or len(texts) > self.config.batch_size:
            raise ValueError("单次向量请求文本数量不正确")
        if any(not text.strip() for text in texts):
            raise ValueError("向量请求不能包含空文本")
        payload = {
            "model": self.config.model,
            "input": texts,
            "dimensions": self.config.dimensions,
            "encoding_format": "float",
        }
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            response: httpx.Response | None = None
            try:
                response = self._client.post(self.config.endpoint, json=payload)
                if response.status_code in RETRYABLE_STATUS_CODES:
                    raise EmbeddingProviderError(
                        f"向量服务暂时不可用（HTTP {response.status_code}）"
                    )
                response.raise_for_status()
                return self._parse_response(response)
            except (httpx.TimeoutException, httpx.NetworkError, EmbeddingProviderError) as error:
                last_error = error
                if attempt >= self.config.max_retries:
                    break
                retry_after = response.headers.get("Retry-After") if response is not None else None
                try:
                    delay = min(float(retry_after), 30.0) if retry_after else min(2**attempt, 15.0)
                except ValueError:
                    delay = min(2**attempt, 15.0)
                time.sleep(delay)
            except httpx.HTTPStatusError as error:
                detail = error.response.text[:500]
                raise EmbeddingProviderError(
                    f"向量服务拒绝请求（HTTP {error.response.status_code}）：{detail}"
                ) from error
        raise EmbeddingProviderError(f"向量请求多次失败：{last_error}")

    def _parse_response(self, response: httpx.Response) -> EmbeddingBatchResult:
        try:
            body = response.json()
            items = sorted(body["data"], key=lambda item: int(item["index"]))
            vectors = np.asarray([item["embedding"] for item in items], dtype=np.float32)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise EmbeddingProviderError("向量服务响应格式无效") from error
        if vectors.ndim != 2 or vectors.shape[1] != self.config.dimensions:
            raise EmbeddingProviderError(
                f"向量维度异常：期望{self.config.dimensions}，实际{vectors.shape}"
            )
        usage = body.get("usage") if isinstance(body, dict) else {}
        total_tokens = int((usage or {}).get("total_tokens", 0) or 0)
        request_id = str(body.get("id") or response.headers.get("x-request-id") or "")
        return EmbeddingBatchResult(
            vectors=normalize_vectors(vectors),
            request_id=request_id,
            total_tokens=total_tokens,
        )


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_cache (
                cache_key TEXT PRIMARY KEY,
                text_hash TEXT NOT NULL,
                model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                vector BLOB NOT NULL,
                request_id TEXT NOT NULL DEFAULT '',
                total_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "EmbeddingCache":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(self, key: str, dimensions: int) -> np.ndarray | None:
        row = self._db.execute(
            "SELECT vector FROM embedding_cache WHERE cache_key = ? AND dimensions = ?",
            (key, dimensions),
        ).fetchone()
        if row is None:
            return None
        vector = np.frombuffer(row[0], dtype=np.float32).copy()
        if vector.shape != (dimensions,):
            raise ValueError(f"缓存向量维度损坏：{key}")
        return vector

    def put_many(
        self,
        *,
        keys: list[str],
        texts: list[str],
        model: str,
        dimensions: int,
        vectors: np.ndarray,
        request_id: str,
        total_tokens: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        token_share = total_tokens // max(len(keys), 1)
        rows = [
            (
                key,
                text_hash(text),
                model,
                dimensions,
                np.asarray(vector, dtype=np.float32).tobytes(),
                request_id,
                token_share,
                now,
            )
            for key, text, vector in zip(keys, texts, vectors, strict=True)
        ]
        self._db.executemany(
            """
            INSERT INTO embedding_cache
                (cache_key, text_hash, model, dimensions, vector, request_id, total_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                vector = excluded.vector,
                request_id = excluded.request_id,
                total_tokens = excluded.total_tokens,
                created_at = excluded.created_at
            """,
            rows,
        )
        self._db.commit()
