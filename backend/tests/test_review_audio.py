from pathlib import Path
import tempfile
import unittest
import wave

from app.services.review_audio import (
    sign_review_audio,
    verify_review_audio,
    wav_waveform,
)
from app.services.secure_download import sign_download, verify_download


class ReviewAudioTests(unittest.TestCase):
    def test_large_download_ticket_is_scope_bound_and_expires(self):
        secret = "d" * 64
        signature = sign_download("research-export", "job-1", 5000, secret)
        self.assertTrue(verify_download(
            "research-export", "job-1", 5000, signature, secret, now=4999
        ))
        self.assertFalse(verify_download(
            "research-export", "job-2", 5000, signature, secret, now=4999
        ))
        self.assertFalse(verify_download(
            "research-export", "job-1", 5000, signature, secret, now=5001
        ))

    def test_ticket_is_bound_to_session_job_and_expiry(self):
        secret = "s" * 64
        signature = sign_review_audio("session-1", "job-1", 2000, secret)

        self.assertTrue(verify_review_audio(
            "session-1", "job-1", 2000, signature, secret, now=1999
        ))
        self.assertFalse(verify_review_audio(
            "session-2", "job-1", 2000, signature, secret, now=1999
        ))
        self.assertFalse(verify_review_audio(
            "session-1", "job-1", 2000, signature, secret, now=2001
        ))

    def test_waveform_is_small_normalized_and_reports_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.wav"
            samples = [0, 1000, -2000, 4000, -8000, 16000] * 200
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                for sample in samples:
                    audio.writeframesraw(int(sample).to_bytes(2, "little", signed=True))

            duration, peaks = wav_waveform(path, bars=60)

            self.assertAlmostEqual(duration, len(samples) / 8000, places=4)
            self.assertEqual(len(peaks), 60)
            self.assertTrue(all(0 <= peak <= 1 for peak in peaks))
            self.assertGreater(max(peaks), 0.4)


if __name__ == "__main__":
    unittest.main()
