from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

import httpx
import numpy as np

from app.services.embedding_provider import (
    EmbeddingConfig,
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    RemoteEmbeddingProvider,
    assert_embedding_identity,
    embedding_cache_key,
)
from app.services.model_inference import apply_tfidf_fallback, mark_pending_classification


def config(**updates) -> EmbeddingConfig:
    values = {
        "provider": "mock", "model": "embed-v1", "version": "2026-1",
        "dimensions": 3, "base_url": "https://embedding.example/v1",
        "api_key": "secret", "normalized": True, "batch_size": 2,
        "timeout_seconds": 5, "max_retries": 2,
    }
    values.update(updates)
    return EmbeddingConfig(**values)


def response(request: httpx.Request, count: int, dimensions: int = 3) -> httpx.Response:
    payload = json.loads(request.content)
    return httpx.Response(200, request=request, json={
        "data": [
            {"index": index, "embedding": [float(index + 1)] * dimensions}
            for index in range(count)
        ]
    })


class EmbeddingProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_provider_batches_and_preserves_order(self):
        batches = []
        async def handler(request):
            payload = json.loads(request.content)
            batches.append(payload["input"])
            self.assertEqual(set(payload), {"model", "input", "dimensions", "encoding_format"})
            return response(request, len(payload["input"]))
        provider = RemoteEmbeddingProvider(config(), transport=httpx.MockTransport(handler))
        result = await provider.embed(["一", "二", "三"])
        await provider.close()
        self.assertEqual(result.vectors.shape, (3, 3))
        self.assertEqual([len(item) for item in batches], [2, 1])

    async def test_timeout_is_retried(self):
        calls = 0
        sleeps = []
        async def handler(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ReadTimeout("timeout", request=request)
            return response(request, 1)
        async def no_sleep(delay):
            sleeps.append(delay)
        provider = RemoteEmbeddingProvider(
            config(), transport=httpx.MockTransport(handler), sleep=no_sleep,
        )
        result = await provider.embed(["重试"])
        await provider.close()
        self.assertEqual(result.failed_request_count, 1)
        self.assertEqual(calls, 2)
        self.assertEqual(sleeps, [1])

    async def test_timeout_exhaustion_is_visible(self):
        async def handler(request):
            raise httpx.ReadTimeout("timeout", request=request)
        async def no_sleep(_):
            return None
        provider = RemoteEmbeddingProvider(
            config(max_retries=1), transport=httpx.MockTransport(handler), sleep=no_sleep,
        )
        with self.assertRaises(EmbeddingProviderError):
            await provider.embed(["失败"])
        await provider.close()

    async def test_dimension_mismatch_is_rejected(self):
        async def handler(request):
            return response(request, 1, dimensions=2)
        provider = RemoteEmbeddingProvider(config(), transport=httpx.MockTransport(handler))
        with self.assertRaisesRegex(EmbeddingProviderError, "维度"):
            await provider.embed(["维度"])
        await provider.close()

    async def test_empty_text_is_rejected_without_api_call(self):
        called = False
        async def handler(request):
            nonlocal called
            called = True
            return response(request, 1)
        provider = RemoteEmbeddingProvider(config(), transport=httpx.MockTransport(handler))
        with self.assertRaises(ValueError):
            await provider.embed([""])
        await provider.close()
        self.assertFalse(called)


class EmbeddingContractTests(unittest.TestCase):
    def test_cache_invalidates_when_model_changes(self):
        self.assertNotEqual(
            embedding_cache_key(config(model="v1"), "同一文本"),
            embedding_cache_key(config(model="v2"), "同一文本"),
        )

    def test_cache_invalidates_when_instruction_changes(self):
        self.assertNotEqual(
            embedding_cache_key(config(instruction=None), "同一文本"),
            embedding_cache_key(config(instruction="query: "), "同一文本"),
        )

    def test_runtime_config_mismatch_refuses_inference(self):
        expected = config().identity()
        with self.assertRaises(EmbeddingConfigurationError):
            assert_embedding_identity(expected, config(model="changed"))

    def test_failed_embedding_marks_pending_without_losing_text(self):
        candidate = SimpleNamespace(
            clean_text="必须保留", classification_status="", prediction_source="x",
            classification_error="",
        )
        mark_pending_classification([candidate], RuntimeError("remote unavailable"))
        self.assertEqual(candidate.clean_text, "必须保留")
        self.assertEqual(candidate.classification_status, "pending_classification")

    def test_tfidf_fallback_marks_prediction_source(self):
        class Fallback:
            def predict(self, texts):
                return np.asarray(["monitoring"] * len(texts))
        candidate = SimpleNamespace(clean_text="保留文本")
        active = SimpleNamespace(id="job", version="v1")
        apply_tfidf_fallback([candidate], [candidate.clean_text], Fallback(), active, RuntimeError("api"))
        self.assertEqual(candidate.clean_text, "保留文本")
        self.assertEqual(candidate.prediction_source, "tfidf_fallback")
        self.assertEqual(candidate.predicted_label, 1)


if __name__ == "__main__":
    unittest.main()
