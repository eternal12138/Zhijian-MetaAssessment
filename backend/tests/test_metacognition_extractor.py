import json
import unittest

from app.services.metacognition_extractor.extractor import (
    MetacognitiveExtractor,
    is_conservative_derivation,
)
from app.services.metacognition_extractor.schemas import (
    ExtractionEnvelope,
    SourceSegment,
)


class MetacognitiveExtractorValidationTests(unittest.TestCase):
    def test_conservative_cleaning_allows_only_ordered_deletion(self):
        self.assertTrue(is_conservative_derivation("嗯，我先算平均数", "我先算平均数"))
        self.assertFalse(is_conservative_derivation("我先算平均数", "我决定先计算平均值"))

    def test_evidence_must_be_verbatim_and_deduplicated(self):
        segments = [SourceSegment(
            segment_id="segment-1",
            text="嗯，我先算平均数，然后比较波动。",
            started_at_ms=1000,
            ended_at_ms=3000,
        )]
        envelope = ExtractionEnvelope.model_validate({
            "candidates": [
                {
                    "segment_id": "segment-1",
                    "original_text": "嗯，我先算平均数",
                    "clean_text": "我先算平均数",
                },
                {
                    "segment_id": "segment-1",
                    "original_text": "嗯，我先算平均数",
                    "clean_text": "我先算平均数",
                },
                {
                    "segment_id": "segment-1",
                    "original_text": "我要计算标准差",
                    "clean_text": "我要计算标准差",
                },
            ]
        })
        result = MetacognitiveExtractor._validate_evidence(envelope.candidates, segments)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].clean_text, "我先算平均数")

    def test_schema_rejects_final_label_fields(self):
        payload = {
            "candidates": [{
                "segment_id": "segment-1",
                "original_text": "我检查一下",
                "clean_text": "我检查一下",
                "dimension": "MONITORING",
            }]
        }
        with self.assertRaises(Exception):
            ExtractionEnvelope.model_validate_json(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
