from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx
import numpy as np

from qwen_embedding_client import (
    EmbeddingCache,
    EmbeddingConfigurationError,
    QwenEmbeddingClient,
    QwenEmbeddingConfig,
    cache_key,
)


class QwenEmbeddingClientTest(unittest.TestCase):
    def config(self) -> QwenEmbeddingConfig:
        return QwenEmbeddingConfig(
            api_key="test-secret",
            base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            dimensions=256,
            batch_size=2,
            max_retries=0,
        )

    def test_rejects_placeholder_endpoint(self) -> None:
        config = QwenEmbeddingConfig(
            api_key="secret",
            base_url="https://CHANGE_ME_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        )
        with self.assertRaises(EmbeddingConfigurationError):
            config.validate()

    def test_parses_and_normalizes_openai_compatible_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/compatible-mode/v1/embeddings")
            self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": "request-1",
                    "data": [
                        {"index": 1, "embedding": [0.0, 3.0, 0.0, 4.0] + [0.0] * 252},
                        {"index": 0, "embedding": [1.0] + [0.0] * 255},
                    ],
                    "usage": {"total_tokens": 12},
                },
            )

        with QwenEmbeddingClient(self.config(), transport=httpx.MockTransport(handler)) as client:
            result = client.embed(["甲", "乙"])
        self.assertEqual(result.request_id, "request-1")
        self.assertEqual(result.total_tokens, 12)
        np.testing.assert_allclose(np.linalg.norm(result.vectors, axis=1), [1.0, 1.0])
        np.testing.assert_allclose(result.vectors[1][:4], [0.0, 0.6, 0.0, 0.8])

    def test_sqlite_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite3"
            key = cache_key("qwen3.7-text-embedding", 256, "测试文本")
            with EmbeddingCache(path) as cache:
                self.assertIsNone(cache.get(key, 256))
                vector = np.zeros((1, 256), dtype=np.float32)
                vector[0, :4] = [0.5, 0.5, 0.5, 0.5]
                cache.put_many(
                    keys=[key], texts=["测试文本"], model="qwen3.7-text-embedding",
                    dimensions=256, vectors=vector,
                    request_id="req", total_tokens=5,
                )
                restored = cache.get(key, 256)
            np.testing.assert_allclose(restored[:4], [0.5, 0.5, 0.5, 0.5])


if __name__ == "__main__":
    unittest.main()
