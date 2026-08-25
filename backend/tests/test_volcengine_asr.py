import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx

from app.config import Settings
from app.services.asr_provider import AsrProviderError, VolcengineAsrProvider
from app.services.asr_signing import (
    build_signed_audio_url,
    sign_audio_download,
    verify_audio_download,
)


def _settings(**overrides) -> Settings:
    values = {
        "ASR_PROVIDER": "volcengine",
        "ASR_MODEL": "volc.seedasr.auc",
        "ASR_LANGUAGE": "zh-CN",
        "ASR_PUBLIC_BASE_URL": "https://assessment.example",
        "ASR_AUDIO_SIGNING_SECRET": "s" * 64,
        "VOLCENGINE_ASR_API_KEY": "test-api-key",
        "VOLCENGINE_ASR_RESOURCE_ID": "volc.seedasr.auc",
        "VOLCENGINE_ASR_QUERY_INTERVAL_SECONDS": 0,
        "VOLCENGINE_ASR_MAX_WAIT_SECONDS": 10,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class AudioSigningTest(unittest.TestCase):
    def test_signature_is_job_bound_and_expires(self):
        secret = "a" * 64
        signature = sign_audio_download("job-1", 1200, secret)
        self.assertTrue(
            verify_audio_download(
                "job-1", 1200, signature, secret, now=1100
            )
        )
        self.assertFalse(
            verify_audio_download(
                "job-2", 1200, signature, secret, now=1100
            )
        )
        self.assertFalse(
            verify_audio_download(
                "job-1", 1200, signature, secret, now=1201
            )
        )

    def test_signed_url_uses_public_https_origin(self):
        url = build_signed_audio_url("job-1", _settings(), now=1000)
        self.assertTrue(
            url.startswith(
                "https://assessment.example/api/asr-provider/audio/job-1?"
            )
        )
        self.assertIn("expires=1600", url)
        self.assertIn("signature=", url)


class VolcengineProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_provider_error_preserves_real_volcengine_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(
                200,
                headers={
                    "X-Api-Status-Code": "45000030",
                    "X-Api-Message": "requested resource not granted",
                },
                json={},
            )

        with TemporaryDirectory() as directory:
            audio = Path(directory) / "recording.wav"
            audio.write_bytes(b"RIFF-test")
            provider = VolcengineAsrProvider(
                _settings(),
                transport=httpx.MockTransport(handler),
            )
            with self.assertRaises(AsrProviderError) as caught:
                await provider.transcribe(audio, job_id="job-error")

        self.assertEqual(caught.exception.code, "volcengine_45000030")
        self.assertIn("requested resource not granted", str(caught.exception))
        self.assertIn("volc.seedasr.auc", str(caught.exception))

    async def test_submit_poll_and_map_utterances(self):
        calls: list[httpx.Request] = []
        query_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal query_count
            calls.append(request)
            if request.url.path.endswith("/submit"):
                body = json.loads(request.content)
                self.assertEqual(
                    body["audio"]["url"].split("?")[0],
                    "https://assessment.example/api/asr-provider/audio/job-1",
                )
                self.assertFalse(body["request"]["enable_ddc"])
                self.assertTrue(body["request"]["show_utterances"])
                self.assertEqual(body["audio"]["language"], "zh-CN")
                self.assertEqual(
                    request.headers["X-Api-Resource-Id"],
                    "volc.seedasr.auc",
                )
                return httpx.Response(
                    200,
                    headers={
                        "X-Api-Status-Code": "20000001",
                        "X-Tt-Logid": "submit-log",
                    },
                    json={},
                )

            query_count += 1
            if query_count == 1:
                return httpx.Response(
                    200,
                    headers={"X-Api-Status-Code": "20000002"},
                    json={},
                )
            return httpx.Response(
                200,
                headers={
                    "X-Api-Status-Code": "20000000",
                    "X-Tt-Logid": "result-log",
                },
                json={
                    "audio_info": {"duration": 2499},
                    "result": {
                        "text": "先计算，再检查。",
                        "utterances": [
                            {
                                "start_time": 450,
                                "end_time": 2499,
                                "text": "先计算，再检查。",
                                "words": [
                                    {
                                        "start_time": 450,
                                        "end_time": 800,
                                        "text": "先",
                                        "confidence": 0.9,
                                    },
                                    {
                                        "start_time": 800,
                                        "end_time": 1200,
                                        "text": "计算",
                                        "confidence": 0.8,
                                    },
                                ],
                            }
                        ],
                    },
                },
            )

        async def no_sleep(_: float) -> None:
            return None

        with TemporaryDirectory() as directory:
            audio = Path(directory) / "recording.wav"
            audio.write_bytes(b"RIFF-test")
            provider = VolcengineAsrProvider(
                _settings(),
                transport=httpx.MockTransport(handler),
                sleep=no_sleep,
            )
            result = await provider.transcribe(audio, job_id="job-1")

        self.assertEqual(len(calls), 3)
        self.assertEqual(result.text, "先计算，再检查。")
        self.assertEqual(result.duration_ms, 2499)
        self.assertEqual(result.request_id, "result-log")
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.segments[0].started_at_ms, 450)
        self.assertEqual(result.segments[0].ended_at_ms, 2499)
        self.assertAlmostEqual(result.segments[0].confidence or 0, 0.85)

    async def test_auto_language_omits_audio_language(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/submit"):
                body = json.loads(request.content)
                self.assertNotIn("language", body["audio"])
                return httpx.Response(
                    200,
                    headers={"X-Api-Status-Code": "20000001"},
                    json={},
                )
            return httpx.Response(
                200,
                headers={"X-Api-Status-Code": "20000000"},
                json={"result": {"text": "测试"}},
            )

        async def no_sleep(_: float) -> None:
            return None

        with TemporaryDirectory() as directory:
            audio = Path(directory) / "recording.wav"
            audio.write_bytes(b"RIFF-test")
            provider = VolcengineAsrProvider(
                _settings(ASR_LANGUAGE=""),
                transport=httpx.MockTransport(handler),
                sleep=no_sleep,
            )
            result = await provider.transcribe(audio, job_id="job-auto")

        self.assertEqual(result.language, "auto")
