"""ASR provider abstraction with OpenAI-compatible and Volcengine support."""
from __future__ import annotations

import asyncio
import math
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.services.asr_signing import build_signed_audio_url


class AsrProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class AsrSegmentResult:
    text: str
    started_at_ms: int
    ended_at_ms: int
    confidence: float | None
    raw_data: dict | None = None


@dataclass(frozen=True)
class AsrResult:
    text: str
    language: str
    duration_ms: int | None
    segments: tuple[AsrSegmentResult, ...]
    request_id: str | None
    raw_response: dict


class AsrProvider(Protocol):
    async def transcribe(self, audio_path: Path, *, job_id: str) -> AsrResult:
        ...


def _confidence(raw: dict[str, Any]) -> float | None:
    explicit = raw.get("confidence")
    if isinstance(explicit, (int, float)):
        value = float(explicit)
        if value > 1 and value <= 100:
            value /= 100
        return max(0.0, min(1.0, value))
    avg_logprob = raw.get("avg_logprob")
    if isinstance(avg_logprob, (int, float)):
        return max(0.0, min(1.0, math.exp(float(avg_logprob))))
    return None


def _http_error(response: httpx.Response, prefix: str) -> AsrProviderError:
    retryable = (
        response.status_code in {408, 409, 425, 429}
        or response.status_code >= 500
    )
    message = response.text[:1500] or f"HTTP {response.status_code}"
    return AsrProviderError(
        f"{prefix}_http_{response.status_code}",
        message,
        retryable=retryable,
    )


def _volcengine_language(value: str) -> str:
    """Normalize legacy short codes to the v3 audio.language values."""
    normalized = value.strip()
    aliases = {
        "auto": "",
        "zh": "zh-CN",
        "en": "en-US",
        "ja": "ja-JP",
        "ko": "ko-KR",
    }
    return aliases.get(normalized, normalized)


def describe_volcengine_error(
    status_code: str,
    message: str,
    resource_id: str,
) -> str:
    """Turn common provider codes into actionable, secret-free guidance."""
    normalized_code = str(status_code).strip()
    normalized_message = message.strip()
    if (
        normalized_code == "45000030"
        or "requested resource not granted" in normalized_message.lower()
    ):
        return (
            f"{normalized_message}。资源 ID {resource_id} 的格式正确，但当前 API Key "
            "尚未获得该资源授权。请在开通“录音文件识别2.0”的同一火山项目中创建并启用 "
            "API Key；若刚完成开通或创建，请等待权限同步后重试。"
        )
    if (
        normalized_code == "45000006"
        or "invalid audio uri" in normalized_message.lower()
        or "audio download failed" in normalized_message.lower()
    ):
        return (
            f"{normalized_message}。API Key 与资源授权已通过，但火山引擎无法下载音频。"
            "本地调试时请把“音频公网地址”设置为当前本地穿透的 HTTPS 地址；"
            "服务器部署时请填写实际反向代理到本后端的 HTTPS 域名，并确认签名密钥"
            "来自同一运行环境。"
        )
    return normalized_message


class OpenAICompatibleAsrProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.settings = settings
        self.transport = transport

    async def transcribe(self, audio_path: Path, *, job_id: str) -> AsrResult:
        del job_id
        url = self.settings.ASR_BASE_URL.rstrip("/") + "/audio/transcriptions"
        headers = {}
        if self.settings.ASR_API_KEY:
            headers["Authorization"] = f"Bearer {self.settings.ASR_API_KEY}"
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.ASR_TIMEOUT_SECONDS,
                transport=self.transport,
            ) as client:
                with audio_path.open("rb") as stream:
                    response = await client.post(
                        url,
                        headers=headers,
                        files={"file": (audio_path.name, stream, "audio/wav")},
                        data={
                            "model": self.settings.ASR_MODEL,
                            "language": self.settings.ASR_LANGUAGE,
                            "response_format": "verbose_json",
                        },
                    )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise AsrProviderError(
                "asr_network_error", str(error), retryable=True
            ) from error
        except OSError as error:
            raise AsrProviderError("audio_file_unreadable", str(error)) from error

        if response.status_code >= 400:
            raise _http_error(response, "asr")
        payload = _json_object(response, "ASR 服务未返回有效 JSON")
        return _parse_openai_result(payload, response.headers)


class VolcengineAsrProvider:
    PENDING_CODES = {"20000001", "20000002"}
    SUCCESS_CODE = "20000000"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep=asyncio.sleep,
    ):
        self.settings = settings
        self.transport = transport
        self.sleep = sleep

    def _headers(self, request_id: str) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Api-Resource-Id": self.settings.VOLCENGINE_ASR_RESOURCE_ID,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }
        auth_mode = self.settings.VOLCENGINE_ASR_AUTH_MODE.strip().lower()
        use_api_key = auth_mode == "api_key" or (
            auth_mode not in {"api_key", "legacy"}
            and self.settings.VOLCENGINE_ASR_API_KEY.strip()
        )
        if use_api_key:
            headers["X-Api-Key"] = self.settings.VOLCENGINE_ASR_API_KEY.strip()
        else:
            headers["X-Api-App-Key"] = self.settings.VOLCENGINE_ASR_APP_ID.strip()
            headers["X-Api-Access-Key"] = (
                self.settings.VOLCENGINE_ASR_ACCESS_KEY.strip()
            )
        return headers

    async def transcribe(self, audio_path: Path, *, job_id: str) -> AsrResult:
        if not audio_path.is_file():
            raise AsrProviderError(
                "audio_file_unreadable",
                f"音频文件不存在：{audio_path.name}",
            )
        request_id = str(uuid.uuid4())
        headers = self._headers(request_id)
        audio_payload: dict[str, Any] = {
            "url": build_signed_audio_url(job_id, self.settings),
            "format": "wav",
            "codec": "raw",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
        }
        language = _volcengine_language(self.settings.ASR_LANGUAGE)
        if language:
            audio_payload["language"] = language

        payload = {
            "user": {
                "uid": self.settings.VOLCENGINE_ASR_APP_ID.strip() or job_id,
            },
            "audio": audio_payload,
            "request": {
                "model_name": "bigmodel",
                "enable_itn": False,
                "enable_punc": True,
                "enable_ddc": False,
                "show_utterances": True,
            },
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.ASR_TIMEOUT_SECONDS,
                transport=self.transport,
            ) as client:
                submitted = await client.post(
                    self.settings.VOLCENGINE_ASR_SUBMIT_URL,
                    headers=headers,
                    json=payload,
                )
                self._ensure_http_success(submitted)
                submit_code = submitted.headers.get("X-Api-Status-Code", "")
                if submit_code and submit_code not in {
                    self.SUCCESS_CODE,
                    *self.PENDING_CODES,
                }:
                    raise self._provider_error(submitted, submit_code)

                deadline = time.monotonic() + (
                    self.settings.VOLCENGINE_ASR_MAX_WAIT_SECONDS
                )
                while True:
                    queried = await client.post(
                        self.settings.VOLCENGINE_ASR_QUERY_URL,
                        headers=headers,
                        json={},
                    )
                    self._ensure_http_success(queried)
                    status_code = queried.headers.get("X-Api-Status-Code", "")
                    if status_code == self.SUCCESS_CODE:
                        result_payload = _json_object(
                            queried,
                            "火山引擎 ASR 未返回有效 JSON",
                        )
                        return _parse_volcengine_result(
                            result_payload,
                            queried.headers,
                            language or "auto",
                            request_id,
                        )
                    if status_code not in self.PENDING_CODES:
                        raise self._provider_error(queried, status_code)
                    if time.monotonic() >= deadline:
                        raise AsrProviderError(
                            "volcengine_timeout",
                            "火山引擎 ASR 任务等待超时",
                            retryable=True,
                        )
                    await self.sleep(
                        self.settings.VOLCENGINE_ASR_QUERY_INTERVAL_SECONDS
                    )
        except AsrProviderError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise AsrProviderError(
                "volcengine_network_error",
                str(error),
                retryable=True,
            ) from error

    @staticmethod
    def _ensure_http_success(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise _http_error(response, "volcengine")

    def _provider_error(
        self,
        response: httpx.Response,
        status_code: str,
    ) -> AsrProviderError:
        raw_message = (
            response.headers.get("X-Api-Message")
            or response.text[:1500]
            or f"火山引擎状态码 {status_code or 'missing'}"
        )
        message = describe_volcengine_error(
            status_code,
            raw_message,
            self.settings.VOLCENGINE_ASR_RESOURCE_ID,
        )
        retryable = status_code.startswith("55") or status_code in {
            "20000003",
            "20000004",
        }
        safe_code = status_code or "missing_status"
        return AsrProviderError(
            f"volcengine_{safe_code}",
            message,
            retryable=retryable,
        )


def _json_object(response: httpx.Response, message: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise AsrProviderError("invalid_asr_response", message) from error
    if not isinstance(payload, dict):
        raise AsrProviderError("invalid_asr_response", message)
    return payload


def _parse_openai_result(
    payload: dict[str, Any],
    headers: httpx.Headers,
) -> AsrResult:
    text = str(payload.get("text") or "").strip()
    language = str(payload.get("language") or "zh")
    duration = payload.get("duration")
    duration_ms = (
        round(float(duration) * 1000)
        if isinstance(duration, (int, float))
        else None
    )
    segments: list[AsrSegmentResult] = []
    raw_segments = payload.get("segments")
    if isinstance(raw_segments, list):
        for raw in raw_segments:
            if not isinstance(raw, dict):
                continue
            segment_text = str(raw.get("text") or "").strip()
            if not segment_text:
                continue
            start = max(0, round(float(raw.get("start") or 0) * 1000))
            end = max(start, round(float(raw.get("end") or 0) * 1000))
            segments.append(
                AsrSegmentResult(
                    text=segment_text,
                    started_at_ms=start,
                    ended_at_ms=end,
                    confidence=_confidence(raw),
                    raw_data=raw,
                )
            )
    if not segments and text:
        segments.append(
            AsrSegmentResult(
                text=text,
                started_at_ms=0,
                ended_at_ms=duration_ms or 0,
                confidence=None,
            )
        )
    if not text:
        text = "".join(item.text for item in segments).strip()
    return AsrResult(
        text=text,
        language=language,
        duration_ms=duration_ms,
        segments=tuple(segments),
        request_id=(
            headers.get("x-request-id")
            or str(payload.get("x_groq", {}).get("id") or "")
            or None
        ),
        raw_response=payload,
    )


def _parse_volcengine_result(
    payload: dict[str, Any],
    headers: httpx.Headers,
    language: str,
    request_id: str,
) -> AsrResult:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise AsrProviderError(
            "invalid_asr_response",
            "火山引擎 ASR 响应缺少 result",
        )
    text = str(result.get("text") or "").strip()
    audio_info = payload.get("audio_info")
    duration_ms: int | None = None
    if isinstance(audio_info, dict):
        duration = audio_info.get("duration")
        if isinstance(duration, (int, float)):
            duration_ms = max(0, round(float(duration)))

    segments: list[AsrSegmentResult] = []
    utterances = result.get("utterances")
    if isinstance(utterances, list):
        for raw in utterances:
            if not isinstance(raw, dict):
                continue
            segment_text = str(raw.get("text") or "").strip()
            if not segment_text:
                continue
            start = max(0, round(float(raw.get("start_time") or 0)))
            end = max(start, round(float(raw.get("end_time") or 0)))
            word_confidences = [
                confidence
                for word in raw.get("words", [])
                if isinstance(word, dict)
                for confidence in [_confidence(word)]
                if confidence is not None
            ]
            confidence = (
                sum(word_confidences) / len(word_confidences)
                if word_confidences
                else _confidence(raw)
            )
            segments.append(
                AsrSegmentResult(
                    text=segment_text,
                    started_at_ms=start,
                    ended_at_ms=end,
                    confidence=confidence,
                    raw_data=raw,
                )
            )
    if not segments and text:
        segments.append(
            AsrSegmentResult(
                text=text,
                started_at_ms=0,
                ended_at_ms=duration_ms or 0,
                confidence=None,
            )
        )
    if not text:
        text = "".join(item.text for item in segments).strip()
    if not text:
        raise AsrProviderError(
            "empty_asr_transcript",
            (
                "音频文件可以读取，但火山引擎未识别到可转写的人声。"
                "请先试听原始录音；若只有静音、环境噪声或没有清晰说话声，"
                "重复识别不会改善结果。"
            ),
        )
    return AsrResult(
        text=text,
        language=language,
        duration_ms=duration_ms,
        segments=tuple(segments),
        request_id=headers.get("X-Tt-Logid") or request_id,
        raw_response=payload,
    )


def get_asr_provider(settings: Settings) -> AsrProvider:
    provider = settings.ASR_PROVIDER.strip().lower()
    if provider == "disabled":
        raise AsrProviderError("provider_disabled", "服务端 ASR 当前未启用")
    if provider in {"openai_compatible", "whisper"}:
        if not settings.ASR_BASE_URL.strip():
            raise AsrProviderError(
                "provider_not_configured",
                "ASR_BASE_URL 尚未配置",
            )
        return OpenAICompatibleAsrProvider(settings)
    if provider == "volcengine":
        if not settings.asr_provider_ready:
            raise AsrProviderError(
                "provider_not_configured",
                "火山引擎 ASR 凭据、公开地址或音频签名密钥尚未配置",
            )
        return VolcengineAsrProvider(settings)
    raise AsrProviderError(
        "unsupported_provider",
        f"不支持的 ASR_PROVIDER：{provider}",
    )
