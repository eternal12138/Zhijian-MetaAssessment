import csv
from io import StringIO
import unittest

from pydantic import ValidationError

from app.schemas.research import ExpertAnnotationIn
from app.services.expert_dataset import EXPERT_LABELS, build_training_csv


class ExpertDatasetTests(unittest.TestCase):
    def test_expert_schema_accepts_only_the_canonical_three_labels(self):
        for label in EXPERT_LABELS:
            payload = ExpertAnnotationIn(expert_label=label, note="")
            self.assertEqual(payload.expert_label, label)
        for legacy_or_invalid in (
            "planning", "non_metacognitive", "legacy_evaluation", "unknown"
        ):
            with self.assertRaises(ValidationError):
                ExpertAnnotationIn(expert_label=legacy_or_invalid, note="")

    def test_clean_text_is_default_training_input_without_losing_raw_text(self):
        content, count = build_training_csv([
            {
                "segment_id": "segment-1",
                "user_id": "user-1",
                "audio_id": "audio-1",
                "start_time": 1200,
                "end_time": 3400,
                "raw_text": "嗯我先算一下",
                "clean_text": "我先算一下",
                "label": "monitoring",
            }
        ])
        rows = list(csv.DictReader(StringIO(content.decode("utf-8-sig"))))
        self.assertEqual(count, 1)
        self.assertEqual(rows[0]["text"], "我先算一下")
        self.assertEqual(rows[0]["raw_text"], "嗯我先算一下")
        self.assertEqual(rows[0]["clean_text"], "我先算一下")

    def test_raw_text_can_be_selected_and_unlabelled_rows_are_excluded(self):
        content, count = build_training_csv(
            [
                {
                    "segment_id": "segment-1",
                    "raw_text": "原始文本",
                    "clean_text": "清洗文本",
                    "label": "monitoring",
                },
                {
                    "segment_id": "segment-2",
                    "raw_text": "不应导出",
                    "clean_text": "不应导出",
                    "label": "legacy_evaluation",
                },
                {
                    "segment_id": "segment-3",
                    "raw_text": "未标注",
                    "clean_text": "未标注",
                    "label": "",
                },
            ],
            text_source="raw_text",
        )
        rows = list(csv.DictReader(StringIO(content.decode("utf-8-sig"))))
        self.assertEqual(count, 1)
        self.assertEqual(rows[0]["segment_id"], "segment-1")
        self.assertEqual(rows[0]["text"], "原始文本")

    def test_unknown_text_source_is_rejected(self):
        with self.assertRaises(ValueError):
            build_training_csv([], text_source="segment")


if __name__ == "__main__":
    unittest.main()
