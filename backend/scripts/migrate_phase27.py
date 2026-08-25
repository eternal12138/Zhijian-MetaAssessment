"""Complete observable model-training lifecycle and candidate predictions."""
from __future__ import annotations

from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


TRAINING_COLUMNS = (
    ("artifact_sha256", "VARCHAR(64) NULL AFTER artifact_path"),
    ("cancel_requested", "BOOLEAN NOT NULL DEFAULT FALSE AFTER artifact_sha256"),
    ("parent_job_id", "VARCHAR(36) NULL AFTER cancel_requested"),
    ("updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER completed_at"),
)
CANDIDATE_COLUMNS = (
    ("classifier_job_id", "VARCHAR(36) NULL AFTER reviewed_at"),
    ("classifier_version", "VARCHAR(64) NULL AFTER classifier_job_id"),
    ("predicted_label", "INT NULL AFTER classifier_version"),
    ("predicted_dimension", "VARCHAR(32) NULL AFTER predicted_label"),
    ("prediction_confidence", "DOUBLE NULL AFTER predicted_dimension"),
    ("prediction_probabilities", "JSON NULL AFTER prediction_confidence"),
    ("classified_at", "DATETIME NULL AFTER prediction_probabilities"),
    ("classification_error", "TEXT NOT NULL AFTER classified_at"),
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


def _constraint_exists(cursor, database: str, table: str, name: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s""",
        (database, table, name),
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
            for name, definition in TRAINING_COLUMNS:
                if not _column_exists(cursor, settings.DB_NAME, "model_training_jobs", name):
                    cursor.execute(f"ALTER TABLE model_training_jobs ADD COLUMN {name} {definition}")
            for name, definition in CANDIDATE_COLUMNS:
                if not _column_exists(cursor, settings.DB_NAME, "extraction_candidates", name):
                    cursor.execute(f"ALTER TABLE extraction_candidates ADD COLUMN {name} {definition}")
            indexes = (
                ("model_training_jobs", "ix_training_updated", "updated_at"),
                ("model_training_jobs", "ix_training_parent", "parent_job_id"),
                ("extraction_candidates", "ix_candidate_classifier_job", "classifier_job_id"),
            )
            for table, name, column in indexes:
                if not _index_exists(cursor, settings.DB_NAME, table, name):
                    cursor.execute(f"ALTER TABLE {table} ADD INDEX {name} ({column})")
            constraints = (
                ("model_training_jobs", "fk_training_parent", "parent_job_id", "model_training_jobs"),
                ("extraction_candidates", "fk_candidate_classifier_job", "classifier_job_id", "model_training_jobs"),
            )
            for table, name, column, referenced in constraints:
                if not _constraint_exists(cursor, settings.DB_NAME, table, name):
                    cursor.execute(
                        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) "
                        f"REFERENCES {referenced}(id) ON DELETE SET NULL"
                    )
        connection.commit()
        print("Phase 27 observable model lifecycle migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
