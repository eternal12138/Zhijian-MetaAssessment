"""Build access-controlled Chinese research bundles containing audio and transcripts."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import shutil
import sys
import wave
import zipfile
from array import array
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class ResearchExportError(ValueError):
    """Raised when an export references an unsafe or unreadable source file."""


@contextmanager
def _atomic_zip(target: Path):
    """Publish only complete archives and always remove failed partial files."""
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(
            partial, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            yield archive
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def export_dataset_fingerprint(*collections: list[dict[str, Any]]) -> str:
    """Hash the exact logical inputs so identical exports can reuse one ZIP."""
    encoded = json.dumps(
        collections,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ensure_export_capacity(
    export_root: Path,
    audio_root: Path,
    audio_files: list[dict[str, Any]],
    minimum_free_bytes: int,
) -> int:
    """Require enough room for the stored WAV payload plus a safety reserve."""
    payload_bytes = 0
    for item in audio_files:
        if item.get("kind") != "canonical_wav":
            continue
        known_size = item.get("size_bytes")
        if isinstance(known_size, int) and known_size >= 0:
            payload_bytes += known_size
        else:
            try:
                payload_bytes += resolve_audio_path(
                    audio_root, str(item.get("storage_path", ""))
                ).stat().st_size
            except Exception:
                pass
    required = payload_bytes + minimum_free_bytes + 64 * 1024 * 1024
    export_root.mkdir(parents=True, exist_ok=True)
    try:
        free = shutil.disk_usage(export_root).free
    except Exception:
        free = 10 * 1024 * 1024 * 1024  # 默认 10GB 兜底
    if free < required:
        need_gib = required / (1024 ** 3)
        free_gib = free / (1024 ** 3)
        raise ResearchExportError(
            "服务器磁盘空间不足：本次导出至少需要 "
            f"{need_gib:.2f} GiB，当前仅剩 {free_gib:.2f} GiB。"
            "请清理过期导出或扩容后重试；原始录音未受影响。"
        )
    return payload_bytes


def resolve_audio_path(audio_root: Path, storage_path: str) -> Path:
    root = audio_root.resolve()
    candidate = (root / storage_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ResearchExportError("audio path escapes the configured storage root") from error
    if not candidate.is_file():
        raise ResearchExportError(f"audio file is missing: {storage_path}")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze_wav_signal(path: Path) -> dict[str, Any]:
    """Return content-free signal metrics for a 16-bit PCM WAV."""
    sample_count = 0
    sum_squares = 0
    peak = 0
    with wave.open(str(path), "rb") as audio:
        if audio.getsampwidth() != 2:
            raise ResearchExportError("WAV signal check requires 16-bit PCM")
        channels = audio.getnchannels()
        sample_rate_hz = audio.getframerate()
        while True:
            frames = audio.readframes(16_384)
            if not frames:
                break
            samples = array("h")
            samples.frombytes(frames)
            if sys.byteorder != "little":
                samples.byteswap()
            sample_count += len(samples)
            sum_squares += sum(sample * sample for sample in samples)
            peak = max(peak, max((abs(sample) for sample in samples), default=0))
    rms = math.sqrt(sum_squares / sample_count) if sample_count else 0.0
    rms_dbfs = round(20 * math.log10(rms / 32768), 2) if rms else None
    peak_dbfs = round(20 * math.log10(peak / 32768), 2) if peak else None
    return {
        "channels": channels,
        "sample_rate_hz": sample_rate_hz,
        "rms_dbfs": rms_dbfs,
        "peak_dbfs": peak_dbfs,
        "contains_signal": bool(
            rms_dbfs is not None
            and peak_dbfs is not None
            and rms_dbfs > -60
            and peak_dbfs > -50
        ),
    }


def collect_wav_metadata(path: Path) -> dict[str, Any]:
    """Collect reusable integrity and signal metadata for a canonical WAV."""
    return {
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        **analyze_wav_signal(path),
    }


def _csv_bytes(rows: list[dict[str, Any]], fieldnames: list[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _safe_component(value: Any, fallback: str = "未填写") -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", "_", text).strip(" ._")
    return (text or fallback)[:80]


def _identity(row: dict[str, Any]) -> dict[str, Any]:
    """Keep requested direct identifiers at the beginning of every CSV."""
    return {
        "账号": row.get("username", ""),
        "用户名": row.get("name", ""),
        "问卷填写姓名": row.get("questionnaire_participant_name", ""),
        "班级": row.get("class_group", ""),
    }


def _task_columns(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "测评编号": row.get("run_id", ""),
        "任务会话编号": row.get("session_id", ""),
        "任务序号": row.get("sequence_no", ""),
        "任务名称": row.get("task_title", ""),
        "任务完成时间": row.get("ended_at", ""),
    }


def _latest_candidate_job_ids(
    extraction_jobs: list[dict[str, Any]],
    extraction_candidates: list[dict[str, Any]],
) -> set[str]:
    jobs_with_candidates = {
        str(item.get("job_id", "")) for item in extraction_candidates
        if item.get("job_id")
    }
    latest: dict[str, dict[str, Any]] = {}
    for job in extraction_jobs:
        job_id = str(job.get("job_id", ""))
        session_id = str(job.get("session_id", ""))
        if not job_id or not session_id or job_id not in jobs_with_candidates:
            continue
        current = latest.get(session_id)
        job_key = (int(job.get("generation_no") or 0), str(job.get("created_at") or ""), job_id)
        current_key = (
            int(current.get("generation_no") or 0),
            str(current.get("created_at") or ""),
            str(current.get("job_id") or ""),
        ) if current else (-1, "", "")
        if job_key > current_key:
            latest[session_id] = job
    return {str(item["job_id"]) for item in latest.values()}


def _original_transcript_rows(
    sessions: list[dict[str, Any]],
    transcript_versions: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Choose the first server ASR version; fall back without hiding missing data."""
    session_map = {str(item.get("session_id", "")): item for item in sessions}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for version in transcript_versions:
        grouped.setdefault(str(version.get("session_id", "")), []).append(version)

    rows: list[dict[str, Any]] = []
    for session_id, session in session_map.items():
        versions = grouped.get(session_id, [])
        server_versions = [item for item in versions if item.get("source") == "server_asr"]
        non_human_versions = [item for item in versions if item.get("source") != "human_corrected"]
        candidates = server_versions or non_human_versions or versions
        selected = min(
            candidates,
            key=lambda item: (int(item.get("version_no") or 0), str(item.get("created_at") or "")),
            default=None,
        )
        if selected is not None:
            full_text = selected.get("full_text", "")
            raw_source = str(selected.get("source", ""))
            source = {
                "server_asr": "服务端 ASR",
                "human_transcribed": "人工转录（非 ASR）",
                "human_corrected": "人工校订",
                "browser": "浏览器实时转录",
            }.get(raw_source, raw_source)
            version_no = selected.get("version_no", "")
        else:
            browser_segments = sorted(
                (
                    item for item in transcript_segments
                    if str(item.get("session_id", "")) == session_id
                    and not item.get("transcript_version_no")
                ),
                key=lambda item: (
                    int(item.get("started_at_ms") or 0),
                    int(item.get("segment_no") or 0),
                ),
            )
            full_text = "\n".join(
                str(item.get("text", "")).strip()
                for item in browser_segments if item.get("text")
            )
            source = "浏览器实时转录" if browser_segments else ""
            version_no = ""
        rows.append({
            **_identity(session),
            **_task_columns(session),
            "原转录来源": source,
            "原转录版本号": version_no,
            "原转录文本": full_text,
        })
    return rows


def _candidate_rows(
    sessions: list[dict[str, Any]],
    extraction_jobs: list[dict[str, Any]],
    extraction_candidates: list[dict[str, Any]],
    *,
    reviewed_only: bool,
    reviewed_after: str | None = None,
) -> list[dict[str, Any]]:
    session_map = {str(item.get("session_id", "")): item for item in sessions}
    latest_job_ids = _latest_candidate_job_ids(extraction_jobs, extraction_candidates)
    job_map = {str(item.get("job_id", "")): item for item in extraction_jobs}
    rows: list[dict[str, Any]] = []
    for candidate in extraction_candidates:
        job_id = str(candidate.get("job_id", ""))
        if job_id not in latest_job_ids:
            continue
        source_type = str(candidate.get("source_type", ""))
        review_status = str(candidate.get("review_status", ""))
        if not reviewed_only and source_type != "llm":
            continue
        if reviewed_only and review_status != "accepted":
            continue
        if reviewed_only and reviewed_after:
            reviewed_at = str(candidate.get("reviewed_at") or "")
            if not reviewed_at or reviewed_at <= reviewed_after:
                continue
        session = session_map.get(str(candidate.get("session_id", "")), candidate)
        job = job_map.get(job_id, {})
        common = {
            **_identity(session),
            **_task_columns(session),
            "抽取版本": f"V{job.get('generation_no', '')}",
            "模型": job.get("model", ""),
            "提示词版本": job.get("prompt_version", ""),
            "候选序号": candidate.get("sequence_no", ""),
            "开始时间（毫秒）": candidate.get("started_at_ms", ""),
            "结束时间（毫秒）": candidate.get("ended_at_ms", ""),
            "来源类型": "AI筛选" if source_type == "llm" else "人工补充",
        }
        if reviewed_only:
            rows.append({
                **common,
                "AI筛选原文": candidate.get("original_text", ""),
                "人工校对后文本": candidate.get("clean_text", ""),
                "人工复核结果": "已接受",
                "人工校对人编号": candidate.get("reviewer_id", ""),
                "人工校对备注": candidate.get("review_note", ""),
                "人工校对时间": candidate.get("reviewed_at", ""),
            })
        else:
            rows.append({
                **common,
                "AI筛选原文": candidate.get("original_text", ""),
                "AI清洗后文本": candidate.get("clean_text", ""),
                "当前人工复核状态": review_status,
            })
    return sorted(
        rows,
        key=lambda item: (
            str(item.get("账号", "")),
            str(item.get("测评编号", "")),
            int(item.get("任务序号") or 0),
            int(item.get("候选序号") or 0),
        ),
    )


def build_audio_transcript_bundle(
    target: Path,
    *,
    audio_root: Path,
    sessions: list[dict[str, Any]],
    transcript_versions: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    audio_files: list[dict[str, Any]],
    extraction_jobs: list[dict[str, Any]] | None = None,
    extraction_candidates: list[dict[str, Any]] | None = None,
    extraction_candidate_revisions: list[dict[str, Any]] | None = None,
    coding_batches: list[dict[str, Any]] | None = None,
    coding_units: list[dict[str, Any]] | None = None,
    coding_annotations: list[dict[str, Any]] | None = None,
    coding_adjudications: list[dict[str, Any]] | None = None,
    preflight_warnings: list[dict[str, str]] | None = None,
    reviewed_after: str | None = None,
    accepted_only: bool = False,
    include_audio: bool = True,
    review_complete: bool | None = None,
) -> dict[str, Any]:
    """Create a directly identifiable, researcher-friendly Chinese ZIP bundle."""
    del extraction_candidate_revisions, coding_batches, coding_units
    del coding_annotations, coding_adjudications
    target.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[dict[str, str]] = list(preflight_warnings or [])
    extraction_jobs = extraction_jobs or []
    extraction_candidates = extraction_candidates or []
    include_audio = bool(include_audio and not accepted_only)

    identity_fields = ["账号", "用户名", "问卷填写姓名", "班级"]
    task_fields = ["测评编号", "任务会话编号", "任务序号", "任务名称", "任务完成时间"]
    user_rows: list[dict[str, Any]] = []
    seen_runs: set[str] = set()
    for session in sessions:
        run_id = str(session.get("run_id", ""))
        if run_id in seen_runs:
            continue
        seen_runs.add(run_id)
        user_rows.append({
            **_identity(session),
            "测评编号": run_id,
            "测评完成时间": session.get("run_completed_at", ""),
            "任务顺序": session.get("task_order_code", ""),
            "研究纳入状态": session.get("research_inclusion_status", ""),
        })

    original_rows = (
        [] if accepted_only else
        _original_transcript_rows(sessions, transcript_versions, transcript_segments)
    )
    ai_rows = (
        [] if accepted_only else
        _candidate_rows(sessions, extraction_jobs, extraction_candidates, reviewed_only=False)
    )
    reviewed_rows = _candidate_rows(
        sessions, extraction_jobs, extraction_candidates,
        reviewed_only=True, reviewed_after=reviewed_after,
    )
    if accepted_only:
        accepted_session_ids = {
            str(row.get("任务会话编号", "")) for row in reviewed_rows
        }
        sessions = [
            session for session in sessions
            if str(session.get("session_id", "")) in accepted_session_ids
        ]
        user_rows.clear()
        seen_runs.clear()
        for session in sessions:
            run_id = str(session.get("run_id", ""))
            if run_id in seen_runs:
                continue
            seen_runs.add(run_id)
            user_rows.append({
                **_identity(session),
                "测评编号": run_id,
                "测评完成时间": session.get("run_completed_at", ""),
                "任务顺序": session.get("task_order_code", ""),
                "研究纳入状态": session.get("research_inclusion_status", ""),
            })
    latest_job_ids = _latest_candidate_job_ids(extraction_jobs, extraction_candidates)
    latest_candidates = [
        item for item in extraction_candidates
        if str(item.get("job_id", "")) in latest_job_ids
    ]
    pending_count = sum(1 for item in latest_candidates if item.get("review_status") == "pending")
    reviewed_count = sum(1 for item in latest_candidates if item.get("review_status") in {"accepted", "rejected"})
    effective_review_complete = (
        bool(review_complete) if review_complete is not None else pending_count == 0
    )

    file_manifest: list[dict[str, Any]] = []
    session_map = {str(item.get("session_id", "")): item for item in sessions}
    package_title = (
        "元认知测评已接受候选数据包说明"
        if accepted_only else
        "元认知测评录音与转录数据包说明"
        if include_audio else
        "元认知测评转录与候选文本数据包说明"
    )
    package_scope_note = (
        "本轻量数据包不包含原始录音、原始转录、待复核或已排除候选，可快速生成。\r\n"
        if accepted_only else
        ("01_原始录音：按“账号_用户名_问卷填写姓名”分文件夹保存每项任务的 WAV 录音；“录音文件清单.csv”包含声音信号检测与文件校验值。\r\n" if include_audio else "本次按用户选择不包含原始录音，仅导出转录与候选文本。\r\n")
        +
        "02_原始转录文本：每项任务一行，ASR 与人工转录均写入同一个“原转录文本”列；“原转录来源”列会额外标记服务端 ASR、人工转录（非 ASR）或浏览器实时转录。\r\n"
        "03_AI筛选后的转录文本：导出每项任务最新且实际生成候选的抽取版本中的 AI 候选，包括后来被人工接受、排除或仍待复核的内容。\r\n"
    )
    package_range_note = (
        f"本次为增量导出；04 文件夹仅包含人工复核时间晚于 {reviewed_after} 的新接受候选，"
        "其余已选目录保留相关任务上下文，便于核对原始文本及可选录音。\r\n"
        if reviewed_after else
        "本次仅导出当前全部已接受候选。\r\n"
        if accepted_only else
        "本次为完整导出；04 文件夹包含当前全部已接受候选。\r\n"
    )
    with _atomic_zip(target) as archive:
        archive.writestr(
            "00_用户信息/用户信息.csv",
            _csv_bytes(
                user_rows,
                identity_fields + ["测评编号", "测评完成时间", "任务顺序", "研究纳入状态"],
            ),
        )
        if not accepted_only:
            archive.writestr(
                "02_原始转录文本/原始转录文本.csv",
                _csv_bytes(
                    original_rows,
                    identity_fields + task_fields + ["原转录来源", "原转录版本号", "原转录文本"],
                ),
            )
            archive.writestr(
                "03_AI筛选后的转录文本/AI筛选后的转录文本.csv",
                _csv_bytes(
                    ai_rows,
                    identity_fields + task_fields + [
                        "抽取版本", "模型", "提示词版本", "候选序号",
                        "开始时间（毫秒）", "结束时间（毫秒）", "来源类型",
                        "AI筛选原文", "AI清洗后文本", "当前人工复核状态",
                    ],
                ),
            )
        archive.writestr(
            "04_AI筛选并人工校对的文本/AI筛选并人工校对的文本.csv",
            _csv_bytes(
                reviewed_rows,
                identity_fields + task_fields + [
                    "抽取版本", "模型", "提示词版本", "候选序号",
                    "开始时间（毫秒）", "结束时间（毫秒）", "来源类型",
                    "AI筛选原文", "人工校对后文本", "人工复核结果",
                    "人工校对人编号", "人工校对备注", "人工校对时间",
                ],
            ),
        )

        for item in (audio_files if include_audio else []):
            if item.get("kind") != "canonical_wav":
                continue
            try:
                source = resolve_audio_path(audio_root, str(item["storage_path"]))
                session = session_map.get(str(item.get("session_id", "")), {})
                participant = "_".join((
                    _safe_component(session.get("username"), "无账号"),
                    _safe_component(session.get("name"), "无用户名"),
                    _safe_component(session.get("questionnaire_participant_name"), "未填写问卷姓名"),
                ))
                task = "_".join((
                    f"任务{_safe_component(session.get('sequence_no'), '未知')}",
                    _safe_component(session.get("task_title"), "未命名任务"),
                    _safe_component(str(item.get("session_id", ""))[:8], "未知会话"),
                ))
                archive_path = f"01_原始录音/{participant}/{task}.wav"
                archive.write(source, archive_path, compress_type=zipfile.ZIP_STORED)
                has_stored_signal = item.get("contains_signal") is not None
                signal = ({
                    "contains_signal": item.get("contains_signal"),
                    "rms_dbfs": item.get("rms_dbfs"),
                    "peak_dbfs": item.get("peak_dbfs"),
                } if has_stored_signal else analyze_wav_signal(source))
                file_manifest.append({
                    "账号": session.get("username", ""),
                    "用户名": session.get("name", ""),
                    "问卷填写姓名": session.get("questionnaire_participant_name", ""),
                    "任务名称": session.get("task_title", ""),
                    "任务会话编号": item.get("session_id", ""),
                    "录音文件路径": archive_path,
                    "文件大小（字节）": item.get("size_bytes") or source.stat().st_size,
                    "SHA256校验值": item.get("sha256") or _sha256(source),
                    "检测到声音信号": signal.get("contains_signal", False),
                    "平均响度（dBFS）": signal.get("rms_dbfs", ""),
                    "峰值响度（dBFS）": signal.get("peak_dbfs", ""),
                })
            except (OSError, ResearchExportError, wave.Error) as error:
                warnings.append({
                    "session_id": str(item.get("session_id", "")),
                    "storage_path": str(item.get("storage_path", "")),
                    "message": str(error),
                })

        if include_audio:
            archive.writestr(
                "01_原始录音/录音文件清单.csv",
                _csv_bytes(
                    file_manifest,
                    [
                        "账号", "用户名", "问卷填写姓名", "任务名称", "任务会话编号",
                        "录音文件路径", "文件大小（字节）", "SHA256校验值",
                        "检测到声音信号", "平均响度（dBFS）", "峰值响度（dBFS）",
                    ],
                ),
            )
        archive.writestr(
            "导出数据说明.txt",
            (
                package_title + "\r\n"
                + "================================\r\n\r\n"
                "本数据包包含可直接识别参与者的信息，仅限获授权的研究人员使用。\r\n"
                "所有 CSV 均使用 UTF-8 BOM 编码，可直接使用 Microsoft Excel 打开。\r\n\r\n"
                "00_用户信息：用户身份索引。包含账号、系统用户名、问卷填写姓名、班级和测评编号。\r\n"
                + package_scope_note
                +
                "04_AI筛选并人工校对的文本：仅导出最新抽取版本中已经人工接受的候选，"
                "以“人工校对后文本”为正式复核文本；人工补充的遗漏片段会标记为“人工补充”。\r\n\r\n"
                "用户信息列固定放在所有文本 CSV 的最前方，顺序为：账号、用户名、问卷填写姓名、班级。\r\n"
                "目录会根据本次选择生成；未勾选录音或选择轻量已接受候选时，不会创建未纳入内容的目录。\r\n"
                "若已生成的文本 CSV 只有表头，表示当前没有符合该阶段条件的记录，并非导出失败。\r\n"
                + package_range_note
            ).encode("utf-8-sig"),
        )

        manifest = {
            "schema_version": "2026.5",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pseudonymized": False,
            "contains_direct_identifiers": True,
            "user_run_count": len(user_rows),
            "session_count": len(sessions),
            "audio_file_count": len(file_manifest),
            "original_transcript_count": len(original_rows),
            "ai_filtered_count": len(ai_rows),
            "human_reviewed_count": len(reviewed_rows),
            "candidate_pending_count": pending_count,
            "candidate_reviewed_count": reviewed_count,
            "review_complete": effective_review_complete,
            "reviewed_after": reviewed_after,
            "accepted_only": accepted_only,
            "include_audio": include_audio,
            "audio_files": file_manifest,
            "warnings": warnings,
        }
        archive.writestr(
            "导出清单.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    return {
        "session_count": len(sessions),
        "audio_file_count": len(file_manifest),
        "original_transcript_count": len(original_rows),
        "ai_filtered_count": len(ai_rows),
        "human_reviewed_count": len(reviewed_rows),
        "candidate_pending_count": pending_count,
        "candidate_reviewed_count": reviewed_count,
        "review_complete": effective_review_complete,
        "warning_count": len(warnings),
    }
