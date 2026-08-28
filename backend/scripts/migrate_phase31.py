"""Immutable prediction audit tables and a single-active-model constraint."""
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
            if not _table_exists(cursor, settings.DB_NAME, "model_prediction_runs"):
                cursor.execute(
                    """CREATE TABLE model_prediction_runs (
                        id VARCHAR(36) PRIMARY KEY,
                        model_job_id VARCHAR(36) NULL,
                        model_version VARCHAR(64) NULL,
                        engine VARCHAR(32) NOT NULL,
                        embedding_config_snapshot JSON NULL,
                        status VARCHAR(24) NOT NULL DEFAULT 'running',
                        error_message TEXT NOT NULL,
                        started_at DATETIME NULL,
                        completed_at DATETIME NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        INDEX ix_prediction_runs_model_job (model_job_id),
                        INDEX ix_prediction_runs_created (created_at),
                        CONSTRAINT fk_prediction_run_model
                            FOREIGN KEY (model_job_id) REFERENCES model_training_jobs(id) ON DELETE SET NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
                )
            if not _table_exists(cursor, settings.DB_NAME, "model_prediction_results"):
                cursor.execute(
                    """CREATE TABLE model_prediction_results (
                        id VARCHAR(36) PRIMARY KEY,
                        run_id VARCHAR(36) NOT NULL,
                        candidate_id VARCHAR(36) NOT NULL,
                        input_text_hash VARCHAR(64) NOT NULL,
                        predicted_label INT NULL,
                        predicted_dimension VARCHAR(32) NULL,
                        prediction_confidence FLOAT NULL,
                        prediction_probabilities JSON NULL,
                        top1_top2_gap FLOAT NULL,
                        low_confidence_reason TEXT NOT NULL,
                        needs_review BOOLEAN NOT NULL DEFAULT FALSE,
                        inference_duration_ms INT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_prediction_run_candidate (run_id, candidate_id),
                        INDEX ix_prediction_result_candidate (candidate_id),
                        CONSTRAINT fk_prediction_result_run
                            FOREIGN KEY (run_id) REFERENCES model_prediction_runs(id) ON DELETE CASCADE,
                        CONSTRAINT fk_prediction_result_candidate
                            FOREIGN KEY (candidate_id) REFERENCES extraction_candidates(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
                )

            if not _column_exists(cursor, settings.DB_NAME, "model_training_jobs", "active_scope"):
                cursor.execute(
                    """ALTER TABLE model_training_jobs
                    ADD COLUMN active_scope TINYINT
                    GENERATED ALWAYS AS (CASE WHEN is_active THEN 1 ELSE NULL END) STORED"""
                )
                cursor.execute(
                    """SELECT id FROM model_training_jobs
                    WHERE is_active = TRUE
                    ORDER BY activated_at DESC, id DESC"""
                )
                active_ids = [row[0] for row in cursor.fetchall()]
                for stale_id in active_ids[1:]:
                    cursor.execute(
                        "UPDATE model_training_jobs SET is_active = FALSE WHERE id = %s",
                        (stale_id,),
                    )
            if not _index_exists(cursor, settings.DB_NAME, "model_training_jobs", "uq_training_active_scope"):
                cursor.execute(
                    "ALTER TABLE model_training_jobs ADD UNIQUE INDEX uq_training_active_scope (active_scope)"
                )
        connection.commit()
        print("Phase 31 prediction audit and single-active-model migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
