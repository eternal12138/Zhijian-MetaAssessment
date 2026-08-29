"""Shared current-transcript/extraction policy for inference and all radars."""
from sqlalchemy import and_, func, or_, select

from app.models.asr import TranscriptVersion
from app.models.extraction import ExtractionCandidate, ExtractionJob

SUCCESSFUL_EXTRACTIONS = ("completed", "reviewing", "reviewed")
CLASSIFIED_STATUSES = ("classified", "classified_with_fallback")
DIMENSION_ALIASES = {
    "monitoring": ("monitoring",),
    "controlDebugging": ("regulation", "control_regulation", "controldebugging", "control_debugging"),
    "evaluation": ("evaluation",),
}


def latest_current_extractions(session_ids=None, *, successful_only=True):
    """An unfinished attempt cannot replace successful evidence on the SAME text.

    A completed empty/unclassified extraction DOES replace the prior version.
    Never fall back across authoritative transcript versions.
    """
    statement = select(
        ExtractionJob.id.label("job_id"), ExtractionJob.session_id,
        ExtractionJob.status, ExtractionJob.generation_no, ExtractionJob.transcript_version_id,
        func.row_number().over(
            partition_by=ExtractionJob.session_id,
            order_by=(ExtractionJob.generation_no.desc(), ExtractionJob.created_at.desc(), ExtractionJob.id.desc()),
        ).label("rank_no"),
    ).join(TranscriptVersion, and_(
        TranscriptVersion.id == ExtractionJob.transcript_version_id,
        TranscriptVersion.session_id == ExtractionJob.session_id,
    )).where(TranscriptVersion.is_authoritative.is_(True))
    if successful_only:
        # enqueue_extraction marks prior jobs superseded BEFORE the new job
        # finishes. Recover successful history without changing stored status.
        # Superseded queued/failed attempts without completion evidence are not
        # successful versions; an empty successful extraction is still a version.
        has_candidates = select(ExtractionCandidate.id).where(
            ExtractionCandidate.extraction_job_id == ExtractionJob.id,
        ).exists()
        statement = statement.where(or_(
            ExtractionJob.status.in_(SUCCESSFUL_EXTRACTIONS),
            and_(ExtractionJob.status == "superseded", ExtractionJob.error_code.is_(None),
                 or_(ExtractionJob.completed_at.is_not(None), has_candidates)),
        ))
    if session_ids is not None:
        statement = statement.where(ExtractionJob.session_id.in_(session_ids))
    ranked = statement.subquery()
    return select(ranked).where(ranked.c.rank_no == 1).subquery()


def normalized_candidate_dimension():
    return func.replace(func.lower(func.trim(ExtractionCandidate.predicted_dimension)), "-", "_")


def valid_candidate_classification():
    return and_(
        ExtractionCandidate.review_status.in_(("accepted", "pending")),
        ExtractionCandidate.classification_status.in_(CLASSIFIED_STATUSES),
        normalized_candidate_dimension().in_(tuple(v for values in DIMENSION_ALIASES.values() for v in values)),
    )
