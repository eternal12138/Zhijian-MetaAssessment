from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave
from array import array

from pydantic import ValidationError

from app.models.asr import AsrJob, TranscriptVersion
from app.models.session import AssessmentSession, AudioChunk, TranscriptSegment
from app.schemas.asr import TranscriptCorrectionIn
from app.services.audio_manifest import AudioManifestError, build_audio_manifest
from app.services.audio_processor import analyze_pcm16_signal
from app.services.report_analyzer import _authoritative_transcripts


def _chunk(
    root: Path,
    index: int,
    payload: bytes,
    *,
    started_at_ms: int | None = None,
) -> AudioChunk:
    relative = f"session-1/chunk-{index:06d}.webm"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return AudioChunk(
        session_id="session-1",
        chunk_index=index,
        storage_path=relative,
        mime_type="audio/webm",
        size_bytes=len(payload),
        started_at_ms=index * 1000 if started_at_ms is None else started_at_ms,
        ended_at_ms=index * 1000 + 1000,
    )


class AsrPipelineTest(unittest.TestCase):
    def test_signal_analysis_flags_silent_recording(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "silent.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16_000)
                audio.writeframes(array("h", [0] * 16_000).tobytes())

            rms_dbfs, peak_dbfs, contains_signal = analyze_pcm16_signal(path)

        self.assertIsNone(rms_dbfs)
        self.assertIsNone(peak_dbfs)
        self.assertFalse(contains_signal)

    def test_signal_analysis_accepts_audible_recording(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "audible.wav"
            samples = array("h", [4000, -4000] * 8_000)
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16_000)
                audio.writeframes(samples.tobytes())

            rms_dbfs, peak_dbfs, contains_signal = analyze_pcm16_signal(path)

        self.assertIsNotNone(rms_dbfs)
        self.assertIsNotNone(peak_dbfs)
        self.assertTrue(contains_signal)

    def test_manifest_requires_at_least_one_recorded_audio_chunk(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(AudioManifestError) as caught:
                build_audio_manifest("session-1", [], Path(directory))
            self.assertEqual(caught.exception.code, "audio_required")

    def test_manifest_is_deterministic_and_hashes_real_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = [_chunk(root, 0, b"first"), _chunk(root, 1, b"second")]
            first = build_audio_manifest("session-1", chunks, root)
            second = build_audio_manifest("session-1", reversed(chunks), root)
            self.assertEqual(first.manifest_hash, second.manifest_hash)
            self.assertEqual(first.chunk_count, 2)
            self.assertEqual(len(first.chunks[0].sha256), 64)

    def test_manifest_rejects_missing_sequence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = [_chunk(root, 0, b"first"), _chunk(root, 2, b"third")]
            with self.assertRaises(AudioManifestError) as caught:
                build_audio_manifest("session-1", chunks, root)
            self.assertEqual(caught.exception.code, "chunk_sequence_incomplete")

    def test_manifest_rejects_file_size_change(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            chunk = _chunk(root, 0, b"first")
            (root / chunk.storage_path).write_bytes(b"changed-size")
            with self.assertRaises(AudioManifestError) as caught:
                build_audio_manifest("session-1", [chunk], root)
            self.assertEqual(caught.exception.code, "chunk_size_mismatch")

    def test_manifest_normalizes_restored_client_timeline_regression(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = [
                _chunk(root, 0, b"first"),
                _chunk(root, 1, b"second", started_at_ms=0),
            ]
            manifest = build_audio_manifest("session-1", chunks, root)
            self.assertEqual(manifest.schema_version, "1.1")
            self.assertEqual(manifest.chunks[0].started_at_ms, 0)
            self.assertEqual(manifest.chunks[0].ended_at_ms, 1000)
            self.assertEqual(manifest.chunks[1].started_at_ms, 1000)
            self.assertEqual(manifest.chunks[1].ended_at_ms, 2000)

    def test_correction_requires_unique_segment_numbers(self):
        with self.assertRaises(ValidationError):
            TranscriptCorrectionIn.model_validate({
                "segments": [
                    {
                        "segment_no": 0,
                        "text": "第一段",
                        "started_at_ms": 0,
                        "ended_at_ms": 1000,
                    },
                    {
                        "segment_no": 0,
                        "text": "重复序号",
                        "started_at_ms": 1000,
                        "ended_at_ms": 2000,
                    },
                ]
            })

    def test_report_uses_only_authoritative_transcript_version(self):
        session = AssessmentSession(
            id="session-1", user_id="user-1", task_id="task-1"
        )
        job = AsrJob(
            id="job-1",
            session_id=session.id,
            provider="test",
            model="test",
            config_version="1",
            manifest_hash="a" * 64,
            input_manifest={},
            expected_chunk_count=1,
        )
        old_version = TranscriptVersion(
            id="version-1",
            session_id=session.id,
            version_no=1,
            source="server_asr",
            status="superseded",
            is_authoritative=False,
            full_text="旧文本",
        )
        current_version = TranscriptVersion(
            id="version-2",
            session_id=session.id,
            version_no=2,
            source="human_corrected",
            status="approved",
            is_authoritative=True,
            full_text="新文本",
        )
        old = TranscriptSegment(
            id="segment-1",
            session_id=session.id,
            client_segment_id="old",
            transcript_version_id=old_version.id,
            segment_no=0,
            text="旧文本",
            is_final=True,
        )
        current = TranscriptSegment(
            id="segment-2",
            session_id=session.id,
            client_segment_id="current",
            transcript_version_id=current_version.id,
            segment_no=0,
            text="新文本",
            is_final=True,
        )
        session.asr_jobs = [job]
        session.transcript_versions = [old_version, current_version]
        session.transcript_segments = [old, current]
        run = type("Run", (), {"sessions": [session]})()

        self.assertEqual(
            [item.text for item in _authoritative_transcripts(run)],
            ["新文本"],
        )
