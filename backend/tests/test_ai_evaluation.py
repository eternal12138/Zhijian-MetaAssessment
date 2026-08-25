from __future__ import annotations

import unittest

from app.main import app

from app.api.ai_evaluation import EXPERIMENT_NAMES, candidate_text_source
from app.models.extraction import ExtractionCandidate
from app.services.model_inference import invalidate_candidate_prediction


class AiEvaluationRulesTests(unittest.TestCase):
    def test_human_review_text_has_priority(self):
        self.assertEqual(candidate_text_source("accepted"), "human_review")
        self.assertEqual(candidate_text_source("pending"), "ai_candidate")

    def test_all_seven_supported_training_methods_are_visible(self):
        self.assertEqual(
            set(EXPERIMENT_NAMES),
            {
                "tfidf_linear_svc", "embedding_linear_svc",
                "embedding_logistic", "embedding_random_forest",
                "embedding_xgboost", "embedding_lightgbm", "embedding_catboost",
            },
        )

    def test_model_deactivation_endpoint_is_registered(self):
        paths = app.openapi()["paths"]
        self.assertIn("/api/research/model-training/jobs/{job_id}/deactivate", paths)

    def test_human_text_change_invalidates_stale_prediction(self):
        candidate = ExtractionCandidate(
            extraction_job_id="job", session_id="session", user_id="user", task_id="task",
            sequence_no=1, raw_asr_text="原文", original_text="原文", clean_text="原文",
            classifier_job_id="model", classifier_version="v1", predicted_label=1,
            predicted_dimension="monitoring", prediction_confidence=.9,
            prediction_probabilities={"1": .9}, classification_status="classified",
            prediction_source="tfidf_production", classification_error="old",
        )
        invalidate_candidate_prediction(candidate)
        self.assertIsNone(candidate.classifier_job_id)
        self.assertIsNone(candidate.predicted_label)
        self.assertEqual(candidate.classification_status, "pending_classification")
        self.assertEqual(candidate.classification_error, "")


if __name__ == "__main__":
    unittest.main()
