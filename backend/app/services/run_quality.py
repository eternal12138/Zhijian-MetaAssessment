"""Deterministic quality gates for formal research inclusion."""
from __future__ import annotations

from typing import Any

from app.models.protocol import AssessmentRun
from app.models.research import RunQualityReview


def _check(key: str, label: str, status: str, message: str) -> dict[str, str]:
    return {"key": key, "label": label, "status": status, "message": message}


def evaluate_run_quality(
    run: AssessmentRun,
    expected_questionnaire_items: int,
    review: RunQualityReview | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    sessions = sorted(run.sessions or [], key=lambda item: item.sequence_no)
    completed_sessions = [item for item in sessions if item.status == "completed"]
    checks.append(_check(
        "protocol_complete", "标准流程完整",
        "pass" if run.status == "completed" and len(completed_sessions) == 2 else "fail",
        f"已完成 {len(completed_sessions)}/2 个任务会话",
    ))

    sessions_with_audio = sum(bool(item.audio_chunks) for item in sessions)
    checks.append(_check(
        "audio_present", "录音分片完整",
        "pass" if len(sessions) == 2 and sessions_with_audio == 2 else "fail",
        f"{sessions_with_audio}/2 个任务包含录音分片",
    ))

    canonical_count = 0
    short_audio: list[int] = []
    authoritative_count = 0
    short_transcript: list[int] = []
    for session in sessions:
        jobs = sorted(
            session.asr_jobs or [],
            key=lambda item: (item.created_at, item.id),
        )
        completed_jobs = [
            item for item in jobs
            if item.status == "completed" and item.canonical_audio_path
        ]
        if completed_jobs:
            canonical_count += 1
            duration = max(item.audio_duration_ms or 0 for item in completed_jobs)
            if duration < 15_000:
                short_audio.append(session.sequence_no)
        authoritative = next(
            (
                item for item in (session.transcript_versions or [])
                if item.is_authoritative and item.full_text.strip()
            ),
            None,
        )
        if authoritative:
            authoritative_count += 1
            if len(authoritative.full_text.strip()) < 20:
                short_transcript.append(session.sequence_no)

    checks.append(_check(
        "canonical_audio", "标准音频可用",
        "pass" if len(sessions) == 2 and canonical_count == 2 else "fail",
        f"{canonical_count}/2 个任务已生成可播放 WAV 并完成服务端识别",
    ))
    checks.append(_check(
        "audio_duration", "录音时长合理",
        "warning" if short_audio else "pass",
        f"任务 {','.join(map(str, short_audio))} 的录音少于 15 秒" if short_audio else "两个任务录音时长均达到 15 秒",
    ))
    checks.append(_check(
        "authoritative_transcript", "权威转录可用",
        "pass" if len(sessions) == 2 and authoritative_count == 2 else "fail",
        f"{authoritative_count}/2 个任务具有非空权威转录",
    ))
    checks.append(_check(
        "transcript_length", "转录内容合理",
        "warning" if short_transcript else "pass",
        f"任务 {','.join(map(str, short_transcript))} 的权威转录少于 20 字" if short_transcript else "权威转录达到最低内容长度",
    ))

    answer_count = len({item.item_id for item in run.questionnaire_responses or []})
    questionnaire_ok = (
        not run.questionnaire_enabled
        or (expected_questionnaire_items > 0 and answer_count == expected_questionnaire_items)
    )
    checks.append(_check(
        "questionnaire_complete", "问卷完整",
        "pass" if questionnaire_ok else "fail",
        "本次协议未启用问卷" if not run.questionnaire_enabled else f"已作答 {answer_count}/{expected_questionnaire_items} 题",
    ))

    automatic_status = (
        "failed" if any(item["status"] == "fail" for item in checks)
        else "warning" if any(item["status"] == "warning" for item in checks)
        else "passed"
    )
    decision = review.decision if review else "automatic"
    if decision == "excluded":
        effective_status = "excluded"
    elif decision == "included":
        effective_status = "included_override" if automatic_status != "passed" else "included"
    else:
        effective_status = {
            "passed": "eligible",
            "warning": "review_required",
            "failed": "ineligible",
        }[automatic_status]
    return {
        "automatic_status": automatic_status,
        "effective_status": effective_status,
        "decision": decision,
        "checks": checks,
    }


def quality_allows_analysis(quality: dict[str, Any]) -> bool:
    return quality["effective_status"] in {"eligible", "included", "included_override"}
