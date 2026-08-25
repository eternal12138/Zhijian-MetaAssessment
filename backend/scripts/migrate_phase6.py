"""Idempotent migration for assessment interaction event timelines."""
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
                CREATE TABLE IF NOT EXISTS interaction_events (
                    id VARCHAR(36) PRIMARY KEY,
                    session_id VARCHAR(36) NOT NULL,
                    client_event_id VARCHAR(96) NOT NULL,
                    sequence_no INT NOT NULL,
                    event_type VARCHAR(64) NOT NULL,
                    occurred_at_ms BIGINT NOT NULL DEFAULT 0,
                    client_timestamp_ms BIGINT NOT NULL,
                    source VARCHAR(32) NOT NULL DEFAULT 'browser',
                    payload JSON NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_interaction_event_session_client_id (
                        session_id, client_event_id
                    ),
                    INDEX idx_interaction_events_session_id (session_id),
                    INDEX idx_interaction_events_type (event_type),
                    INDEX idx_interaction_events_timeline (
                        session_id, sequence_no, occurred_at_ms
                    ),
                    CONSTRAINT fk_interaction_events_session
                        FOREIGN KEY (session_id)
                        REFERENCES assessment_sessions(id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA=%s
                  AND TABLE_NAME='interaction_events'
                  AND INDEX_NAME='idx_interaction_events_timeline'
                """,
                (settings.DB_NAME,),
            )
            if not cursor.fetchone()[0]:
                cursor.execute(
                    """
                    ALTER TABLE interaction_events
                    ADD INDEX idx_interaction_events_timeline (
                        session_id, sequence_no, occurred_at_ms
                    )
                    """
                )
        connection.commit()
        print("Phase-6 interaction event schema is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
