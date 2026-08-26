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


import logging

logger = logging.getLogger(__name__)


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

        BATCH_SIZE = 20
        all_codes: list[AnalysisCode] = []
        headers = {
            "Authorization": f"Bearer {self.settings.LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.settings.REPORT_LLM_TIMEOUT_SECONDS)

        for batch_start in range(0, len(segments), BATCH_SIZE):
            batch_segments = segments[batch_start:batch_start + BATCH_SIZE]
            payload = [
                {"segment_id": item.segment_id, "text": item.text[:600]}
                for item in batch_segments
            ]
            prompt = prompt_template.replace(
                "{segments}",
                json.dumps(payload, ensure_ascii=False),
            )
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
                batch_codes = self.parse_codes(str(content), batch_segments)
                all_codes.extend(batch_codes)
            except Exception as error:
                logger.warning(
                    "LLM 事后元认知编码轮次 (第 %d-%d 条) 失败: %s",
                    batch_start + 1,
                    min(batch_start + BATCH_SIZE, len(segments)),
                    error,
                )

        return all_codes

    async def generate_metacognitive_profile(
        self,
        overall_score: float,
        dimension_results: list[dict],
        prompt_template: str,
    ) -> dict | None:
        if not self.settings.REPORT_USE_LLM:
            return None

        clean_dimensions = [
            {
                "dimension": d.get("dimension"),
                "label": d.get("label"),
                "score": d.get("score"),
                "behavioral_score": d.get("behavioral_score"),
                "questionnaire_score": d.get("questionnaire_score"),
                "behavioral_count": d.get("behavioral_count"),
                "key_evidence": [e.get("excerpt") for e in d.get("evidence", [])[:3] if e.get("excerpt")],
            }
            for d in dimension_results
        ]

        prompt = prompt_template.replace(
            "{overall_score}", str(round(overall_score, 1))
        ).replace(
            "{dimension_results}", json.dumps(clean_dimensions, ensure_ascii=False, indent=2)
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
                                "content": "你是元认知测评分析与画像生成智能体。请严格依据输入的三分类数据返回纯 JSON 对象，不输出思维链或 Markdown 格式标记。",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": self.settings.LLM_TEMPERATURE,
                        "top_p": self.settings.LLM_TOP_P,
                        "max_tokens": min(self.settings.LLM_MAX_TOKENS, 2048),
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            return self.parse_profile_response(str(content))
        except Exception as error:
            logger.warning("LLM 生成元认知画像报告失败 (将降级使用规则模板): %s", error)
            return None

    @staticmethod
    def parse_profile_response(content: str) -> dict | None:
        normalized = content.strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            normalized = "\n".join(lines).strip()
        try:
            parsed = json.loads(normalized)
            if not isinstance(parsed, dict):
                return None
            return parsed
        except Exception:
            return None

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
