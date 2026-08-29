"""Formal per-run metacognition behavior-proportion measurements."""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now_naive
from app.models.extraction import ExtractionCandidate
from app.models.protocol import AssessmentRun
from app.models.report import MetacognitionMeasurement
from app.services.metacognition_distribution import normalize_dimension
from app.services.metacognition_evidence import load_session_evidence, aggregate_session_evidence


DIMENSION_KEYS = ("monitoring", "controlDebugging", "evaluation")


def calculate_dimension_scores(
    dimensions: Iterable[object],
    effective_dialogue_count: int,
) -> tuple[dict[str, int], dict[str, float | None]]:
    """Count normalized final labels and divide each by all effective dialogue."""
    counts = {key: 0 for key in DIMENSION_KEYS}
    for raw_dimension in dimensions:
        dimension = normalize_dimension(raw_dimension)
        if dimension in counts:
            counts[dimension] += 1
    if effective_dialogue_count <= 0:
        return counts, {key: None for key in DIMENSION_KEYS}
    scores = {
        key: counts[key] / effective_dialogue_count
        for key in DIMENSION_KEYS
    }
    return counts, scores


def calculate_reviewed_candidate_scores(
    candidates: Iterable[ExtractionCandidate],
) -> tuple[int, dict[str, int], dict[str, float | None]]:
    """Use only candidates explicitly accepted by the current review workflow."""
    accepted = [candidate for candidate in candidates if candidate.review_status == "accepted"]
    counts, scores = calculate_dimension_scores(
        (candidate.predicted_dimension for candidate in accepted),
        len(accepted),
    )
    return len(accepted), counts, scores


def reviewed_candidate_source(transcript_sources: Iterable[str]) -> str:
    sources = set(transcript_sources)
    return (
        "uploaded_review"
        if sources.intersection({"human_corrected", "human_transcribed"})
        else "human_review"
    )




async def calculate_and_persist_measurement(
    run: AssessmentRun,
    db: AsyncSession,
    *,
    task_id: str | None = None,
    session_evidence=None,
) -> MetacognitionMeasurement:
    """Recalculate from current authority and upsert one scoped snapshot.

    Recalculation on read is intentional: a changed review/adjudication can never
    leave the student radar permanently attached to an obsolete snapshot.
    """
    if run.status != "completed" or run.completed_at is None:
        raise ValueError("完整测评尚未结束，不能计算三维测量分数")

    if session_evidence is None:
        session_evidence = await load_session_evidence([run.id], db)
    all_sessions, resolved = session_evidence
    sessions = [s for s in all_sessions if s.run_id == run.id and (task_id is None or s.task_id == task_id)]
    if task_id is not None and not sessions:
        raise ValueError("该任务不属于当前测评轮次")
    task_ids = list(dict.fromkeys(session.task_id for session in sessions))
    scope_type = "task" if task_id is not None else "run"
    scope_key = f"task:{task_id}" if task_id is not None else "run"

    profile = aggregate_session_evidence(sessions, resolved, task_id=task_id)
    effective_dialogue_count = profile["effective_dialogue_count"]
    counts = profile["counts"]
    scores = {
        key: counts[key] / effective_dialogue_count if profile["score_available"] else None
        for key in DIMENSION_KEYS
    }
    source = profile["primary_source"]
    data_version = profile["data_version"]
    measurement = await db.scalar(
        select(MetacognitionMeasurement).where(
            MetacognitionMeasurement.run_id == run.id,
            MetacognitionMeasurement.scope_key == scope_key,
        )
    )
    if measurement is None:
        measurement = MetacognitionMeasurement(
            user_id=run.user_id,
            run_id=run.id,
            scope_type=scope_type,
            scope_key=scope_key,
            task_id=task_id,
            completed_at=run.completed_at,
        )
        db.add(measurement)

    measurement.user_id = run.user_id
    measurement.scope_type = scope_type
    measurement.scope_key = scope_key
    measurement.task_id = task_id
    measurement.task_ids = task_ids
    measurement.effective_dialogue_count = effective_dialogue_count
    measurement.monitoring_count = counts["monitoring"]
    measurement.control_debugging_count = counts["controlDebugging"]
    measurement.evaluation_count = counts["evaluation"]
    measurement.monitoring_score = scores["monitoring"]
    measurement.control_debugging_score = scores["controlDebugging"]
    measurement.evaluation_score = scores["evaluation"]
    measurement.score_available = profile["score_available"]
    # Response-only provenance, recalculated alongside the persisted snapshot.
    measurement.denominator_breakdown = profile["denominator_breakdown"]
    measurement.fallback_dialogue_count = profile["fallback_dialogue_count"]
    measurement.unclassified_count = profile["unclassified_count"]
    measurement.evidence_status_counts = profile["evidence_status_counts"]
    measurement.retained_previous_count = profile["retained_previous_count"]
    measurement.session_states = profile["session_states"]
    measurement.source = source
    measurement.data_version = data_version
    measurement.calculated_at = utc_now_naive()
    measurement.completed_at = run.completed_at
    await db.flush()
    return measurement
