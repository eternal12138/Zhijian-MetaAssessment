"""Shared session -> task/run -> cohort evidence contract for all three roles.

Queries are batched, and do not load audio or transcript/candidate text. Never
divide a newer set of labels by an older/differently scoped dialogue count.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asr import TranscriptVersion
from app.models.extraction import ExtractionCandidate
from app.models.report import MeasurementCorrection
from app.models.research import CodingBatch, CodingUnit
from app.models.session import AssessmentSession, TranscriptSegment
from app.services.metacognition_distribution import aggregate_distribution, empty_counts, normalize_dimension
from app.services.evidence_selection import latest_current_extractions, CLASSIFIED_STATUSES


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
    evidence = []
    def remember(item, label, source):
        evidence.append({
            "segmentId": item.id, "dimension": normalize_dimension(label), "source": source,
            "excerpt": (getattr(item, "clean_text", None) or getattr(item, "segment", "") or ""),
            "started_at_ms": getattr(item, "started_at_ms", None),
            "ended_at_ms": getattr(item, "ended_at_ms", None),
        })
    if correction is not None:
        counts.update(correction.dimension_counts)
        denominator = correction.effective_dialogue_count
        source = denominator_source = "admin_upload"
        versions.append(f"correction:{correction.id}")
        for index, dialogue in enumerate(getattr(correction, "dialogues", None) or []):
            evidence.append({"segmentId": f"{correction.id}:{index}", "dimension": normalize_dimension(dialogue["label"]),
                             "source": "admin_upload", "excerpt": dialogue["text"]})
    else:
        accepted = [c for c in candidates if c.review_status == "accepted"]
        expert = {u.candidate_id: u for u in units if u.candidate_id}
        is_reviewed = (
            # Supersession replaces the job-level review flag; retained accepted
            # decisions still define the reviewed set if none remain pending.
            job is not None and job.status in {"reviewed", "superseded"} and accepted
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
                    remember(unit, label, "expert_consensus")
                elif candidate.classification_status in CLASSIFIED_STATUSES and (
                    normalize_dimension(candidate.predicted_dimension) is not None
                    or candidate.predicted_dimension in {"non_meta", "non_metacognitive", "0"}
                ):
                    label = candidate.predicted_dimension
                    used_sources.add("production_model")
                    remember(candidate, label, "production_model")
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
                remember(unit, unit.final_dimension, "expert_consensus")
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
                    remember(candidate, candidate.predicted_dimension, "production_model")
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
        "evidence": evidence,
        # Pipeline coverage tracks actual current candidates independently from
        # the authoritative measurement (which may come from an admin upload).
        "classification_eligible_count": sum(c.review_status in {"accepted", "pending"} for c in candidates),
        "classification_completed_count": sum(
            c.review_status in {"accepted", "pending"}
            and c.classification_status in {"classified", "classified_with_fallback"}
            and normalize_dimension(c.predicted_dimension) is not None for c in candidates
        ),
    }


async def load_session_evidence(run_ids: list[str], db: AsyncSession, *, include_text: bool = False):
    """One source resolution per session, independent of requesting role."""
    if not run_ids:
        return [], {}
    sessions = list((await db.scalars(select(AssessmentSession).where(
        AssessmentSession.run_id.in_(run_ids),
    ).order_by(AssessmentSession.sequence_no, AssessmentSession.id))).all())
    session_ids = [s.id for s in sessions]
    if not session_ids:
        return sessions, {}
    # Use the same version policy as AI evaluation; pending/failed attempts are
    # reported separately instead of erasing the last successful extraction.
    chosen = latest_current_extractions(session_ids)
    latest_jobs = {j.session_id: j for j in (await db.execute(select(
        chosen.c.job_id.label("id"), chosen.c.session_id, chosen.c.status, chosen.c.generation_no,
    ))).all()}
    newest = latest_current_extractions(session_ids, successful_only=False)
    latest_attempts = {j.session_id: j for j in (await db.execute(select(newest))).all()}
    versions = (await db.execute(select(
        TranscriptVersion.id, TranscriptVersion.session_id, TranscriptVersion.is_authoritative,
    ).where(TranscriptVersion.session_id.in_(session_ids)))).all()
    authoritative_ids = {v.id for v in versions if v.is_authoritative}
    authoritative_sessions = {v.session_id for v in versions if v.is_authoritative}
    version_counts = defaultdict(int)
    for version in versions:
        version_counts[version.session_id] += 1
    candidates_by_job = defaultdict(list)
    if latest_jobs:
        candidates = (await db.execute(select(
            ExtractionCandidate.id, ExtractionCandidate.extraction_job_id,
            ExtractionCandidate.review_status, ExtractionCandidate.predicted_dimension,
            ExtractionCandidate.classification_status,
            ExtractionCandidate.classifier_version,
            (func.length(func.coalesce(ExtractionCandidate.classification_error, "")) > 0).label("classification_has_error"),
        ).where(ExtractionCandidate.extraction_job_id.in_([j.id for j in latest_jobs.values()])))).all()
        for candidate in candidates:
            candidates_by_job[candidate.extraction_job_id].append(candidate)
        if include_text:
            candidates_by_job.clear()
            for candidate in (await db.scalars(select(ExtractionCandidate).where(
                ExtractionCandidate.extraction_job_id.in_([j.id for j in latest_jobs.values()])
            ).execution_options(populate_existing=True))).all():
                candidate.classification_has_error = bool(candidate.classification_error)
                candidates_by_job[candidate.extraction_job_id].append(candidate)

    # Select the latest batch per SESSION, not one batch for the entire run or
    # a union of batch ids that can accidentally include other runs' older units.
    unit_rows = (await db.execute(select(
        CodingUnit.id, CodingUnit.session_id, CodingUnit.batch_id,
        CodingUnit.candidate_id, CodingUnit.final_dimension,
        CodingUnit.transcript_segment_id,
        ExtractionCandidate.extraction_job_id, ExtractionCandidate.review_status,
        TranscriptSegment.transcript_version_id,
    ).join(CodingBatch, CodingBatch.id == CodingUnit.batch_id)
    .outerjoin(ExtractionCandidate, ExtractionCandidate.id == CodingUnit.candidate_id)
    .outerjoin(TranscriptSegment, TranscriptSegment.id == CodingUnit.transcript_segment_id).where(
        CodingUnit.session_id.in_(session_ids), CodingBatch.status == "completed",
        CodingUnit.status.in_(("agreed", "adjudicated")),
    ).order_by(CodingBatch.completed_at.desc(), CodingBatch.created_at.desc(), CodingBatch.id.desc()))).all()
    latest_batches = {}
    units_by_session = defaultdict(list)
    for unit in unit_rows:
        job = latest_jobs.get(unit.session_id)
        if unit.candidate_id:
            if job is None or unit.extraction_job_id != job.id or unit.review_status == "rejected":
                continue
        elif unit.transcript_segment_id:
            if unit.transcript_version_id not in authoritative_ids:
                continue
        elif version_counts[unit.session_id] > 1:
            # Legacy unlinked units cannot prove which revised text they coded.
            continue
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
    if include_text:
        unit_ids = [u.id for rows in units_by_session.values() for u in rows]
        full_units = {u.id: u for u in (await db.scalars(select(CodingUnit).where(CodingUnit.id.in_(unit_ids))
                     .execution_options(populate_existing=True))).all()} if unit_ids else {}
        units_by_session = {sid: [full_units[u.id] for u in rows] for sid, rows in units_by_session.items()}
        correction_ids = [c.id for c in latest_corrections.values()]
        latest_corrections = {c.session_id: c for c in (await db.scalars(select(MeasurementCorrection).where(
            MeasurementCorrection.id.in_(correction_ids)))).all()} if correction_ids else {}
    resolved = {}
    for session in sessions:
        job = latest_jobs.get(session.id)
        candidates = candidates_by_job.get(job.id, ()) if job else ()
        resolved[session.id] = row = resolve_session_evidence(
            job=job, candidates=candidates,
            units=units_by_session.get(session.id, ()), correction=latest_corrections.get(session.id),
        )
        attempt = latest_attempts.get(session.id)
        row["evidence_state"] = describe_session_state(
            session, row, job, attempt, candidates, session.id in authoritative_sessions,
        )
        row["evidence_status_counts"] = {row["evidence_state"]["status"]: 1}
        row["retained_previous_count"] = int(row["evidence_state"]["using_previous_extraction"])
    return sessions, resolved


def describe_session_state(session, row, job, attempt, candidates, has_transcript):
    """No text or peer identity is exposed; cohort APIs only aggregate counts."""
    eligible = [c for c in candidates if c.review_status in {"accepted", "pending"}]
    ready = row["effective_dialogue_count"] > 0 and (sum(row["counts"].values()) > 0 or row["unclassified_count"] == 0)
    if ready:
        status = "ready" if row["classification_completed_count"] == len(eligible) or row["source"] in {"admin_upload", "expert_consensus"} else "classification_partial"
    elif not has_transcript:
        status = "no_transcript"
    elif job is None:
        status = "extraction_" + attempt.status if attempt else "awaiting_extraction"
    elif not candidates:
        status = "no_candidates"
    elif not eligible:
        status = "all_rejected"
    elif any(c.classification_status == "failed" or (
        c.classification_status not in CLASSIFIED_STATUSES and c.classification_has_error
    ) for c in eligible):
        status = "classification_failed"
    elif all(c.classification_status in CLASSIFIED_STATUSES for c in eligible) and not sum(row["counts"].values()):
        status = "no_three_class_labels"
    else:
        status = "classification_pending"
    return {
        "session_id": session.id, "task_id": session.task_id, "status": status,
        "extraction_generation": job.generation_no if job else None,
        "latest_generation": attempt.generation_no if attempt else None,
        "latest_extraction_status": attempt.status if attempt else None,
        "using_previous_extraction": bool(job and attempt and job.id != attempt.job_id and row["source"] not in {"admin_upload", "expert_consensus"}),
        "model_versions": sorted({c.classifier_version for c in eligible if c.classifier_version and c.classification_status in CLASSIFIED_STATUSES}),
    }


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
    profile["session_states"] = [resolved[s.id]["evidence_state"] for s in selected if "evidence_state" in resolved[s.id]]
    for key in ("classification_eligible_count", "classification_completed_count"):
        profile[key] = sum(resolved[s.id].get(key, 0) for s in selected)
    return profile


async def load_run_evidence(run_ids: list[str], db: AsyncSession):
    sessions, resolved = await load_session_evidence(run_ids, db)
    by_run = defaultdict(list)
    for session in sessions:
        by_run[session.run_id].append(session)
    return {run_id: aggregate_session_evidence(rows, resolved) for run_id, rows in by_run.items()}
