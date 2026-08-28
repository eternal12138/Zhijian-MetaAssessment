import unittest

from app.models.session import CodedSegment, TranscriptSegment
from app.services.report_analyzer import (
    _fallback_behavior_score,
    _normalize,
    _rule_codes,
)


class ReportAnalysisTest(unittest.TestCase):
    def test_normalize_maps_likert_endpoints_to_zero_and_one_hundred(self):
        self.assertEqual(_normalize(1), 0.0)
        self.assertEqual(_normalize(4), 50.0)
        self.assertEqual(_normalize(7), 100.0)

    def test_rule_coding_keeps_observable_dimension_evidence(self):
        segment = TranscriptSegment(
            id="segment-1",
            session_id="session-1",
            client_segment_id="client-1",
            text="我发现这个方法可能不对，准备换一种方法重新计算，最后再验证结果。",
            is_final=True,
        )
        codes = _rule_codes(
            segment,
            {
                "monitoring": "item-m",
                "controlDebugging": "item-c",
                "evaluation": "item-e",
            },
        )
        self.assertEqual(
            {item["dimension"] for item in codes},
            {"monitoring", "controlDebugging", "evaluation"},
        )
        self.assertTrue(all(1 <= item["score"] <= 7 for item in codes))

    def test_legacy_human_score_cannot_override_report_fallback(self):
        code = CodedSegment(
            id="coding-1",
            session_id="session-1",
            segment="测试片段",
            score=2,
            human_score=7,
            reason="自动编码",
            confidence=0.8,
        )

        self.assertEqual(_fallback_behavior_score(code), 2.0)

    def test_transcript_coding_no_longer_requires_dialogue_turn(self):
        self.assertTrue(CodedSegment.__table__.c.turn_id.nullable)
        self.assertTrue(CodedSegment.__table__.c.transcript_segment_id.nullable)


if __name__ == "__main__":
    unittest.main()
