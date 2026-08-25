"""Persist reusable audio metadata and observable export task state."""
from __future__ import annotations

from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


ASR_COLUMNS = (
    ("audio_size_bytes", "BIGINT NULL AFTER audio_duration_ms"),
    ("audio_sha256", "VARCHAR(64) NULL AFTER audio_size_bytes"),
    ("audio_contains_signal", "BOOLEAN NULL AFTER audio_sha256"),
    ("audio_rms_dbfs", "DOUBLE NULL AFTER audio_contains_signal"),
    ("audio_peak_dbfs", "DOUBLE NULL AFTER audio_rms_dbfs"),
)
EXPORT_COLUMNS = (
    ("progress", "INT NOT NULL DEFAULT 0 AFTER row_count"),
    ("dataset_fingerprint", "VARCHAR(64) NULL AFTER progress"),
)


def _column_exists(cursor, database: str, table: str, column: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s""",
        (database, table, column),
    )
    return bool(cursor.fetchone()[0])


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
            for name, definition in ASR_COLUMNS:
                if not _column_exists(cursor, settings.DB_NAME, "asr_jobs", name):
                    cursor.execute(f"ALTER TABLE asr_jobs ADD COLUMN {name} {definition}")
            for name, definition in EXPORT_COLUMNS:
                if not _column_exists(cursor, settings.DB_NAME, "export_jobs", name):
                    cursor.execute(f"ALTER TABLE export_jobs ADD COLUMN {name} {definition}")
            if not _index_exists(
                cursor, settings.DB_NAME, "export_jobs", "ix_export_jobs_dataset_fingerprint"
            ):
                cursor.execute(
                    "ALTER TABLE export_jobs ADD INDEX "
                    "ix_export_jobs_dataset_fingerprint (dataset_fingerprint)"
                )
        connection.commit()
        print("Phase 25 export acceleration migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
