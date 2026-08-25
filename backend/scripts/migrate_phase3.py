"""Idempotent migration for phase-3 coding and complete-run reports."""
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
            additions = [
                ("coded_segments", "transcript_segment_id",
                 "ALTER TABLE coded_segments ADD COLUMN transcript_segment_id VARCHAR(36) NULL AFTER turn_id"),
                ("coded_segments", "analysis_method",
                 "ALTER TABLE coded_segments ADD COLUMN analysis_method VARCHAR(32) NOT NULL DEFAULT 'rule'"),
                ("coded_segments", "rubric_version",
                 "ALTER TABLE coded_segments ADD COLUMN rubric_version VARCHAR(32) NOT NULL DEFAULT '2026.1'"),
                ("metacognitive_profiles", "run_id",
                 "ALTER TABLE metacognitive_profiles ADD COLUMN run_id VARCHAR(36) NULL AFTER user_id"),
                ("metacognitive_profiles", "analysis_method",
                 "ALTER TABLE metacognitive_profiles ADD COLUMN analysis_method VARCHAR(32) NOT NULL DEFAULT 'rule'"),
                ("metacognitive_profiles", "rubric_version",
                 "ALTER TABLE metacognitive_profiles ADD COLUMN rubric_version VARCHAR(32) NOT NULL DEFAULT '2026.1'"),
                ("metacognitive_profiles", "requires_review_count",
                 "ALTER TABLE metacognitive_profiles ADD COLUMN requires_review_count INT NOT NULL DEFAULT 0"),
                ("metacognitive_profiles", "is_provisional",
                 "ALTER TABLE metacognitive_profiles ADD COLUMN is_provisional BOOLEAN NOT NULL DEFAULT TRUE"),
            ]
            for table, column, statement in additions:
                if not column_exists(cursor, table, column):
                    cursor.execute(statement)

            cursor.execute(
                "ALTER TABLE coded_segments MODIFY COLUMN turn_id VARCHAR(36) NULL"
            )
            if not index_exists(cursor, "coded_segments", "idx_coded_segments_transcript_id"):
                cursor.execute(
                    "ALTER TABLE coded_segments ADD INDEX "
                    "idx_coded_segments_transcript_id (transcript_segment_id)"
                )
            if not constraint_exists(cursor, "fk_coded_segments_transcript"):
                cursor.execute(
                    "ALTER TABLE coded_segments ADD CONSTRAINT "
                    "fk_coded_segments_transcript FOREIGN KEY (transcript_segment_id) "
                    "REFERENCES transcript_segments(id) ON DELETE CASCADE"
                )
            if not index_exists(cursor, "metacognitive_profiles", "uq_profiles_run_id"):
                cursor.execute(
                    "ALTER TABLE metacognitive_profiles ADD UNIQUE INDEX "
                    "uq_profiles_run_id (run_id)"
                )
            if not constraint_exists(cursor, "fk_profiles_run"):
                cursor.execute(
                    "ALTER TABLE metacognitive_profiles ADD CONSTRAINT fk_profiles_run "
                    "FOREIGN KEY (run_id) REFERENCES assessment_runs(id)"
                )
        connection.commit()
        print("Phase-3 coding and report schema is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
