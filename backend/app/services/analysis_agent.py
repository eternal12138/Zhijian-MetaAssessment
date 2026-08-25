"""测评结束后的元认知分析智能体。"""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings


DIMENSIONS = ("monitoring", "controlDebugging", "evaluation")


@dataclass(frozen=True, slots=True)
class AnalysisSegment:
    segment_id: str
    text: str


@dataclass(frozen=True, slots=True)
class AnalysisCode:
    segment_id: str
    dimension: str
    score: int
    reason: str
    confidence: float


class AnalysisAgent:
    """只负责事后结构化编码，不生成测评过程中的主试回复。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def code_segments(
        self,
        segments: list[AnalysisSegment],
        prompt_template: str,
    ) -> list[AnalysisCode]:
        if not self.settings.REPORT_USE_LLM or not segments:
            return []

        limited_segments = segments[:20]
        payload = [
            {"segment_id": item.segment_id, "text": item.text[:600]}
            for item in limited_segments
        ]
        prompt = prompt_template.replace(
            "{segments}",
            json.dumps(payload, ensure_ascii=False),
        )
        headers = {
            "Authorization": f"Bearer {self.settings.LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.settings.REPORT_LLM_TIMEOUT_SECONDS)
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.LLM_BASE_URL,
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
                                "content": "你是事后元认知编码员。只返回严格 JSON，不输出思维链。",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": self.settings.LLM_TEMPERATURE,
                        "top_p": self.settings.LLM_TOP_P,
                        "max_tokens": min(self.settings.LLM_MAX_TOKENS, 1800),
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            return self.parse_codes(str(content), limited_segments)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return []

    @staticmethod
    def parse_codes(
        content: str,
        segments: list[AnalysisSegment],
    ) -> list[AnalysisCode]:
        normalized = content.strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            normalized = "\n".join(lines[1:-1])
        parsed = json.loads(normalized)
        if not isinstance(parsed, list):
            return []

        valid_ids = {item.segment_id for item in segments}
        results: list[AnalysisCode] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            segment_id = str(item.get("segment_id", ""))
            dimension = item.get("dimension")
            score = item.get("score")
            confidence = item.get("confidence")
            if segment_id not in valid_ids or dimension not in DIMENSIONS:
                continue
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 7:
                continue
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0 <= confidence <= 1
            ):
                continue
            results.append(AnalysisCode(
                segment_id=segment_id,
                dimension=dimension,
                score=score,
                reason=str(item.get("reason", ""))[:500],
                confidence=float(confidence),
            ))
        return results


analysis_agent = AnalysisAgent()
