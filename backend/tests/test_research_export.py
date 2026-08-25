import json
import math
import tempfile
import unittest
import wave
from array import array
import zipfile
from pathlib import Path

from app.services.research_export import (
    ResearchExportError,
    _candidate_rows,
    _original_transcript_rows,
    analyze_wav_signal,
    build_audio_transcript_bundle,
    resolve_audio_path,
)


class ResearchExportTest(unittest.TestCase):
    def test_full_text_bundle_can_explicitly_exclude_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "text-only.zip"
            stats = build_audio_transcript_bundle(
                target,
                audio_root=Path(temp),
                sessions=[{
                    "username": "student001", "name": "测试学生",
                    "run_id": "run-1", "session_id": "session-1",
                    "task_title": "任务一", "sequence_no": 1,
                }],
                transcript_versions=[{
                    "session_id": "session-1", "version_no": 1,
                    "source": "server_asr", "full_text": "原始转录文本",
                }],
                transcript_segments=[],
                audio_files=[{
                    "storage_path": "missing.wav", "kind": "canonical_wav",
                    "session_id": "session-1",
                }],
                include_audio=False,
                review_complete=False,
            )

            self.assertEqual(stats["audio_file_count"], 0)
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
                self.assertIn("02_原始转录文本/原始转录文本.csv", names)
                self.assertNotIn("01_原始录音/录音文件清单.csv", names)
                self.assertFalse(any(name.endswith(".wav") for name in names))
                self.assertIn(
                    "原始转录文本",
                    archive.read("02_原始转录文本/原始转录文本.csv").decode("utf-8-sig"),
                )
                manifest = json.loads(archive.read("导出清单.json"))
                self.assertFalse(manifest["include_audio"])
                self.assertFalse(manifest["review_complete"])

    def test_accepted_only_bundle_skips_audio_and_unreviewed_materials(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "accepted-only.zip"
            stats = build_audio_transcript_bundle(
                target,
                audio_root=Path(temp),
                sessions=[{
                    "user_id": "user-1", "username": "student001", "name": "测试学生",
                    "questionnaire_participant_name": "微信名", "class_group": "一班",
                    "run_id": "run-1", "session_id": "session-1", "task_title": "任务一",
                    "sequence_no": 1,
                }, {
                    "user_id": "user-2", "username": "unrelated", "name": "无接受候选用户",
                    "run_id": "run-2", "session_id": "session-2", "task_title": "任务二",
                    "sequence_no": 1,
                }],
                transcript_versions=[{"session_id": "session-1", "full_text": "原始转录"}],
                transcript_segments=[],
                audio_files=[{
                    "storage_path": "missing.wav", "kind": "canonical_wav",
                    "session_id": "session-1",
                }],
                extraction_jobs=[{
                    "job_id": "job-1", "session_id": "session-1",
                    "generation_no": 1, "created_at": "2026-08-23T08:00:00Z",
                }],
                extraction_candidates=[
                    {
                        "candidate_id": "accepted", "job_id": "job-1",
                        "session_id": "session-1", "sequence_no": 1,
                        "source_type": "llm", "review_status": "accepted",
                        "original_text": "接受原文", "clean_text": "接受文本",
                        "reviewed_at": "2026-08-23T09:00:00Z",
                    },
                    {
                        "candidate_id": "pending", "job_id": "job-1",
                        "session_id": "session-1", "sequence_no": 2,
                        "source_type": "llm", "review_status": "pending",
                        "original_text": "待复核原文", "clean_text": "待复核文本",
                    },
                ],
                accepted_only=True,
            )

            self.assertEqual(stats["human_reviewed_count"], 1)
            self.assertEqual(stats["audio_file_count"], 0)
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
                self.assertIn("00_用户信息/用户信息.csv", names)
                self.assertIn("04_AI筛选并人工校对的文本/AI筛选并人工校对的文本.csv", names)
                self.assertNotIn("01_原始录音/录音文件清单.csv", names)
                self.assertNotIn("02_原始转录文本/原始转录文本.csv", names)
                self.assertNotIn("03_AI筛选后的转录文本/AI筛选后的转录文本.csv", names)
                reviewed = archive.read(
                    "04_AI筛选并人工校对的文本/AI筛选并人工校对的文本.csv"
                ).decode("utf-8-sig")
                self.assertIn("接受文本", reviewed)
                self.assertNotIn("待复核文本", reviewed)
                identity = archive.read(
                    "00_用户信息/用户信息.csv"
                ).decode("utf-8-sig")
                self.assertIn("student001", identity)
                self.assertNotIn("unrelated", identity)

    def test_incremental_review_export_only_includes_newly_accepted_candidates(self):
        sessions = [{
            "session_id": "session-1", "run_id": "run-1", "sequence_no": 1,
            "username": "student001", "name": "测试学生",
        }]
        jobs = [{
            "job_id": "job-1", "session_id": "session-1", "generation_no": 1,
            "created_at": "2026-08-20T10:00:00Z",
        }]
        candidates = [
            {
                "candidate_id": "old", "job_id": "job-1", "session_id": "session-1",
                "sequence_no": 1, "source_type": "llm", "review_status": "accepted",
                "clean_text": "上次已经复核", "reviewed_at": "2026-08-21T10:00:00Z",
            },
            {
                "candidate_id": "new", "job_id": "job-1", "session_id": "session-1",
                "sequence_no": 2, "source_type": "llm", "review_status": "accepted",
                "clean_text": "本次新增复核", "reviewed_at": "2026-08-23T10:00:00Z",
            },
            {
                "candidate_id": "pending", "job_id": "job-1", "session_id": "session-1",
                "sequence_no": 3, "source_type": "llm", "review_status": "pending",
                "clean_text": "尚未复核", "reviewed_at": "",
            },
        ]

        rows = _candidate_rows(
            sessions, jobs, candidates, reviewed_only=True,
            reviewed_after="2026-08-22T00:00:00Z",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["人工校对后文本"], "本次新增复核")

    def test_manual_transcript_uses_same_text_column_with_source_marker(self):
        rows = _original_transcript_rows(
            [{
                "session_id": "manual-session",
                "username": "student002",
                "name": "人工样本",
                "run_id": "run-2",
                "sequence_no": 2,
            }],
            [{
                "session_id": "manual-session",
                "version_no": 1,
                "source": "human_transcribed",
                "full_text": "这是人工听写的完整文本。",
                "created_at": "2026-08-22T10:00:00Z",
            }],
            [],
        )

        self.assertEqual(rows[0]["原转录文本"], "这是人工听写的完整文本。")
        self.assertEqual(rows[0]["原转录来源"], "人工转录（非 ASR）")

    def test_wav_signal_check_distinguishes_tone_from_digital_silence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            silent = root / "silent.wav"
            tone = root / "tone.wav"
            for path, samples in (
                (silent, array("h", [0] * 16_000)),
                (
                    tone,
                    array(
                        "h",
                        [
                            round(8_000 * math.sin(2 * math.pi * 440 * i / 16_000))
                            for i in range(16_000)
                        ],
                    ),
                ),
            ):
                with wave.open(str(path), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(16_000)
                    audio.writeframes(samples.tobytes())

            self.assertFalse(analyze_wav_signal(silent)["contains_signal"])
            self.assertTrue(analyze_wav_signal(tone)["contains_signal"])

    def test_audio_path_must_stay_inside_storage_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "audio"
            root.mkdir()
            outside = Path(temp) / "outside.webm"
            outside.write_bytes(b"outside")
            with self.assertRaises(ResearchExportError):
                resolve_audio_path(root, "../outside.webm")

    def test_bundle_contains_audio_transcripts_and_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "audio"
            source = root / "session" / "recording.wav"
            source.parent.mkdir(parents=True)
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16_000)
                audio.writeframes(array("h", [1000] * 16_000).tobytes())
            target = Path(temp) / "bundle.zip"

            stats = build_audio_transcript_bundle(
                target,
                audio_root=root,
                sessions=[{
                    "user_id": "user-1",
                    "username": "student001",
                    "name": "测试学生",
                    "questionnaire_participant_name": "微信测试名",
                    "class_group": "一班",
                    "run_id": "run",
                    "session_id": "session",
                    "task_id": "task",
                    "task_title": "最优投球机判断",
                    "sequence_no": 1,
                    "ended_at": "2026-08-17T08:00:00Z",
                    "run_completed_at": "2026-08-17T08:10:00Z",
                    "task_order_code": "AB",
                }],
                transcript_versions=[{
                    "user_id": "user-1",
                    "username": "student001",
                    "name": "测试学生",
                    "class_group": "一班",
                    "run_id": "run",
                    "session_id": "session",
                    "version_no": 1,
                    "source": "server_asr",
                    "is_authoritative": True,
                    "full_text": "测试转录",
                }],
                transcript_segments=[{
                    "user_id": "user-1",
                    "username": "student001",
                    "name": "测试学生",
                    "class_group": "一班",
                    "run_id": "run",
                    "session_id": "session",
                    "transcript_version_no": 1,
                    "is_authoritative": True,
                    "text": "测试转录",
                }],
                extraction_jobs=[{
                    "job_id": "job-1",
                    "session_id": "session",
                    "generation_no": 1,
                    "model": "test-model",
                    "prompt_version": "prompt-1",
                    "created_at": "2026-08-17T08:20:00Z",
                }],
                extraction_candidates=[{
                    "candidate_id": "candidate-1",
                    "job_id": "job-1",
                    "session_id": "session",
                    "sequence_no": 1,
                    "source_type": "llm",
                    "review_status": "accepted",
                    "started_at_ms": 1000,
                    "ended_at_ms": 3000,
                    "original_text": "我需要检查一下",
                    "clean_text": "我需要检查一下。",
                    "reviewer_id": "reviewer-1",
                    "review_note": "已对照录音",
                    "reviewed_at": "2026-08-17T08:30:00Z",
                }],
                audio_files=[{
                    "storage_path": "session/recording.wav",
                    "kind": "canonical_wav",
                    "session_id": "session",
                    "mime_type": "audio/wav",
                }],
            )

            self.assertEqual(stats["session_count"], 1)
            self.assertEqual(stats["audio_file_count"], 1)
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
                self.assertIn("00_用户信息/用户信息.csv", names)
                self.assertIn("01_原始录音/录音文件清单.csv", names)
                self.assertIn("02_原始转录文本/原始转录文本.csv", names)
                self.assertIn(
                    "03_AI筛选后的转录文本/AI筛选后的转录文本.csv", names
                )
                self.assertIn(
                    "04_AI筛选并人工校对的文本/AI筛选并人工校对的文本.csv",
                    names,
                )
                self.assertIn("导出清单.json", names)
                self.assertIn("导出数据说明.txt", names)
                audio_name = next(name for name in names if name.endswith(".wav"))
                self.assertTrue(audio_name.startswith(
                    "01_原始录音/student001_测试学生_微信测试名/"
                ))
                self.assertEqual(archive.getinfo(audio_name).compress_type, zipfile.ZIP_STORED)
                self.assertEqual(
                    archive.getinfo("02_原始转录文本/原始转录文本.csv").compress_type,
                    zipfile.ZIP_DEFLATED,
                )
                original_csv = archive.read(
                    "02_原始转录文本/原始转录文本.csv"
                ).decode("utf-8-sig")
                self.assertTrue(original_csv.startswith(
                    "账号,用户名,问卷填写姓名,班级,"
                ))
                self.assertIn("测试转录", original_csv)
                reviewed_csv = archive.read(
                    "04_AI筛选并人工校对的文本/AI筛选并人工校对的文本.csv"
                ).decode("utf-8-sig")
                self.assertIn("人工校对后文本", reviewed_csv)
                self.assertIn("我需要检查一下。", reviewed_csv)
                manifest = json.loads(archive.read("导出清单.json"))
                self.assertEqual(manifest["audio_file_count"], 1)
                self.assertFalse(manifest["pseudonymized"])
                self.assertTrue(manifest["contains_direct_identifiers"])
                self.assertEqual(manifest["original_transcript_count"], 1)
                self.assertEqual(manifest["ai_filtered_count"], 1)
                self.assertEqual(manifest["human_reviewed_count"], 1)
                self.assertEqual(len(manifest["audio_files"][0]["SHA256校验值"]), 64)


if __name__ == "__main__":
    unittest.main()
