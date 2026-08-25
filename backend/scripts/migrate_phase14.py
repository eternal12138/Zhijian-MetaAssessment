"""Add immutable human narration recordings and per-run audio snapshots."""
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
                CREATE TABLE IF NOT EXISTS narration_assets (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    slot_key VARCHAR(64) NOT NULL,
                    label VARCHAR(255) NOT NULL,
                    source_text TEXT NOT NULL,
                    original_filename VARCHAR(255) NOT NULL,
                    storage_path VARCHAR(1024) NOT NULL,
                    mime_type VARCHAR(128) NOT NULL,
                    size_bytes BIGINT NOT NULL,
                    sha256 VARCHAR(64) NOT NULL,
                    version INT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    uploaded_by VARCHAR(36) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_narration_asset_slot_version
                        UNIQUE (slot_key, version),
                    CONSTRAINT fk_narration_asset_uploader
                        FOREIGN KEY (uploaded_by) REFERENCES users(id),
                    INDEX ix_narration_assets_slot_key (slot_key),
                    INDEX ix_narration_assets_is_active (is_active)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s
                  AND TABLE_NAME='assessment_runs'
                  AND COLUMN_NAME='narration_snapshot'
                """,
                (settings.DB_NAME,),
            )
            if not cursor.fetchone()[0]:
                cursor.execute(
                    """
                    ALTER TABLE assessment_runs
                    ADD COLUMN narration_snapshot JSON NULL
                    AFTER order_assignment_id
                    """
                )
        connection.commit()
        print("Phase 14 human narration storage is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
