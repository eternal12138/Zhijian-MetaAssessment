"""Add provider-aware embedding cache metadata and durable prediction status."""
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


def main() -> None:
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME,
        charset="utf8mb4", autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            cache_columns = (
                ("provider", "VARCHAR(64) NOT NULL DEFAULT 'legacy' AFTER text_hash"),
                ("model_version", "VARCHAR(100) NOT NULL DEFAULT 'default' AFTER model"),
                ("normalized", "BOOLEAN NOT NULL DEFAULT TRUE AFTER dimensions"),
                ("instruction_hash", "VARCHAR(64) NOT NULL DEFAULT '' AFTER normalized"),
            )
            for name, definition in cache_columns:
                if not _column_exists(cursor, settings.DB_NAME, "text_embedding_cache", name):
                    cursor.execute(f"ALTER TABLE text_embedding_cache ADD COLUMN {name} {definition}")
            candidate_columns = (
                ("classification_status", "VARCHAR(32) NOT NULL DEFAULT 'pending_classification' AFTER classified_at"),
                ("prediction_source", "VARCHAR(32) NULL AFTER classification_status"),
            )
            for name, definition in candidate_columns:
                if not _column_exists(cursor, settings.DB_NAME, "extraction_candidates", name):
                    cursor.execute(f"ALTER TABLE extraction_candidates ADD COLUMN {name} {definition}")
            cursor.execute(
                """UPDATE extraction_candidates SET classification_status = CASE
                    WHEN classifier_version IS NOT NULL THEN 'classified'
                    WHEN classification_error <> '' THEN 'pending_classification'
                    ELSE 'not_active' END
                WHERE classification_status = 'pending_classification'"""
            )
            cursor.execute(
                """UPDATE extraction_candidates SET prediction_source = 'remote_embedding'
                WHERE classifier_version IS NOT NULL AND prediction_source IS NULL"""
            )
            if not _index_exists(cursor, settings.DB_NAME, "extraction_candidates", "ix_candidate_classification_status"):
                cursor.execute(
                    "ALTER TABLE extraction_candidates ADD INDEX ix_candidate_classification_status (classification_status)"
                )
        connection.commit()
        print("Phase 29 provider-aware embedding and classification status migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
