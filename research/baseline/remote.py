from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

BACKEND_ROOT = Path(__file__).parents[2] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.embedding_provider import (
    EmbeddingConfig,
    EmbeddingProvider,
    RemoteEmbeddingProvider,
    embedding_cache_key,
    text_hash,
)


def config_from_environment() -> EmbeddingConfig:
    model = os.getenv("EMBEDDING_MODEL") or os.getenv("QWEN_EMBEDDING_MODEL", "")
    base_url = os.getenv("EMBEDDING_API_BASE") or os.getenv("QWEN_EMBEDDING_BASE_URL", "")
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("QWEN_EMBEDDING_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")
    dimensions = int(os.getenv("EMBEDDING_DIMENSION") or os.getenv("QWEN_EMBEDDING_DIMENSIONS", "1024"))
    return EmbeddingConfig(
        provider=os.getenv("EMBEDDING_PROVIDER", "openai_compatible"),
        model=model,
        version=os.getenv("EMBEDDING_VERSION", "default"),
        dimensions=dimensions,
        base_url=base_url,
        api_key=api_key,
        normalized=os.getenv("EMBEDDING_NORMALIZED", "true").lower() in {"1", "true", "yes", "on"},
        instruction=os.getenv("EMBEDDING_INSTRUCTION") or None,
        batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "20")),
        timeout_seconds=float(os.getenv("EMBEDDING_TIMEOUT", "60")),
        max_retries=int(os.getenv("EMBEDDING_MAX_RETRIES", "4")),
    )


class SqliteEmbeddingCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS embeddings (
                cache_key TEXT PRIMARY KEY,
                text_hash TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                model_version TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                normalized INTEGER NOT NULL,
                instruction_hash TEXT NOT NULL,
                vector BLOB NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def get(self, key: str, dimensions: int) -> np.ndarray | None:
        row = self.connection.execute(
            "SELECT vector FROM embeddings WHERE cache_key=? AND dimensions=?",
            (key, dimensions),
        ).fetchone()
        if row is None:
            return None
        vector = np.frombuffer(row[0], dtype=np.float32).copy()
        if vector.shape != (dimensions,):
            raise ValueError(f"Embedding cache vector is corrupt: {key}")
        return vector

    def put_many(self, config: EmbeddingConfig, texts: Sequence[str], vectors: np.ndarray) -> None:
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                embedding_cache_key(config, text), text_hash(text), config.provider,
                config.model, config.version, config.dimensions, int(config.normalized),
                config.instruction_hash, np.asarray(vector, dtype=np.float32).tobytes(), now,
            )
            for text, vector in zip(texts, vectors, strict=True)
        ]
        self.connection.executemany(
            """INSERT OR REPLACE INTO embeddings
            (cache_key,text_hash,provider,model,model_version,dimensions,normalized,instruction_hash,vector,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        self.connection.commit()


async def load_or_create_remote_embeddings(
    texts: Sequence[str],
    *,
    config: EmbeddingConfig,
    cache_path: Path,
    provider: EmbeddingProvider | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    config.validate()
    cache = SqliteEmbeddingCache(cache_path)
    vectors: list[np.ndarray | None] = [None] * len(texts)
    missing_indices: list[int] = []
    try:
        for index, text in enumerate(texts):
            vector = cache.get(embedding_cache_key(config, text), config.dimensions)
            if vector is None:
                missing_indices.append(index)
            else:
                vectors[index] = vector
        created_provider = provider is None
        active_provider = provider or RemoteEmbeddingProvider(config)
        api_latencies: list[float] = []
        api_batches: list[int] = []
        api_requests = 0
        api_failures = 0
        try:
            if missing_indices:
                missing_texts = [texts[index] for index in missing_indices]
                result = await active_provider.embed(list(missing_texts))
                cache.put_many(config, missing_texts, result.vectors)
                for index, vector in zip(missing_indices, result.vectors, strict=True):
                    vectors[index] = vector
                api_latencies.extend(result.request_latencies_ms)
                api_batches.extend(result.batch_sizes)
                api_requests += result.request_count
                api_failures += result.failed_request_count
        finally:
            if created_provider:
                await active_provider.close()
        if any(vector is None for vector in vectors):
            raise RuntimeError("Some texts still have no embedding")
        metrics = {
            "cache_hits": len(texts) - len(missing_indices),
            "api_generated": len(missing_indices),
            "api_request_count": api_requests,
            "api_failed_attempt_count": api_failures,
            "api_failure_rate": api_failures / max(1, api_requests + api_failures),
            "embedding_api_avg_latency_ms": float(np.mean(api_latencies)) if api_latencies else None,
            "embedding_api_p50_latency_ms": float(np.percentile(api_latencies, 50)) if api_latencies else None,
            "embedding_api_p95_latency_ms": float(np.percentile(api_latencies, 95)) if api_latencies else None,
            "average_batch_size": float(np.mean(api_batches)) if api_batches else None,
            **config.identity(),
        }
        return np.vstack([vector for vector in vectors if vector is not None]), metrics
    finally:
        cache.close()


def create_embeddings(
    texts: Sequence[str], *, config: EmbeddingConfig, cache_path: Path,
    provider: EmbeddingProvider | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    return asyncio.run(load_or_create_remote_embeddings(
        texts, config=config, cache_path=cache_path, provider=provider,
    ))
