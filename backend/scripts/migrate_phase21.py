"""Add expiring review leases for concurrent candidate validation."""
from __future__ import annotations

from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


def _column_exists(cursor, database: str, column: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME='extraction_jobs' AND COLUMN_NAME=%s""",
        (database, column),
    )
    return bool(cursor.fetchone()[0])


def _index_exists(cursor, database: str, index_name: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME='extraction_jobs' AND INDEX_NAME=%s""",
        (database, index_name),
    )
    return bool(cursor.fetchone()[0])


def _constraint_exists(cursor, database: str, constraint_name: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME='extraction_jobs'
          AND CONSTRAINT_NAME=%s""",
        (database, constraint_name),
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
            if not _column_exists(cursor, settings.DB_NAME, "review_lock_user_id"):
                cursor.execute(
                    """ALTER TABLE extraction_jobs
                    ADD COLUMN review_lock_user_id VARCHAR(36) NULL AFTER completed_at"""
                )
            if not _column_exists(cursor, settings.DB_NAME, "review_lock_acquired_at"):
                cursor.execute(
                    """ALTER TABLE extraction_jobs ADD COLUMN
                    review_lock_acquired_at DATETIME NULL AFTER review_lock_user_id"""
                )
            if not _column_exists(cursor, settings.DB_NAME, "review_lock_expires_at"):
                cursor.execute(
                    """ALTER TABLE extraction_jobs ADD COLUMN
                    review_lock_expires_at DATETIME NULL AFTER review_lock_acquired_at"""
                )
            if not _index_exists(cursor, settings.DB_NAME, "ix_extraction_jobs_review_lock_user"):
                cursor.execute(
                    """ALTER TABLE extraction_jobs ADD KEY
                    ix_extraction_jobs_review_lock_user (review_lock_user_id)"""
                )
            if not _index_exists(cursor, settings.DB_NAME, "ix_extraction_jobs_review_lock_expires"):
                cursor.execute(
                    """ALTER TABLE extraction_jobs ADD KEY
                    ix_extraction_jobs_review_lock_expires (review_lock_expires_at)"""
                )
            if not _constraint_exists(cursor, settings.DB_NAME, "fk_extraction_job_review_lock_user"):
                cursor.execute(
                    """ALTER TABLE extraction_jobs
                    ADD CONSTRAINT fk_extraction_job_review_lock_user
                    FOREIGN KEY (review_lock_user_id) REFERENCES users(id)"""
                )
        connection.commit()
        print("Phase 21 candidate review lease migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
