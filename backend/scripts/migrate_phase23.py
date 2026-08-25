"""Add composite indexes for high-volume review and data-governance queries."""
from __future__ import annotations

from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


INDEXES = (
    ("assessment_runs", "ix_runs_started_id", "started_at, id"),
    ("assessment_runs", "ix_runs_user_started", "user_id, started_at"),
    ("assessment_sessions", "ix_sessions_status_started", "status, start_time, id"),
    ("transcript_versions", "ix_transcript_authoritative_latest", "session_id, is_authoritative, version_no"),
    ("asr_jobs", "ix_asr_session_created", "session_id, created_at, id"),
    ("extraction_jobs", "ix_extraction_version_created", "transcript_version_id, created_at, id"),
    ("extraction_candidates", "ix_candidate_job_status", "extraction_job_id, review_status"),
)


def _index_exists(cursor, database: str, table: str, name: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s""",
        (database, table, name),
    )
    return bool(cursor.fetchone()[0])


def main() -> None:
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            for table, name, columns in INDEXES:
                if not _index_exists(cursor, settings.DB_NAME, table, name):
                    cursor.execute(f"ALTER TABLE {table} ADD INDEX {name} ({columns})")
        connection.commit()
        print("Phase 23 performance indexes migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
