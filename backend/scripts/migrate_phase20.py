"""Create the auditable metacognitive candidate-extraction workflow."""
from __future__ import annotations

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
                CREATE TABLE IF NOT EXISTS extraction_jobs (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    session_id VARCHAR(36) NOT NULL,
                    transcript_version_id VARCHAR(36) NOT NULL,
                    requested_by VARCHAR(36) NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'queued',
                    provider VARCHAR(32) NOT NULL DEFAULT 'openai_compatible',
                    model VARCHAR(128) NOT NULL,
                    extractor_version VARCHAR(32) NOT NULL,
                    prompt_version VARCHAR(32) NOT NULL,
                    prompt_content LONGTEXT NOT NULL,
                    raw_asr_text LONGTEXT NOT NULL,
                    raw_response JSON NULL,
                    retry_count INT NOT NULL DEFAULT 0,
                    max_retries INT NOT NULL DEFAULT 2,
                    error_code VARCHAR(64) NULL,
                    error_message LONGTEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    started_at DATETIME NULL,
                    completed_at DATETIME NULL,
                    UNIQUE KEY uq_extraction_version_config
                        (transcript_version_id, extractor_version, prompt_version),
                    KEY ix_extraction_jobs_session_id (session_id),
                    KEY ix_extraction_jobs_transcript_version_id (transcript_version_id),
                    KEY ix_extraction_jobs_status (status),
                    CONSTRAINT fk_extraction_job_session FOREIGN KEY (session_id)
                        REFERENCES assessment_sessions(id) ON DELETE CASCADE,
                    CONSTRAINT fk_extraction_job_version FOREIGN KEY (transcript_version_id)
                        REFERENCES transcript_versions(id) ON DELETE CASCADE,
                    CONSTRAINT fk_extraction_job_requester FOREIGN KEY (requested_by)
                        REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS extraction_candidates (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    extraction_job_id VARCHAR(36) NOT NULL,
                    source_transcript_segment_id VARCHAR(36) NULL,
                    session_id VARCHAR(36) NOT NULL,
                    run_id VARCHAR(36) NULL,
                    user_id VARCHAR(36) NOT NULL,
                    task_id VARCHAR(36) NOT NULL,
                    sequence_no INT NOT NULL,
                    source_type VARCHAR(16) NOT NULL DEFAULT 'llm',
                    review_status VARCHAR(16) NOT NULL DEFAULT 'pending',
                    raw_asr_text LONGTEXT NOT NULL,
                    original_text LONGTEXT NOT NULL,
                    clean_text LONGTEXT NOT NULL,
                    char_start INT NULL,
                    char_end INT NULL,
                    started_at_ms BIGINT NOT NULL DEFAULT 0,
                    ended_at_ms BIGINT NOT NULL DEFAULT 0,
                    reviewer_id VARCHAR(36) NULL,
                    review_note LONGTEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    reviewed_at DATETIME NULL,
                    UNIQUE KEY uq_extraction_candidate_no (extraction_job_id, sequence_no),
                    KEY ix_extraction_candidates_job (extraction_job_id),
                    KEY ix_extraction_candidates_segment (source_transcript_segment_id),
                    KEY ix_extraction_candidates_session (session_id),
                    KEY ix_extraction_candidates_run (run_id),
                    KEY ix_extraction_candidates_user (user_id),
                    KEY ix_extraction_candidates_review_status (review_status),
                    CONSTRAINT fk_extraction_candidate_job FOREIGN KEY (extraction_job_id)
                        REFERENCES extraction_jobs(id) ON DELETE CASCADE,
                    CONSTRAINT fk_extraction_candidate_segment FOREIGN KEY (source_transcript_segment_id)
                        REFERENCES transcript_segments(id) ON DELETE SET NULL,
                    CONSTRAINT fk_extraction_candidate_session FOREIGN KEY (session_id)
                        REFERENCES assessment_sessions(id) ON DELETE CASCADE,
                    CONSTRAINT fk_extraction_candidate_run FOREIGN KEY (run_id)
                        REFERENCES assessment_runs(id),
                    CONSTRAINT fk_extraction_candidate_user FOREIGN KEY (user_id)
                        REFERENCES users(id),
                    CONSTRAINT fk_extraction_candidate_task FOREIGN KEY (task_id)
                        REFERENCES assessment_tasks(id),
                    CONSTRAINT fk_extraction_candidate_reviewer FOREIGN KEY (reviewer_id)
                        REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s AND TABLE_NAME='coding_units'
                  AND COLUMN_NAME='candidate_id'
                """,
                (settings.DB_NAME,),
            )
            if not cursor.fetchone()[0]:
                cursor.execute(
                    "ALTER TABLE coding_units MODIFY transcript_segment_id VARCHAR(36) NULL"
                )
                cursor.execute(
                    """
                    ALTER TABLE coding_units
                    ADD COLUMN candidate_id VARCHAR(36) NULL AFTER transcript_segment_id,
                    ADD KEY ix_coding_units_candidate_id (candidate_id),
                    ADD UNIQUE KEY uq_coding_batch_candidate (batch_id, candidate_id),
                    ADD CONSTRAINT fk_coding_unit_candidate FOREIGN KEY (candidate_id)
                        REFERENCES extraction_candidates(id) ON DELETE SET NULL
                    """
                )
        connection.commit()
        print("Phase 20 extraction workflow migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
