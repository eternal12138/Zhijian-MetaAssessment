import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from app.api.reports import _ensure_measurement_owned_by_student
from app.services.metacognition_measurement import (
    calculate_dimension_scores,
    calculate_reviewed_candidate_scores,
    reviewed_candidate_source,
)


class MetacognitionMeasurementTests(unittest.TestCase):
    def test_dimension_scores_use_effective_dialogue_denominator(self):
        labels = ["monitoring"] * 3 + ["regulation"] * 4 + ["other"] * 3
        counts, scores = calculate_dimension_scores(labels, 10)
        self.assertEqual(counts["monitoring"], 3)
        self.assertEqual(counts["controlDebugging"], 4)
        self.assertEqual(counts["evaluation"], 0)
        self.assertEqual(scores["monitoring"], 0.3)
        self.assertEqual(scores["controlDebugging"], 0.4)
        self.assertEqual(scores["evaluation"], 0.0)
        self.assertEqual(sum(value for value in scores.values() if value is not None), 0.7)

    def test_zero_effective_dialogues_are_unavailable(self):
        counts, scores = calculate_dimension_scores([], 0)
        self.assertEqual(counts, {
            "monitoring": 0, "controlDebugging": 0, "evaluation": 0,
        })
        self.assertEqual(scores, {
            "monitoring": None, "controlDebugging": None, "evaluation": None,
        })

    def test_only_finally_accepted_candidates_enter_denominator(self):
        candidates = [
            SimpleNamespace(
                review_status="accepted" if index < 10 else "pending",
                predicted_dimension=("monitoring" if index < 3 else "regulation"),
            )
            for index in range(12)
        ]
        total, counts, scores = calculate_reviewed_candidate_scores(candidates)
        self.assertEqual(total, 10)
        self.assertEqual(counts["monitoring"], 3)
        self.assertEqual(scores["monitoring"], 0.3)

    def test_changed_final_label_is_recalculated(self):
        _old_counts, old_scores = calculate_dimension_scores(
            ["monitoring"] * 4 + ["regulation"] * 3 + ["evaluation"] * 3,
            10,
        )
        _new_counts, new_scores = calculate_dimension_scores(
            ["monitoring"] * 3 + ["regulation"] * 4 + ["evaluation"] * 3,
            10,
        )
        self.assertEqual(old_scores["monitoring"], 0.4)
        self.assertEqual(new_scores["monitoring"], 0.3)
        self.assertEqual(new_scores["controlDebugging"], 0.4)

    def test_human_corrected_transcript_provenance_is_preserved(self):
        self.assertEqual(reviewed_candidate_source(["server_asr"]), "human_review")
        self.assertEqual(
            reviewed_candidate_source(["server_asr", "human_corrected"]),
            "uploaded_review",
        )

    def test_student_cannot_read_another_students_run(self):
        with self.assertRaises(HTTPException) as raised:
            _ensure_measurement_owned_by_student(
                SimpleNamespace(user_id="student-b"),
                SimpleNamespace(id="student-a"),
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_task_scoped_measurement_columns_are_declared(self):
        from app.models.report import MetacognitionMeasurement

        table = MetacognitionMeasurement.__table__
        self.assertIn("scope_type", table.c)
        self.assertIn("scope_key", table.c)
        self.assertIn("task_id", table.c)
        unique_scope = next(
            index for index in table.indexes
            if index.name == "uq_metacognition_measurement_scope"
        )
        self.assertTrue(unique_scope.unique)
        self.assertEqual([column.name for column in unique_scope.columns], ["run_id", "scope_key"])


if __name__ == "__main__":
    unittest.main()
