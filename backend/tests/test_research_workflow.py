import json
import unittest
from datetime import date
from types import SimpleNamespace

from pydantic import ValidationError

from app.api.research import (
    _cohen_kappa,
    _pearson,
    _reviewer_slot,
    _transcript_scope_base,
)
from app.models.session import TranscriptSegment
from sqlalchemy import select
from app.schemas.research import (
    CodingUnitAdjudicationIn,
    CodingUnitAnnotationIn,
    CodingBatchCreateIn,
    CodingBatchScopeIn,
    TemplateUpdateIn,
)
from app.services.method_templates import DEFAULT_TEMPLATES


class ResearchWorkflowTest(unittest.TestCase):
    def test_default_templates_are_replaceable_and_well_formed(self):
        report_prompt = DEFAULT_TEMPLATES["report_prompt"]["content"]
        self.assertIn("{overall_score}", report_prompt)
        self.assertIn("{dimension_results}", report_prompt)
        self.assertIn("metacognition_pattern", report_prompt)
        self.assertIn("group_norm.status", report_prompt)
        self.assertIn("integrated", report_prompt)
        for prefix in ("立即尝试：", "练习安排：", "效果检查："):
            self.assertIn(prefix, report_prompt)
        self.assertIn("{segments}", DEFAULT_TEMPLATES["metacognitive_extractor"]["content"])

    def test_template_kind_is_constrained(self):
        with self.assertRaises(ValidationError):
            TemplateUpdateIn(version="v1", kind="unknown", content="{}")

    def test_agreement_metrics_handle_perfect_and_inverse_pairs(self):
        self.assertEqual(
            _cohen_kappa([
                ("monitoring", "monitoring"),
                ("evaluation", "evaluation"),
            ]),
            1.0,
        )
        self.assertEqual(_pearson([(1, 7), (2, 6), (3, 5)]), -1.0)

    def test_blinded_annotation_accepts_no_evidence_without_a_score(self):
        annotation = CodingUnitAnnotationIn(dimension=None, note="")
        self.assertIsNone(annotation.dimension)
        self.assertFalse(hasattr(annotation, "score"))
        with self.assertRaises(ValidationError):
            CodingUnitAnnotationIn(note="")

    def test_third_party_adjudication_requires_a_reason(self):
        with self.assertRaises(ValidationError):
            CodingUnitAdjudicationIn(dimension="monitoring", note="")

    def test_fixed_batch_assigns_only_its_named_reviewers(self):
        batch = SimpleNamespace(reviewer_a_id="reviewer-a", reviewer_b_id="reviewer-b")
        self.assertEqual(_reviewer_slot(batch, "reviewer-a"), "A")
        self.assertEqual(_reviewer_slot(batch, "reviewer-b"), "B")
        self.assertIsNone(_reviewer_slot(batch, "someone-else"))

    def test_coding_scope_rejects_reversed_completion_dates(self):
        with self.assertRaises(ValidationError):
            CodingBatchScopeIn(
                completed_from=date(2026, 8, 2),
                completed_to=date(2026, 8, 1),
            )

    def test_coding_scope_shows_all_batches_by_default(self):
        scope = CodingBatchScopeIn()
        self.assertFalse(scope.exclude_previously_batched)

    def test_unreviewed_candidates_require_explicit_batch_confirmation(self):
        base = {
            "name": "第一轮盲编",
            "reviewer_a_id": "reviewer-a",
            "reviewer_b_id": "reviewer-b",
            "adjudicator_id": "adjudicator",
        }
        self.assertFalse(CodingBatchCreateIn(**base).allow_unreviewed_candidates)
        self.assertTrue(CodingBatchCreateIn(
            **base,
            allow_unreviewed_candidates=True,
        ).allow_unreviewed_candidates)

    def test_scope_search_is_based_on_authoritative_transcripts(self):
        statement = _transcript_scope_base(select(TranscriptSegment.id))
        sql = str(statement)
        self.assertIn("transcript_versions", sql)
        self.assertIn("transcript_versions.is_authoritative", sql)
        self.assertNotIn("extraction_jobs.status", sql)


if __name__ == "__main__":
    unittest.main()
