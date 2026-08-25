"""LLM adapter that extracts evidence candidates without assigning labels."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.services.metacognition_extractor.schemas import (
    ExtractionEnvelope,
    ProposedCandidate,
    SourceSegment,
)


class ExtractionProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    candidates: list[ProposedCandidate]
    raw_response: dict


def _unwrap_json(content: str) -> str:
    normalized = content.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3:
            normalized = "\n".join(lines[1:-1]).strip()
    return normalized


def _comparable(value: str) -> str:
    return re.sub(r"[\s，。！？、,.!?；;：:\"'“”‘’（）()\[\]【】]", "", value)


def is_conservative_derivation(original: str, cleaned: str) -> bool:
    """Reject rewrites: cleaned text must remain an ordered subsequence of the quote."""
    source = _comparable(original)
    target = _comparable(cleaned)
    if not source or not target:
        return False
    iterator = iter(source)
    return all(any(char == source_char for source_char in iterator) for char in target)


class MetacognitiveExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def extract(
        self,
        segments: list[SourceSegment],
        prompt_template: str,
    ) -> ExtractionResult:
        segment_payload = [item.model_dump() for item in segments]
        prompt = prompt_template.replace(
            "{segments}", json.dumps(segment_payload, ensure_ascii=False)
        )
        headers = {
            "Authorization": f"Bearer {self.settings.LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        attempts = self.settings.METACOGNITIVE_EXTRACTION_MAX_RETRIES + 1
        for attempt in range(attempts):
            try:
                timeout = httpx.Timeout(
                    self.settings.METACOGNITIVE_EXTRACTION_TIMEOUT_SECONDS
                )
                async with httpx.AsyncClient(
                    base_url=self.settings.LLM_BASE_URL.rstrip("/"),
                    headers=headers,
                    timeout=timeout,
                ) as client:
                    response = await client.post(
                        "/chat/completions",
                        json={
                            "model": self.settings.LLM_MODEL,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": (
                                        "你只做高召回候选片段抽取，不做元认知维度判断、"
                                        "评分或诊断。仅返回满足约定结构的 JSON。"
                                    ),
                                },
                                {"role": "user", "content": prompt},
                            ],
                            "temperature": 0,
                            "top_p": 1,
                            "max_tokens": min(self.settings.LLM_MAX_TOKENS, 3000),
                            "response_format": {"type": "json_object"},
                        },
                    )
                if response.status_code >= 500 or response.status_code == 429:
                    raise ExtractionProviderError(
                        f"llm_http_{response.status_code}",
                        f"候选抽取模型暂时不可用（HTTP {response.status_code}）",
                        retryable=True,
                    )
                if response.status_code >= 400:
                    raise ExtractionProviderError(
                        f"llm_http_{response.status_code}",
                        response.text[:1000],
                        retryable=False,
                    )
                payload = response.json()
                content = str(payload["choices"][0]["message"]["content"])
                envelope = ExtractionEnvelope.model_validate_json(_unwrap_json(content))
                validated = self._validate_evidence(envelope.candidates, segments)
                return ExtractionResult(
                    candidates=validated,
                    raw_response={"provider_payload": payload, "content": content},
                )
            except ExtractionProviderError as error:
                last_error = error
                if not error.retryable or attempt + 1 >= attempts:
                    raise
            except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as error:
                last_error = error
                if attempt + 1 >= attempts:
                    raise ExtractionProviderError(
                        "invalid_llm_response",
                        f"候选抽取响应无法通过结构校验：{error}",
                        retryable=False,
                    ) from error
            await asyncio.sleep(min(4, 2 ** attempt))
        raise ExtractionProviderError(
            "extraction_failed", str(last_error or "unknown error"), retryable=False
        )

    @staticmethod
    def _validate_evidence(
        candidates: list[ProposedCandidate], segments: list[SourceSegment]
    ) -> list[ProposedCandidate]:
        sources = {item.segment_id: item.text for item in segments}
        output: list[ProposedCandidate] = []
        seen: set[tuple[str, str]] = set()
        for item in candidates:
            source = sources.get(item.segment_id)
            quote = item.original_text.strip()
            cleaned = item.clean_text.strip()
            key = (item.segment_id, quote)
            if (
                source is None
                or quote not in source
                or not is_conservative_derivation(quote, cleaned)
                or key in seen
            ):
                continue
            seen.add(key)
            output.append(ProposedCandidate(
                segment_id=item.segment_id,
                original_text=quote,
                clean_text=cleaned,
            ))
        return output
