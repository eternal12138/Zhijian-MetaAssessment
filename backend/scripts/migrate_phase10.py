"""Idempotent migration for optional questionnaire protocol snapshots."""
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
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s
                  AND TABLE_NAME='assessment_runs'
                  AND COLUMN_NAME='questionnaire_enabled'
                """,
                (settings.DB_NAME,),
            )
            if not cursor.fetchone()[0]:
                cursor.execute(
                    """
                    ALTER TABLE assessment_runs
                    ADD COLUMN questionnaire_enabled BOOLEAN NOT NULL DEFAULT TRUE
                    AFTER protocol_version
                    """
                )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS system_config (
                    config_key VARCHAR(64) PRIMARY KEY,
                    config_value TEXT NOT NULL,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                INSERT IGNORE INTO system_config (config_key, config_value)
                VALUES ('assessment_protocol_config',
                        '{"questionnaire_enabled":false}')
                """
            )
        connection.commit()
        print("Phase 10 optional questionnaire protocol schema is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
