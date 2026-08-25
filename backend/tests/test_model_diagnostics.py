import unittest

import httpx

from app.config import Settings
from app.services.model_diagnostics import ModelDiagnosticsService


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        REPORT_USE_LLM=True,
        LLM_API_KEY="ark-test-key",
        LLM_BASE_URL="https://ark.example/api/v3",
        LLM_MODEL="doubao-test",
        QWEN_EMBEDDING_API_KEY="qwen-test-key",
        QWEN_EMBEDDING_BASE_URL="https://workspace.example/compatible-mode/v1",
        QWEN_EMBEDDING_MODEL="qwen3.7-text-embedding",
        QWEN_EMBEDDING_DIMENSIONS=1024,
        ASR_PROVIDER="volcengine",
        ASR_PUBLIC_BASE_URL="https://assessment.example",
        ASR_AUDIO_SIGNING_SECRET="s" * 64,
        VOLCENGINE_ASR_API_KEY="speech-test-key",
        VOLCENGINE_ASR_AUTH_MODE="api_key",
        VOLCENGINE_ASR_RESOURCE_ID="volc.seedasr.auc",
        VOLCENGINE_ASR_SUBMIT_URL="https://speech.example/submit",
        VOLCENGINE_ASR_QUERY_URL="https://speech.example/query",
    )


class ModelDiagnosticsTest(unittest.IsolatedAsyncioTestCase):
    async def test_active_diagnostics_check_all_four_services(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/chat/completions"):
                self.assertEqual(
                    request.headers["Authorization"],
                    "Bearer ark-test-key",
                )
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {"message": {"role": "assistant", "content": "好"}}
                        ]
                    },
                )
            if request.url.path.endswith("/embeddings"):
                self.assertEqual(request.headers["Authorization"], "Bearer qwen-test-key")
                return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 1024}]})
            if request.method == "GET" and request.url.path.endswith(
                "/diagnostic-audio"
            ):
                self.assertIn("signature", request.url.params)
                return httpx.Response(
                    200,
                    headers={"Content-Type": "audio/wav"},
                    content=b"RIFF-diagnostic",
                )
            if request.url.path.endswith("/submit"):
                self.assertEqual(
                    request.headers["X-Api-Key"],
                    "speech-test-key",
                )
                return httpx.Response(
                    200,
                    headers={"X-Api-Status-Code": "20000001"},
                    json={},
                )
            if request.url.path.endswith("/query"):
                return httpx.Response(
                    200,
                    headers={
                        "X-Api-Status-Code": "20000003",
                        "X-Api-Message": "silence",
                    },
                    json={},
                )
            return httpx.Response(404)

        async def no_sleep(_: float) -> None:
            return None

        service = ModelDiagnosticsService(
            _settings(),
            transport=httpx.MockTransport(handler),
            sleep=no_sleep,
        )
        llm, embedding, asr, audio = await service.run()

        self.assertEqual(llm.status, "ready")
        self.assertEqual(embedding.status, "ready")
        self.assertEqual(asr.status, "ready")
        self.assertEqual(audio.status, "ready")
        self.assertNotIn("test-key", llm.message)
        self.assertNotIn("test-key", asr.message)

    async def test_placeholders_are_reported_without_network_calls(self):
        called = False

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(500)

        settings = _settings()
        settings.LLM_API_KEY = "CHANGE_ME_KEY"
        settings.QWEN_EMBEDDING_API_KEY = "CHANGE_ME_KEY"
        settings.VOLCENGINE_ASR_API_KEY = "CHANGE_ME_KEY"
        settings.ASR_AUDIO_SIGNING_SECRET = "CHANGE_ME_SECRET"
        service = ModelDiagnosticsService(
            settings,
            transport=httpx.MockTransport(handler),
        )
        llm, embedding, asr, audio = await service.run()

        self.assertEqual(llm.status, "unconfigured")
        self.assertEqual(embedding.status, "unconfigured")
        self.assertEqual(asr.status, "unconfigured")
        self.assertEqual(audio.status, "unconfigured")
        self.assertFalse(called)

    async def test_volcengine_embedding_missing_endpoint_has_actionable_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertTrue(request.url.path.endswith("/embeddings"))
            return httpx.Response(
                404,
                json={
                    "error": {
                        "message": (
                            "The model or endpoint doubao-embedding-text-240715 "
                            "does not exist or you do not have access to it."
                        )
                    }
                },
            )

        settings = _settings()
        settings.QWEN_EMBEDDING_BASE_URL = (
            "https://ark.cn-beijing.volces.com/api/v3"
        )
        settings.QWEN_EMBEDDING_MODEL = "doubao-embedding-text-240715"
        service = ModelDiagnosticsService(
            settings,
            transport=httpx.MockTransport(handler),
        )

        result = await service.check_embedding()

        self.assertEqual(result.status, "error")
        self.assertEqual(result.label, "火山方舟文本向量")
        self.assertEqual(result.provider, "volcengine_ark_embedding")
        self.assertIn("Model ID", result.message)
        self.assertIn("ep-", result.message)
        self.assertIn("同一账号空间", result.message)
        self.assertNotIn("qwen-test-key", result.message)

    async def test_resource_not_granted_has_actionable_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/submit"):
                return httpx.Response(
                    200,
                    headers={
                        "X-Api-Status-Code": "45000030",
                        "X-Api-Message": (
                            "[resource_id=volc.seedasr.auc] "
                            "requested resource not granted"
                        ),
                    },
                    json={},
                )
            return httpx.Response(200, json={})

        service = ModelDiagnosticsService(
            _settings(),
            transport=httpx.MockTransport(handler),
        )
        result = await service.check_asr()

        self.assertEqual(result.status, "error")
        self.assertIn("API Key", result.message)
        self.assertIn("同一火山项目", result.message)
        self.assertNotIn("speech-test-key", result.message)

    async def test_audio_download_failure_explains_public_url_mismatch(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/submit"):
                return httpx.Response(
                    200,
                    headers={
                        "X-Api-Status-Code": "45000006",
                        "X-Api-Message": (
                            "[Invalid audio URI] audio download failed"
                        ),
                    },
                    json={},
                )
            return httpx.Response(200, json={})

        service = ModelDiagnosticsService(
            _settings(),
            transport=httpx.MockTransport(handler),
        )
        result = await service.check_asr()

        self.assertEqual(result.status, "error")
        self.assertIn("API Key 与资源授权已通过", result.message)
        self.assertIn("音频公网地址", result.message)
        self.assertNotIn("speech-test-key", result.message)
