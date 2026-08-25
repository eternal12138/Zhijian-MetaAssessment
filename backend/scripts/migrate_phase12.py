"""Create the fixed-assignment blinded double-coding workflow tables."""
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
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_batches (
                    id VARCHAR(36) PRIMARY KEY,
                    name VARCHAR(128) NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'active',
                    reviewer_a_id VARCHAR(36) NOT NULL,
                    reviewer_b_id VARCHAR(36) NOT NULL,
                    adjudicator_id VARCHAR(36) NOT NULL,
                    created_by VARCHAR(36) NOT NULL,
                    rubric_version VARCHAR(32) NOT NULL DEFAULT '2026.2',
                    scope_filter JSON NULL,
                    scope_summary JSON NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    activated_at DATETIME NULL,
                    completed_at DATETIME NULL,
                    INDEX ix_coding_batches_status (status),
                    INDEX ix_coding_batches_reviewer_a (reviewer_a_id),
                    INDEX ix_coding_batches_reviewer_b (reviewer_b_id),
                    INDEX ix_coding_batches_adjudicator (adjudicator_id),
                    CONSTRAINT fk_coding_batch_reviewer_a
                        FOREIGN KEY (reviewer_a_id) REFERENCES users(id),
                    CONSTRAINT fk_coding_batch_reviewer_b
                        FOREIGN KEY (reviewer_b_id) REFERENCES users(id),
                    CONSTRAINT fk_coding_batch_adjudicator
                        FOREIGN KEY (adjudicator_id) REFERENCES users(id),
                    CONSTRAINT fk_coding_batch_creator
                        FOREIGN KEY (created_by) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_units (
                    id VARCHAR(36) PRIMARY KEY,
                    batch_id VARCHAR(36) NOT NULL,
                    transcript_segment_id VARCHAR(36) NOT NULL,
                    session_id VARCHAR(36) NOT NULL,
                    run_id VARCHAR(36) NULL,
                    task_id VARCHAR(36) NOT NULL,
                    sequence_no INT NOT NULL,
                    segment TEXT NOT NULL,
                    context_before TEXT NOT NULL,
                    context_after TEXT NOT NULL,
                    started_at_ms BIGINT NOT NULL DEFAULT 0,
                    ended_at_ms BIGINT NOT NULL DEFAULT 0,
                    ai_dimension VARCHAR(32) NULL,
                    ai_score INT NULL,
                    ai_reason TEXT NOT NULL,
                    ai_confidence DOUBLE NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'pending',
                    final_dimension VARCHAR(32) NULL,
                    final_source VARCHAR(32) NULL,
                    resolved_at DATETIME NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_coding_batch_transcript (
                        batch_id, transcript_segment_id
                    ),
                    INDEX ix_coding_units_batch (batch_id),
                    INDEX ix_coding_units_transcript (transcript_segment_id),
                    INDEX ix_coding_units_session (session_id),
                    INDEX ix_coding_units_run (run_id),
                    INDEX ix_coding_units_status (status),
                    CONSTRAINT fk_coding_unit_batch
                        FOREIGN KEY (batch_id) REFERENCES coding_batches(id)
                        ON DELETE CASCADE,
                    CONSTRAINT fk_coding_unit_transcript
                        FOREIGN KEY (transcript_segment_id)
                        REFERENCES transcript_segments(id) ON DELETE CASCADE,
                    CONSTRAINT fk_coding_unit_session
                        FOREIGN KEY (session_id)
                        REFERENCES assessment_sessions(id),
                    CONSTRAINT fk_coding_unit_run
                        FOREIGN KEY (run_id) REFERENCES assessment_runs(id),
                    CONSTRAINT fk_coding_unit_task
                        FOREIGN KEY (task_id) REFERENCES assessment_tasks(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_unit_annotations (
                    id VARCHAR(36) PRIMARY KEY,
                    unit_id VARCHAR(36) NOT NULL,
                    reviewer_id VARCHAR(36) NOT NULL,
                    reviewer_slot VARCHAR(1) NOT NULL,
                    dimension VARCHAR(32) NULL,
                    note TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_unit_reviewer (unit_id, reviewer_id),
                    UNIQUE KEY uq_unit_reviewer_slot (unit_id, reviewer_slot),
                    INDEX ix_unit_annotations_unit (unit_id),
                    INDEX ix_unit_annotations_reviewer (reviewer_id),
                    CONSTRAINT fk_unit_annotation_unit
                        FOREIGN KEY (unit_id) REFERENCES coding_units(id)
                        ON DELETE CASCADE,
                    CONSTRAINT fk_unit_annotation_reviewer
                        FOREIGN KEY (reviewer_id) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_unit_adjudications (
                    id VARCHAR(36) PRIMARY KEY,
                    unit_id VARCHAR(36) NOT NULL,
                    adjudicator_id VARCHAR(36) NOT NULL,
                    dimension VARCHAR(32) NULL,
                    note TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_unit_adjudication (unit_id),
                    INDEX ix_unit_adjudications_adjudicator (adjudicator_id),
                    CONSTRAINT fk_unit_adjudication_unit
                        FOREIGN KEY (unit_id) REFERENCES coding_units(id)
                        ON DELETE CASCADE,
                    CONSTRAINT fk_unit_adjudication_user
                        FOREIGN KEY (adjudicator_id) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COLLATE=utf8mb4_unicode_ci
                """
            )
        connection.commit()
        print("Phase 12 blinded double-coding schema is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
