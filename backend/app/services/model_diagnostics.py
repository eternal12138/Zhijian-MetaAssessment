"""Active diagnostics for Volcengine Ark LLM and Doubao Speech ASR."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
import uuid
from typing import Any

import httpx

from app.config import Settings
from app.schemas.diagnostics import ServiceDiagnosticOut
from app.services.asr_provider import describe_volcengine_error
from app.services.asr_signing import build_signed_diagnostic_audio_url


def _configured(value: str) -> bool:
    normalized = value.strip()
    return bool(normalized and not normalized.startswith("CHANGE_ME"))


def _response_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or f"HTTP {response.status_code}")[:300]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:300]
        if payload.get("message"):
            return str(payload["message"])[:300]
    return f"HTTP {response.status_code}"


def _embedding_service_meta(endpoint: str) -> tuple[str, str]:
    normalized = endpoint.lower()
    if "volces.com" in normalized or "volcengine" in normalized:
        return "火山方舟文本向量", "volcengine_ark_embedding"
    if any(marker in normalized for marker in ("aliyuncs.com", "dashscope", "aliyun")):
        return "阿里云百炼文本向量", "aliyun_model_studio"
    return "远程文本向量服务", "openai_compatible_embedding"


def _embedding_error_message(response: httpx.Response, provider: str) -> str:
    raw_message = _response_message(response)
    normalized = raw_message.lower()
    if provider == "volcengine_ark_embedding" and (
        "does not exist" in normalized
        or "do not have access" in normalized
        or "not found" in normalized
        or "permission" in normalized
    ):
        return (
            f"文本向量调用失败：{raw_message}。请在火山方舟控制台确认已开通文本向量模型，"
            "填写控制台调用指南给出的 Model ID，或填写已创建的 Endpoint ID（通常以 ep- 开头）；"
            "同时确认 API Key、模型/接入点和地域属于同一账号空间。"
        )
    return f"文本向量调用失败：{raw_message}"


class ModelDiagnosticsService:
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

    async def run(
        self,
    ) -> tuple[
        ServiceDiagnosticOut,
        ServiceDiagnosticOut,
        ServiceDiagnosticOut,
        ServiceDiagnosticOut,
    ]:
        llm, embedding, asr, audio = await asyncio.gather(
            self.check_llm(),
            self.check_embedding(),
            self.check_asr(),
            self.check_public_audio(),
        )
        return llm, embedding, asr, audio

    async def check_embedding(self) -> ServiceDiagnosticOut:
        endpoint = (
            self.settings.EMBEDDING_API_BASE
            or self.settings.QWEN_EMBEDDING_BASE_URL
        ).rstrip("/")
        model = (
            self.settings.EMBEDDING_MODEL
            or self.settings.QWEN_EMBEDDING_MODEL
        ).strip()
        api_key = (
            self.settings.EMBEDDING_API_KEY
            or self.settings.QWEN_EMBEDDING_API_KEY
        )
        dimensions = (
            self.settings.EMBEDDING_DIMENSION
            if self.settings.EMBEDDING_MODEL
            else self.settings.QWEN_EMBEDDING_DIMENSIONS
        )
        timeout_seconds = (
            self.settings.EMBEDDING_TIMEOUT
            if self.settings.EMBEDDING_API_BASE
            else self.settings.QWEN_EMBEDDING_TIMEOUT_SECONDS
        )
        label, provider = _embedding_service_meta(endpoint)
        if not (_configured(api_key) and endpoint.startswith("https://") and model):
            return ServiceDiagnosticOut(
                status="unconfigured", configured=False, label=label,
                provider=provider, endpoint=endpoint or None,
                model=model or None,
                message="请配置文本向量服务的 API Key、HTTPS 接口地址以及模型名称或推理接入点 ID",
            )
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=min(timeout_seconds, 20), transport=self.transport) as client:
                response = await client.post(
                    f"{endpoint}/embeddings",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "input": ["文本向量服务连通性测试"], "dimensions": dimensions},
                )
            latency = round((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                return ServiceDiagnosticOut(
                    status="error", configured=True, label=label, provider=provider,
                    endpoint=endpoint, model=model, latency_ms=latency,
                    message=_embedding_error_message(response, provider),
                )
            payload = response.json()
            vector = (payload.get("data") or [{}])[0].get("embedding", [])
            if len(vector) != dimensions:
                return ServiceDiagnosticOut(
                    status="error", configured=True, label=label, provider=provider,
                    endpoint=endpoint, model=model, latency_ms=latency,
                    message=f"接口已响应，但返回 {len(vector)} 维向量，与当前配置的 {dimensions} 维不一致",
                )
            return ServiceDiagnosticOut(
                status="ready", configured=True, label=label, provider=provider,
                endpoint=endpoint, model=model, latency_ms=latency,
                message=f"文本向量服务可用，测试文本已成功转换为 {len(vector)} 维向量",
            )
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
            return ServiceDiagnosticOut(
                status="error", configured=True, label=label, provider=provider,
                endpoint=endpoint, model=model,
                latency_ms=round((time.perf_counter() - started) * 1000),
                message=f"文本向量服务连接失败：{str(error)[:200]}",
            )

    async def check_llm(self) -> ServiceDiagnosticOut:
        endpoint = self.settings.LLM_BASE_URL.rstrip("/")
        if not self.settings.REPORT_USE_LLM:
            return ServiceDiagnosticOut(
                status="disabled",
                configured=False,
                label="火山方舟大语言模型",
                provider="volcengine_ark",
                endpoint=endpoint or None,
                model=self.settings.LLM_MODEL or None,
                message="REPORT_USE_LLM=false，事后大模型分析已关闭",
            )
        if not all((
            _configured(self.settings.LLM_API_KEY),
            endpoint.startswith("https://"),
            _configured(self.settings.LLM_MODEL),
        )):
            return ServiceDiagnosticOut(
                status="unconfigured",
                configured=False,
                label="火山方舟大语言模型",
                provider="volcengine_ark",
                endpoint=endpoint or None,
                model=self.settings.LLM_MODEL or None,
                message="请配置方舟 API Key、HTTPS Base URL 和模型/接入点 ID",
            )

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=min(self.settings.REPORT_LLM_TIMEOUT_SECONDS, 20),
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{endpoint}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.LLM_MODEL,
                        "messages": [
                            {
                                "role": "user",
                                "content": "这是服务可用性测试，请只回复“好”。",
                            }
                        ],
                        "temperature": 0,
                        "max_tokens": 1,
                    },
                )
            latency = round((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                return ServiceDiagnosticOut(
                    status="error",
                    configured=True,
                    label="火山方舟大语言模型",
                    provider="volcengine_ark",
                    endpoint=endpoint,
                    model=self.settings.LLM_MODEL,
                    latency_ms=latency,
                    message=f"模型调用失败：{_response_message(response)}",
                )
            return ServiceDiagnosticOut(
                status="ready",
                configured=True,
                label="火山方舟大语言模型",
                provider="volcengine_ark",
                endpoint=endpoint,
                model=self.settings.LLM_MODEL,
                latency_ms=latency,
                message="API Key、模型 ID 与 Chat API 调用正常",
            )
        except httpx.HTTPError as error:
            return ServiceDiagnosticOut(
                status="error",
                configured=True,
                label="火山方舟大语言模型",
                provider="volcengine_ark",
                endpoint=endpoint,
                model=self.settings.LLM_MODEL,
                latency_ms=round((time.perf_counter() - started) * 1000),
                message=f"网络连接失败：{str(error)[:200]}",
            )

    def _asr_headers(self, request_id: str) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Api-Resource-Id": self.settings.VOLCENGINE_ASR_RESOURCE_ID,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }
        auth_mode = self.settings.VOLCENGINE_ASR_AUTH_MODE.strip().lower()
        use_api_key = auth_mode == "api_key" or (
            auth_mode not in {"api_key", "legacy"}
            and _configured(self.settings.VOLCENGINE_ASR_API_KEY)
        )
        if use_api_key:
            headers["X-Api-Key"] = self.settings.VOLCENGINE_ASR_API_KEY.strip()
        else:
            headers["X-Api-App-Key"] = self.settings.VOLCENGINE_ASR_APP_ID.strip()
            headers["X-Api-Access-Key"] = (
                self.settings.VOLCENGINE_ASR_ACCESS_KEY.strip()
            )
        return headers

    def _asr_is_configured(self) -> bool:
        auth_mode = self.settings.VOLCENGINE_ASR_AUTH_MODE.strip().lower()
        api_key_ready = _configured(self.settings.VOLCENGINE_ASR_API_KEY)
        legacy_ready = (
            _configured(self.settings.VOLCENGINE_ASR_APP_ID)
            and _configured(self.settings.VOLCENGINE_ASR_ACCESS_KEY)
        )
        credential_ready = (
            api_key_ready
            if auth_mode == "api_key"
            else legacy_ready
            if auth_mode == "legacy"
            else api_key_ready or legacy_ready
        )
        return bool(
            self.settings.ASR_PROVIDER.strip().lower() == "volcengine"
            and credential_ready
            and _configured(self.settings.VOLCENGINE_ASR_RESOURCE_ID)
            and self.settings.VOLCENGINE_ASR_SUBMIT_URL.startswith("https://")
            and self.settings.VOLCENGINE_ASR_QUERY_URL.startswith("https://")
            and self.settings.ASR_PUBLIC_BASE_URL.startswith("https://")
            and _configured(self.settings.ASR_AUDIO_SIGNING_SECRET)
        )

    async def check_asr(self) -> ServiceDiagnosticOut:
        endpoint = self.settings.VOLCENGINE_ASR_SUBMIT_URL
        if not self._asr_is_configured():
            return ServiceDiagnosticOut(
                status="unconfigured",
                configured=False,
                label="豆包录音文件识别",
                provider="volcengine_speech",
                endpoint=endpoint or None,
                model=self.settings.VOLCENGINE_ASR_RESOURCE_ID or None,
                message="请检查 ASR Provider、语音 API Key、资源 ID、公网地址和签名密钥",
            )

        request_id = str(uuid.uuid4())
        headers = self._asr_headers(request_id)
        audio_payload: dict[str, Any] = {
            "url": build_signed_diagnostic_audio_url(self.settings),
            "format": "wav",
            "codec": "raw",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
        }
        language_aliases = {"zh": "zh-CN", "en": "en-US", "auto": ""}
        language = language_aliases.get(
            self.settings.ASR_LANGUAGE.strip(),
            self.settings.ASR_LANGUAGE.strip(),
        )
        if language:
            audio_payload["language"] = language

        payload: dict[str, Any] = {
            "user": {
                "uid": self.settings.VOLCENGINE_ASR_APP_ID.strip() or "diagnostic",
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
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=min(self.settings.ASR_TIMEOUT_SECONDS, 20),
                transport=self.transport,
            ) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                )
                if response.status_code >= 400:
                    return self._asr_failure(response, started)
                status_code = response.headers.get("X-Api-Status-Code", "")
                if status_code not in {"20000000", "20000001", "20000002"}:
                    return self._asr_failure(response, started)

                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    queried = await client.post(
                        self.settings.VOLCENGINE_ASR_QUERY_URL,
                        headers=headers,
                        json={},
                    )
                    if queried.status_code >= 400:
                        return self._asr_failure(queried, started)
                    query_code = queried.headers.get("X-Api-Status-Code", "")
                    if query_code in {"20000000", "20000003"}:
                        return ServiceDiagnosticOut(
                            status="ready",
                            configured=True,
                            label="豆包录音文件识别",
                            provider="volcengine_speech",
                            endpoint=endpoint,
                            model=self.settings.VOLCENGINE_ASR_RESOURCE_ID,
                            latency_ms=round(
                                (time.perf_counter() - started) * 1000
                            ),
                            message="API Key、资源授权、任务轮询和音频拉取均正常",
                        )
                    if query_code not in {"20000001", "20000002"}:
                        return self._asr_failure(queried, started)
                    await self.sleep(2)
            return ServiceDiagnosticOut(
                status="warning",
                configured=True,
                label="豆包录音文件识别",
                provider="volcengine_speech",
                endpoint=endpoint,
                model=self.settings.VOLCENGINE_ASR_RESOURCE_ID,
                latency_ms=round((time.perf_counter() - started) * 1000),
                message="探针任务已提交，但30秒内仍未完成，请稍后重试",
            )
        except httpx.HTTPError as error:
            return ServiceDiagnosticOut(
                status="error",
                configured=True,
                label="豆包录音文件识别",
                provider="volcengine_speech",
                endpoint=endpoint,
                model=self.settings.VOLCENGINE_ASR_RESOURCE_ID,
                latency_ms=round((time.perf_counter() - started) * 1000),
                message=f"网络连接失败：{str(error)[:200]}",
            )

    def _asr_failure(
        self,
        response: httpx.Response,
        started: float,
    ) -> ServiceDiagnosticOut:
        code = response.headers.get("X-Api-Status-Code") or response.status_code
        raw_message = (
            response.headers.get("X-Api-Message")
            or _response_message(response)
        )
        message = describe_volcengine_error(
            str(code),
            raw_message,
            self.settings.VOLCENGINE_ASR_RESOURCE_ID,
        )
        return ServiceDiagnosticOut(
            status="error",
            configured=True,
            label="豆包录音文件识别",
            provider="volcengine_speech",
            endpoint=self.settings.VOLCENGINE_ASR_SUBMIT_URL,
            model=self.settings.VOLCENGINE_ASR_RESOURCE_ID,
            latency_ms=round((time.perf_counter() - started) * 1000),
            message=f"语音探针失败（{code}）：{message[:250]}",
        )

    async def check_public_audio(self) -> ServiceDiagnosticOut:
        endpoint = self.settings.ASR_PUBLIC_BASE_URL.rstrip("/")
        if not (
            endpoint.startswith("https://")
            and _configured(self.settings.ASR_AUDIO_SIGNING_SECRET)
        ):
            return ServiceDiagnosticOut(
                status="unconfigured",
                configured=False,
                label="ASR 音频公网地址",
                provider="signed_https",
                endpoint=endpoint or None,
                message="请配置 HTTPS 公网地址和独立音频签名密钥",
            )
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = await client.get(
                    build_signed_diagnostic_audio_url(self.settings)
                )
            latency = round((time.perf_counter() - started) * 1000)
            content_type = response.headers.get("content-type", "")
            if response.status_code == 200 and "audio/wav" in content_type:
                return ServiceDiagnosticOut(
                    status="ready",
                    configured=True,
                    label="ASR 音频公网地址",
                    provider="signed_https",
                    endpoint=endpoint,
                    latency_ms=latency,
                    message="公网 HTTPS、签名校验和 WAV 下载正常",
                )
            return ServiceDiagnosticOut(
                status="error",
                configured=True,
                label="ASR 音频公网地址",
                provider="signed_https",
                endpoint=endpoint,
                latency_ms=latency,
                message=f"公网探针返回 HTTP {response.status_code}，请检查域名、代理和缓存规则",
            )
        except httpx.HTTPError as error:
            return ServiceDiagnosticOut(
                status="error",
                configured=True,
                label="ASR 音频公网地址",
                provider="signed_https",
                endpoint=endpoint,
                latency_ms=round((time.perf_counter() - started) * 1000),
                message=f"公网地址无法访问：{str(error)[:200]}",
            )
