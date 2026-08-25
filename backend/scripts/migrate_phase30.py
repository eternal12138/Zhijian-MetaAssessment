"""Persist observable model-training progress columns."""
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


def _index_exists(cursor, database: str, table: str, index: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s""",
        (database, table, index),
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
            columns = (
                ("current_fold", "INT NULL AFTER progress"),
                ("heartbeat_at", "DATETIME NULL AFTER current_fold"),
                ("estimated_remaining_seconds", "INT NULL AFTER heartbeat_at"),
            )
            for name, definition in columns:
                if not _column_exists(cursor, settings.DB_NAME, "model_training_jobs", name):
                    cursor.execute(f"ALTER TABLE model_training_jobs ADD COLUMN {name} {definition}")
            if not _index_exists(cursor, settings.DB_NAME, "model_training_jobs", "ix_training_jobs_heartbeat_at"):
                cursor.execute(
                    "ALTER TABLE model_training_jobs ADD INDEX ix_training_jobs_heartbeat_at (heartbeat_at)"
                )
        connection.commit()
        print("Phase 30 model training progress migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
