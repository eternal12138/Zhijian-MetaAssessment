"""Formal per-run metacognition measurement snapshots."""
from __future__ import annotations

from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


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
            if not _table_exists(cursor, settings.DB_NAME, "metacognition_measurements"):
                cursor.execute(
                    """CREATE TABLE metacognition_measurements (
                        id VARCHAR(36) PRIMARY KEY,
                        user_id VARCHAR(36) NOT NULL,
                        run_id VARCHAR(36) NOT NULL,
                        task_ids JSON NULL,
                        effective_dialogue_count INT NOT NULL DEFAULT 0,
                        monitoring_count INT NOT NULL DEFAULT 0,
                        control_debugging_count INT NOT NULL DEFAULT 0,
                        evaluation_count INT NOT NULL DEFAULT 0,
                        monitoring_score FLOAT NULL,
                        control_debugging_score FLOAT NULL,
                        evaluation_score FLOAT NULL,
                        score_available BOOLEAN NOT NULL DEFAULT FALSE,
                        source VARCHAR(32) NOT NULL DEFAULT 'none',
                        data_version VARCHAR(255) NOT NULL DEFAULT '',
                        calculated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        completed_at DATETIME NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_metacognition_measurement_run (run_id),
                        INDEX ix_metacognition_measurement_user (user_id),
                        INDEX ix_metacognition_measurement_completed (completed_at),
                        CONSTRAINT fk_metacognition_measurement_user
                            FOREIGN KEY (user_id) REFERENCES users(id),
                        CONSTRAINT fk_metacognition_measurement_run
                            FOREIGN KEY (run_id) REFERENCES assessment_runs(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
                )
        connection.commit()
        print("Phase 32 metacognition measurement migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
