"""Idempotent local migration for the phase-2 standardized protocol."""
from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


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

    def column_exists(cursor, table: str, column: str) -> bool:
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
            """,
            (settings.DB_NAME, table, column),
        )
        return bool(cursor.fetchone()[0])

    def index_exists(cursor, table: str, index: str) -> bool:
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s
            """,
            (settings.DB_NAME, table, index),
        )
        return bool(cursor.fetchone()[0])

    def constraint_exists(cursor, constraint: str) -> bool:
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA=%s AND CONSTRAINT_NAME=%s
            """,
            (settings.DB_NAME, constraint),
        )
        return bool(cursor.fetchone()[0])

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS assessment_runs (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL,
                    status ENUM('in_progress', 'completed', 'abandoned')
                        NOT NULL DEFAULT 'in_progress',
                    current_stage VARCHAR(32) NOT NULL DEFAULT 'device_check',
                    protocol_version VARCHAR(32) NOT NULL DEFAULT '2026.2',
                    consented_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    INDEX idx_assessment_runs_user_id (user_id),
                    CONSTRAINT fk_assessment_runs_user
                        FOREIGN KEY (user_id) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                ALTER TABLE assessment_runs
                MODIFY protocol_version VARCHAR(32) NOT NULL DEFAULT '2026.2'
                """
            )

            additions = [
                (
                    "assessment_tasks",
                    "protocol_order",
                    "ALTER TABLE assessment_tasks "
                    "ADD COLUMN protocol_order INT NOT NULL DEFAULT 0 AFTER requires_voice",
                ),
                (
                    "assessment_tasks",
                    "stimulus_data",
                    "ALTER TABLE assessment_tasks "
                    "ADD COLUMN stimulus_data JSON NULL AFTER protocol_order",
                ),
                (
                    "scale_items",
                    "display_order",
                    "ALTER TABLE scale_items "
                    "ADD COLUMN display_order INT NOT NULL DEFAULT 0 AFTER reversed",
                ),
                (
                    "assessment_sessions",
                    "run_id",
                    "ALTER TABLE assessment_sessions "
                    "ADD COLUMN run_id VARCHAR(36) NULL AFTER task_id",
                ),
                (
                    "assessment_sessions",
                    "sequence_no",
                    "ALTER TABLE assessment_sessions "
                    "ADD COLUMN sequence_no INT NOT NULL DEFAULT 1 AFTER run_id",
                ),
            ]
            for table, column, statement in additions:
                if not column_exists(cursor, table, column):
                    cursor.execute(statement)

            if not index_exists(
                cursor,
                "assessment_sessions",
                "idx_assessment_sessions_run_id",
            ):
                cursor.execute(
                    "ALTER TABLE assessment_sessions "
                    "ADD INDEX idx_assessment_sessions_run_id (run_id)"
                )
            if not constraint_exists(cursor, "fk_assessment_sessions_run"):
                cursor.execute(
                    "ALTER TABLE assessment_sessions "
                    "ADD CONSTRAINT fk_assessment_sessions_run "
                    "FOREIGN KEY (run_id) REFERENCES assessment_runs(id)"
                )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS questionnaire_responses (
                    id VARCHAR(36) PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL,
                    user_id VARCHAR(36) NOT NULL,
                    item_id VARCHAR(36) NOT NULL,
                    value INT NOT NULL,
                    answered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_questionnaire_run_item (run_id, item_id),
                    CONSTRAINT fk_questionnaire_run
                        FOREIGN KEY (run_id) REFERENCES assessment_runs(id)
                        ON DELETE CASCADE,
                    CONSTRAINT fk_questionnaire_user
                        FOREIGN KEY (user_id) REFERENCES users(id),
                    CONSTRAINT fk_questionnaire_item
                        FOREIGN KEY (item_id) REFERENCES scale_items(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )

        connection.commit()
        print("Phase-2 standardized protocol schema is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
