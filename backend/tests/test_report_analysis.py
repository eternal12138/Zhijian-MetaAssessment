import unittest

from pydantic import ValidationError

from app.models.session import CodedSegment, TranscriptSegment
from app.schemas.report import CodingReviewIn
from app.services.report_analyzer import _normalize, _rule_codes


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

    def test_human_review_score_is_limited_to_one_through_seven(self):
        with self.assertRaises(ValidationError):
            CodingReviewIn(human_score=0)
        with self.assertRaises(ValidationError):
            CodingReviewIn(human_score=8)

    def test_transcript_coding_no_longer_requires_dialogue_turn(self):
        self.assertTrue(CodedSegment.__table__.c.turn_id.nullable)
        self.assertTrue(CodedSegment.__table__.c.transcript_segment_id.nullable)


if __name__ == "__main__":
    unittest.main()
