"""Shared session -> task/run -> cohort evidence contract for all three roles.

Queries are batched, and do not load audio or transcript/candidate text. Never
divide a newer set of labels by an older/differently scoped dialogue count.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asr import TranscriptVersion
from app.models.extraction import ExtractionCandidate, ExtractionJob
from app.models.report import MeasurementCorrection
from app.models.research import CodingBatch, CodingUnit
from app.models.session import AssessmentSession
from app.services.metacognition_distribution import aggregate_distribution, empty_counts, normalize_dimension


def resolve_session_evidence(*, job=None, candidates=(), units=(), correction=None):
    """Resolve a single session. Admin correction explicitly supersedes prior data.

    A reviewed extraction set defines the denominator; expert decisions override
    model labels for the SAME candidates only. Pending/failed classification never
    becomes a fabricated zero label. Without a reviewed set, completed expert
    units are usable; otherwise actual classified labels provide a marked fallback.
    """
    counts = empty_counts()
    unknown = 0
    versions = []
    if correction is not None:
        counts.update(correction.dimension_counts)
        denominator = correction.effective_dialogue_count
        source = denominator_source = "admin_upload"
        versions.append(f"correction:{correction.id}")
    else:
        accepted = [c for c in candidates if c.review_status == "accepted"]
        expert = {u.candidate_id: u for u in units if u.candidate_id}
        is_reviewed = (
            job is not None and job.status == "reviewed" and accepted
            and not any(c.review_status == "pending" for c in candidates)
        )
        if is_reviewed:
            denominator = len(accepted)
            denominator_source = "human_review"
            used_sources = set()
            for candidate in accepted:
                unit = expert.get(candidate.id)
                if unit is not None:
                    label = unit.final_dimension
                    used_sources.add("expert_consensus")
                elif candidate.classification_status in {"classified", "classified_with_fallback"}:
                    label = candidate.predicted_dimension
                    used_sources.add("production_model")
                else:
                    label = None
                    unknown += 1
                dimension = normalize_dimension(label)
                if dimension:
                    counts[dimension] += 1
            source = next(iter(used_sources)) if len(used_sources) == 1 else "hybrid" if used_sources else "none"
        elif units:
            denominator = len(units)
            denominator_source = source = "expert_consensus"
            for unit in units:
                dimension = normalize_dimension(unit.final_dimension)
                if dimension:
                    counts[dimension] += 1
        else:
            for candidate in candidates:
                if candidate.review_status not in {"accepted", "pending"}:
                    continue
                if candidate.classification_status not in {"classified", "classified_with_fallback"}:
                    continue
                dimension = normalize_dimension(candidate.predicted_dimension)
                if dimension:
                    counts[dimension] += 1
            denominator = sum(counts.values())
            denominator_source = "label_total_fallback"
            source = "production_model" if denominator else "none"
        if job:
            versions.append(f"extraction:{job.id}")
        versions.extend(f"batch:{u.batch_id}" for u in units)
    return {
        "counts": counts, "source": source,
        "effective_dialogue_count": denominator,
        "denominator_breakdown": {denominator_source: denominator} if denominator else {},
        "unclassified_count": unknown,
        "versions": sorted(set(versions)),
        # Pipeline coverage tracks actual current candidates independently from
        # the authoritative measurement (which may come from an admin upload).
        "classification_eligible_count": sum(c.review_status in {"accepted", "pending"} for c in candidates),
        "classification_completed_count": sum(
            c.review_status in {"accepted", "pending"}
            and c.classification_status in {"classified", "classified_with_fallback"}
            and normalize_dimension(c.predicted_dimension) is not None for c in candidates
        ),
    }


async def load_session_evidence(run_ids: list[str], db: AsyncSession):
    """One source resolution per session, independent of requesting role."""
    if not run_ids:
        return [], {}
    sessions = list((await db.scalars(select(AssessmentSession).where(
        AssessmentSession.run_id.in_(run_ids),
    ).order_by(AssessmentSession.sequence_no, AssessmentSession.id))).all())
    session_ids = [s.id for s in sessions]
    if not session_ids:
        return sessions, {}
    # Only the latest extraction of the currently authoritative transcript counts.
    jobs = (await db.execute(select(
        ExtractionJob.id, ExtractionJob.session_id, ExtractionJob.status,
    ).join(TranscriptVersion, TranscriptVersion.id == ExtractionJob.transcript_version_id).where(
        ExtractionJob.session_id.in_(session_ids), TranscriptVersion.is_authoritative.is_(True),
    ).order_by(ExtractionJob.generation_no.desc(), ExtractionJob.created_at.desc(), ExtractionJob.id.desc()))).all()
    latest_jobs = {}
    for job in jobs:
        latest_jobs.setdefault(job.session_id, job)
    candidates_by_job = defaultdict(list)
    if latest_jobs:
        candidates = (await db.execute(select(
            ExtractionCandidate.id, ExtractionCandidate.extraction_job_id,
            ExtractionCandidate.review_status, ExtractionCandidate.predicted_dimension,
            ExtractionCandidate.classification_status,
        ).where(ExtractionCandidate.extraction_job_id.in_([j.id for j in latest_jobs.values()])))).all()
        for candidate in candidates:
            candidates_by_job[candidate.extraction_job_id].append(candidate)

    # Select the latest batch per SESSION, not one batch for the entire run or
    # a union of batch ids that can accidentally include other runs' older units.
    unit_rows = (await db.execute(select(
        CodingUnit.id, CodingUnit.session_id, CodingUnit.batch_id,
        CodingUnit.candidate_id, CodingUnit.final_dimension,
    ).join(CodingBatch, CodingBatch.id == CodingUnit.batch_id).where(
        CodingUnit.session_id.in_(session_ids), CodingBatch.status == "completed",
        CodingUnit.status.in_(("agreed", "adjudicated")),
    ).order_by(CodingBatch.completed_at.desc(), CodingBatch.created_at.desc(), CodingBatch.id.desc()))).all()
    latest_batches = {}
    units_by_session = defaultdict(list)
    for unit in unit_rows:
        if latest_batches.setdefault(unit.session_id, unit.batch_id) == unit.batch_id:
            units_by_session[unit.session_id].append(unit)

    corrections = (await db.execute(select(
        MeasurementCorrection.id, MeasurementCorrection.session_id,
        MeasurementCorrection.dimension_counts, MeasurementCorrection.effective_dialogue_count,
    ).where(MeasurementCorrection.session_id.in_(session_ids)).order_by(
        MeasurementCorrection.version_no.desc(), MeasurementCorrection.id.desc(),
    ))).all()
    latest_corrections = {}
    for correction in corrections:
        latest_corrections.setdefault(correction.session_id, correction)
    resolved = {}
    for session in sessions:
        job = latest_jobs.get(session.id)
        resolved[session.id] = resolve_session_evidence(
            job=job, candidates=candidates_by_job.get(job.id, ()) if job else (),
            units=units_by_session.get(session.id, ()), correction=latest_corrections.get(session.id),
        )
    return sessions, resolved


def aggregate_session_evidence(sessions, resolved, *, task_id=None):
    selected = [s for s in sessions if task_id is None or s.task_id == task_id]
    profile = aggregate_distribution([s.id for s in selected], resolved, scope="run", label="测评")
    versions = sorted({v for s in selected for v in resolved[s.id].get("versions", [])})
    # Bounded fingerprint even when a run contains many tasks/versions.
    fingerprint = json.dumps({"versions": versions, "counts": profile["counts"],
                              "denominator": profile["denominator_breakdown"],
                              "unclassified": profile["unclassified_count"]}, sort_keys=True)
    profile["data_version"] = "evidence-v2:" + sha256(fingerprint.encode()).hexdigest()[:32]
    profile["source"] = profile["primary_source"]
    for key in ("classification_eligible_count", "classification_completed_count"):
        profile[key] = sum(resolved[s.id].get(key, 0) for s in selected)
    return profile


async def load_run_evidence(run_ids: list[str], db: AsyncSession):
    sessions, resolved = await load_session_evidence(run_ids, db)
    by_run = defaultdict(list)
    for session in sessions:
        by_run[session.run_id].append(session)
    return {run_id: aggregate_session_evidence(rows, resolved) for run_id, rows in by_run.items()}
