"""Idempotent migration for authoritative ASR and transcript versions."""
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
                CREATE TABLE IF NOT EXISTS asr_jobs (
                    id VARCHAR(36) PRIMARY KEY,
                    session_id VARCHAR(36) NOT NULL,
                    provider VARCHAR(32) NOT NULL,
                    model VARCHAR(128) NOT NULL,
                    config_version VARCHAR(32) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'queued',
                    manifest_hash VARCHAR(64) NOT NULL,
                    input_manifest JSON NOT NULL,
                    expected_chunk_count INT NOT NULL,
                    source_audio_path VARCHAR(1024) NULL,
                    canonical_audio_path VARCHAR(1024) NULL,
                    audio_duration_ms BIGINT NULL,
                    language VARCHAR(16) NOT NULL DEFAULT 'zh',
                    retry_count INT NOT NULL DEFAULT 0,
                    max_retries INT NOT NULL DEFAULT 3,
                    provider_request_id VARCHAR(160) NULL,
                    error_code VARCHAR(64) NULL,
                    error_message TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    started_at DATETIME NULL,
                    finished_at DATETIME NULL,
                    UNIQUE KEY uq_asr_job_manifest_config (
                        session_id, manifest_hash, provider, model, config_version
                    ),
                    INDEX idx_asr_jobs_session_id (session_id),
                    INDEX idx_asr_jobs_status (status),
                    CONSTRAINT fk_asr_jobs_session
                        FOREIGN KEY (session_id)
                        REFERENCES assessment_sessions(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS transcript_versions (
                    id VARCHAR(36) PRIMARY KEY,
                    session_id VARCHAR(36) NOT NULL,
                    asr_job_id VARCHAR(36) NULL UNIQUE,
                    version_no INT NOT NULL,
                    source VARCHAR(32) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'ready',
                    is_authoritative BOOLEAN NOT NULL DEFAULT FALSE,
                    language VARCHAR(16) NOT NULL DEFAULT 'zh',
                    provider VARCHAR(32) NULL,
                    model VARCHAR(128) NULL,
                    full_text TEXT NOT NULL,
                    raw_response JSON NULL,
                    created_by VARCHAR(36) NOT NULL DEFAULT 'system',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    approved_by VARCHAR(36) NULL,
                    approved_at DATETIME NULL,
                    UNIQUE KEY uq_transcript_version_session_no (
                        session_id, version_no
                    ),
                    INDEX idx_transcript_versions_session_id (session_id),
                    CONSTRAINT fk_transcript_versions_session
                        FOREIGN KEY (session_id)
                        REFERENCES assessment_sessions(id) ON DELETE CASCADE,
                    CONSTRAINT fk_transcript_versions_job
                        FOREIGN KEY (asr_job_id) REFERENCES asr_jobs(id),
                    CONSTRAINT fk_transcript_versions_approver
                        FOREIGN KEY (approved_by) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COLLATE=utf8mb4_unicode_ci
                """
            )
            additions = {
                "transcript_version_id": (
                    "ALTER TABLE transcript_segments "
                    "ADD COLUMN transcript_version_id VARCHAR(36) NULL "
                    "AFTER client_segment_id"
                ),
                "segment_no": (
                    "ALTER TABLE transcript_segments "
                    "ADD COLUMN segment_no INT NULL AFTER transcript_version_id"
                ),
                "confidence": (
                    "ALTER TABLE transcript_segments "
                    "ADD COLUMN confidence FLOAT NULL AFTER source"
                ),
                "raw_data": (
                    "ALTER TABLE transcript_segments "
                    "ADD COLUMN raw_data JSON NULL AFTER confidence"
                ),
            }
            for column, statement in additions.items():
                if not column_exists(cursor, "transcript_segments", column):
                    cursor.execute(statement)
            if not index_exists(
                cursor, "transcript_segments", "idx_transcript_segments_version_id"
            ):
                cursor.execute(
                    "ALTER TABLE transcript_segments "
                    "ADD INDEX idx_transcript_segments_version_id "
                    "(transcript_version_id)"
                )
            if not index_exists(
                cursor, "transcript_segments", "uq_transcript_version_segment_no"
            ):
                cursor.execute(
                    "ALTER TABLE transcript_segments "
                    "ADD UNIQUE KEY uq_transcript_version_segment_no "
                    "(transcript_version_id, segment_no)"
                )
            if not constraint_exists(
                cursor, "fk_transcript_segments_version"
            ):
                cursor.execute(
                    "ALTER TABLE transcript_segments "
                    "ADD CONSTRAINT fk_transcript_segments_version "
                    "FOREIGN KEY (transcript_version_id) "
                    "REFERENCES transcript_versions(id) ON DELETE CASCADE"
                )
        connection.commit()
        print("Phase-7 authoritative ASR schema is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
