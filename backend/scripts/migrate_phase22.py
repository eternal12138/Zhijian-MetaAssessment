"""Add immutable candidate revisions and repeatable extraction generations."""
from __future__ import annotations

from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


def _column_exists(cursor, database: str, table: str, column: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s""",
        (database, table, column),
    )
    return bool(cursor.fetchone()[0])


def _index_exists(cursor, database: str, table: str, index_name: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s""",
        (database, table, index_name),
    )
    return bool(cursor.fetchone()[0])


def _index_columns(cursor, database: str, table: str, index_name: str) -> list[str]:
    cursor.execute(
        """SELECT COLUMN_NAME FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s
        ORDER BY SEQ_IN_INDEX""",
        (database, table, index_name),
    )
    return [row[0] for row in cursor.fetchall()]


def _constraint_exists(cursor, database: str, table: str, name: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s""",
        (database, table, name),
    )
    return bool(cursor.fetchone()[0])


def _table_exists(cursor, database: str, table: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s""",
        (database, table),
    )
    return bool(cursor.fetchone()[0])


def main() -> None:
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME,
        charset="utf8mb4", autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            if not _column_exists(cursor, settings.DB_NAME, "extraction_jobs", "generation_no"):
                cursor.execute(
                    """ALTER TABLE extraction_jobs ADD COLUMN
                    generation_no INT NOT NULL DEFAULT 1 AFTER prompt_version"""
                )
            if not _column_exists(cursor, settings.DB_NAME, "extraction_jobs", "supersedes_job_id"):
                cursor.execute(
                    """ALTER TABLE extraction_jobs ADD COLUMN
                    supersedes_job_id VARCHAR(36) NULL AFTER generation_no"""
                )
            expected_unique = [
                "transcript_version_id", "extractor_version", "prompt_version", "generation_no"
            ]
            current_unique = _index_columns(
                cursor, settings.DB_NAME, "extraction_jobs", "uq_extraction_version_config"
            )
            if current_unique != expected_unique:
                if current_unique:
                    cursor.execute(
                        "ALTER TABLE extraction_jobs DROP INDEX uq_extraction_version_config"
                    )
                cursor.execute(
                    """ALTER TABLE extraction_jobs ADD UNIQUE KEY uq_extraction_version_config
                    (transcript_version_id, extractor_version, prompt_version, generation_no)"""
                )
            if not _index_exists(
                cursor, settings.DB_NAME, "extraction_jobs", "ix_extraction_jobs_supersedes_job_id"
            ):
                cursor.execute(
                    """ALTER TABLE extraction_jobs ADD KEY
                    ix_extraction_jobs_supersedes_job_id (supersedes_job_id)"""
                )
            if not _constraint_exists(
                cursor, settings.DB_NAME, "extraction_jobs", "fk_extraction_job_supersedes"
            ):
                cursor.execute(
                    """ALTER TABLE extraction_jobs ADD CONSTRAINT fk_extraction_job_supersedes
                    FOREIGN KEY (supersedes_job_id) REFERENCES extraction_jobs(id)
                    ON DELETE SET NULL"""
                )

            if not _table_exists(cursor, settings.DB_NAME, "extraction_candidate_revisions"):
                cursor.execute(
                    """CREATE TABLE extraction_candidate_revisions (
                        id VARCHAR(36) NOT NULL,
                        candidate_id VARCHAR(36) NOT NULL,
                        extraction_job_id VARCHAR(36) NOT NULL,
                        session_id VARCHAR(36) NOT NULL,
                        actor_id VARCHAR(36) NULL,
                        action VARCHAR(32) NOT NULL,
                        before_snapshot JSON NULL,
                        after_snapshot JSON NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        KEY ix_candidate_revision_candidate (candidate_id),
                        KEY ix_candidate_revision_job (extraction_job_id),
                        KEY ix_candidate_revision_session (session_id),
                        KEY ix_candidate_revision_actor (actor_id),
                        KEY ix_candidate_revision_action (action),
                        KEY ix_candidate_revision_created (created_at),
                        CONSTRAINT fk_candidate_revision_candidate FOREIGN KEY (candidate_id)
                            REFERENCES extraction_candidates(id) ON DELETE CASCADE,
                        CONSTRAINT fk_candidate_revision_job FOREIGN KEY (extraction_job_id)
                            REFERENCES extraction_jobs(id) ON DELETE CASCADE,
                        CONSTRAINT fk_candidate_revision_session FOREIGN KEY (session_id)
                            REFERENCES assessment_sessions(id) ON DELETE CASCADE,
                        CONSTRAINT fk_candidate_revision_actor FOREIGN KEY (actor_id)
                            REFERENCES users(id) ON DELETE SET NULL
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"""
                )
        connection.commit()
        print("Phase 22 extraction provenance migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
