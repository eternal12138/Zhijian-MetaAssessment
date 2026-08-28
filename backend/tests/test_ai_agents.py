import json
import unittest
from types import SimpleNamespace

from app.services.analysis_agent import (
    AnalysisAgent,
    AnalysisSegment,
)
class AnalysisAgentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.segments = [
            AnalysisSegment(segment_id="segment-1", text="我发现结果矛盾了。"),
            AnalysisSegment(segment_id="segment-2", text="我准备换一种方法。"),
        ]

    def test_parse_codes_accepts_only_valid_structured_evidence(self):
        content = json.dumps([
            {
                "segment_id": "segment-1",
                "dimension": "monitoring",
                "score": 6,
                "reason": "发现结果矛盾",
                "confidence": 0.91,
            },
            {
                "segment_id": "unknown",
                "dimension": "evaluation",
                "score": 5,
                "reason": "不存在的片段",
                "confidence": 0.8,
            },
            {
                "segment_id": "segment-2",
                "dimension": "controlDebugging",
                "score": 9,
                "reason": "非法分数",
                "confidence": 0.8,
            },
        ], ensure_ascii=False)

        results = AnalysisAgent.parse_codes(content, self.segments)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].segment_id, "segment-1")
        self.assertEqual(results[0].dimension, "monitoring")

    async def test_disabled_llm_returns_without_calling_a_provider(self):
        settings = SimpleNamespace(REPORT_USE_LLM=False)
        agent = AnalysisAgent(settings=settings)

        results = await agent.code_segments(self.segments, "片段：{segments}")

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
