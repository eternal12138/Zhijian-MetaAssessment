import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.extraction import _candidate_snapshot, _is_low_risk, _require_review_lock
from app.core.time import utc_now_naive
from app.models.extraction import ExtractionCandidate
from app.schemas.extraction import ExtractionBatchRerunIn, ExtractionJobStatusBatchIn
from app.services import extraction_service


class CandidateReviewEfficiencyTests(unittest.TestCase):
    @staticmethod
    def candidate(**overrides) -> ExtractionCandidate:
        values = {
            "source_type": "llm",
            "review_status": "pending",
            "source_transcript_segment_id": "segment-1",
            "original_text": "嗯，我先计算平均数",
            "clean_text": "我先计算平均数",
            "raw_asr_text": "前面的话。嗯，我先计算平均数，然后比较波动。",
            "started_at_ms": 1000,
            "ended_at_ms": 2600,
        }
        values.update(overrides)
        return ExtractionCandidate(**values)

    def test_low_risk_requires_traceable_conservative_evidence(self):
        self.assertTrue(_is_low_risk(self.candidate()))
        self.assertFalse(_is_low_risk(self.candidate(clean_text="我决定计算均值")))
        self.assertFalse(_is_low_risk(self.candidate(source_transcript_segment_id=None)))
        self.assertFalse(_is_low_risk(self.candidate(review_status="accepted")))
        self.assertFalse(_is_low_risk(self.candidate(
            predicted_label=0, prediction_confidence=0.99
        )))
        self.assertFalse(_is_low_risk(self.candidate(
            predicted_label=2, prediction_confidence=0.74
        )))
        self.assertTrue(_is_low_risk(self.candidate(
            predicted_label=2, prediction_confidence=0.91
        )))

    def test_another_active_reviewer_blocks_writes(self):
        job = SimpleNamespace(
            review_lock_user_id="reviewer-b",
            review_lock_expires_at=utc_now_naive() + timedelta(minutes=2),
        )
        with self.assertRaises(HTTPException) as context:
            _require_review_lock(job, SimpleNamespace(id="reviewer-a"))
        self.assertEqual(context.exception.status_code, 423)

    def test_expired_lease_requires_reacquisition(self):
        job = SimpleNamespace(
            review_lock_user_id="reviewer-a",
            review_lock_expires_at=utc_now_naive() - timedelta(seconds=1),
        )
        with self.assertRaises(HTTPException) as context:
            _require_review_lock(job, SimpleNamespace(id="reviewer-a"))
        self.assertEqual(context.exception.status_code, 409)

    def test_candidate_snapshot_preserves_before_after_research_fields(self):
        snapshot = _candidate_snapshot(self.candidate(
            review_status="accepted", review_note="人工确认"
        ))
        self.assertEqual(snapshot["clean_text"], "我先计算平均数")
        self.assertEqual(snapshot["review_status"], "accepted")
        self.assertEqual(snapshot["review_note"], "人工确认")
        self.assertEqual(snapshot["started_at_ms"], 1000)

    def test_batch_rerun_requires_unique_bounded_session_ids(self):
        payload = ExtractionBatchRerunIn(session_ids=["session-b", "session-a"])
        self.assertEqual(payload.session_ids, ["session-b", "session-a"])
        with self.assertRaises(ValidationError):
            ExtractionBatchRerunIn(session_ids=["session-a", "session-a"])
        with self.assertRaises(ValidationError):
            ExtractionBatchRerunIn(session_ids=[])
        with self.assertRaises(ValidationError):
            ExtractionBatchRerunIn(
                session_ids=[f"session-{index}" for index in range(51)]
            )

    def test_job_status_batch_requires_unique_bounded_job_ids(self):
        payload = ExtractionJobStatusBatchIn(job_ids=["job-b", "job-a"])
        self.assertEqual(payload.job_ids, ["job-b", "job-a"])
        with self.assertRaises(ValidationError):
            ExtractionJobStatusBatchIn(job_ids=["job-a", "job-a"])
        with self.assertRaises(ValidationError):
            ExtractionJobStatusBatchIn(job_ids=[])

    def test_terminal_extraction_creates_deduplicated_notification(self):
        job = SimpleNamespace(
            id="job-1",
            session_id="session-1",
            requested_by="reviewer-1",
            generation_no=3,
            error_code=None,
            error_message=None,
        )
        create_notification = AsyncMock()
        with patch.object(
            extraction_service, "create_notification", create_notification
        ):
            asyncio.run(extraction_service._notify_extraction_terminal(
                AsyncMock(), job, succeeded=True, candidate_count=12
            ))
        create_notification.assert_awaited_once()
        kwargs = create_notification.await_args.kwargs
        self.assertEqual(kwargs["event_key"], "extraction:job-1:completed")
        self.assertEqual(
            kwargs["target_url"],
            "/candidate-review?session_id=session-1&job_id=job-1",
        )
        self.assertEqual(kwargs["metadata"]["candidate_count"], 12)

    def test_new_extraction_job_is_locked_and_refreshed_before_response(self):
        source = Path(extraction_service.__file__).read_text(encoding="utf-8")
        self.assertIn(".with_for_update()", source)
        self.assertIn(
            'await db.refresh(job, attribute_names=["created_at"])', source
        )


if __name__ == "__main__":
    unittest.main()
