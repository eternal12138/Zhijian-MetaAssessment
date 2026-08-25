import unittest
from datetime import datetime
from types import SimpleNamespace

from app.services.run_quality import evaluate_run_quality, quality_allows_analysis


def _session(sequence_no: int, *, duration: int = 30_000, transcript: str = "这是达到最低内容长度的有效权威转录文本。"):
    now = datetime(2026, 1, 1)
    return SimpleNamespace(
        sequence_no=sequence_no,
        status="completed",
        audio_chunks=[SimpleNamespace(id=f"chunk-{sequence_no}")],
        asr_jobs=[SimpleNamespace(
            id=f"job-{sequence_no}",
            created_at=now,
            status="completed",
            canonical_audio_path=f"run/{sequence_no}.wav",
            audio_duration_ms=duration,
        )],
        transcript_versions=[SimpleNamespace(
            is_authoritative=True,
            full_text=transcript,
        )],
    )


def _run():
    return SimpleNamespace(
        status="completed",
        sessions=[_session(1), _session(2)],
        questionnaire_enabled=True,
        questionnaire_responses=[SimpleNamespace(item_id=f"q-{index}") for index in range(12)],
    )


class RunQualityTests(unittest.TestCase):
    def test_complete_run_is_eligible(self):
        quality = evaluate_run_quality(_run(), 12)
        self.assertEqual(quality["automatic_status"], "passed")
        self.assertEqual(quality["effective_status"], "eligible")
        self.assertTrue(quality_allows_analysis(quality))

    def test_missing_audio_blocks_analysis(self):
        run = _run()
        run.sessions[0].audio_chunks = []
        quality = evaluate_run_quality(run, 12)
        self.assertEqual(quality["automatic_status"], "failed")
        self.assertEqual(quality["effective_status"], "ineligible")
        self.assertFalse(quality_allows_analysis(quality))

    def test_manual_inclusion_is_explicit_override(self):
        run = _run()
        run.sessions[0].audio_chunks = []
        review = SimpleNamespace(decision="included")
        quality = evaluate_run_quality(run, 12, review)
        self.assertEqual(quality["effective_status"], "included_override")
        self.assertTrue(quality_allows_analysis(quality))

    def test_manual_exclusion_blocks_valid_run(self):
        quality = evaluate_run_quality(
            _run(), 12, SimpleNamespace(decision="excluded")
        )
        self.assertEqual(quality["effective_status"], "excluded")
        self.assertFalse(quality_allows_analysis(quality))


if __name__ == "__main__":
    unittest.main()
