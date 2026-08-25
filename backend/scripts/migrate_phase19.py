"""Normalize database-generated timestamps to UTC and repair legacy rows.

Historically MySQL ``CURRENT_TIMESTAMP`` used the server's local timezone while
application-written timestamps used UTC. This one-time migration records every
changed value, shifts only columns known to be database-generated, and marks the
database so a redeployment cannot apply the correction twice.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


MIGRATION_VERSION = "phase19_utc_timestamps"

# Only timestamps whose historical value is known to come from a MySQL
# CURRENT_TIMESTAMP default/on-update expression belong here. Fields explicitly
# written by the application (for example completed_at/end_time) are already UTC.
DATABASE_GENERATED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("users", "id", "created_at"),
    ("assessment_tasks", "id", "created_at"),
    ("system_config", "config_key", "updated_at"),
    ("system_config_history", "id", "created_at"),
    ("assessment_runs", "id", "consented_at"),
    ("assessment_runs", "id", "started_at"),
    ("assessment_sessions", "id", "start_time"),
    ("questionnaire_responses", "id", "answered_at"),
    ("coded_segments", "id", "coded_at"),
    ("audio_chunks", "id", "created_at"),
    ("transcript_segments", "id", "created_at"),
    ("interaction_events", "id", "created_at"),
    ("asr_jobs", "id", "created_at"),
    ("asr_jobs", "id", "updated_at"),
    ("transcript_versions", "id", "created_at"),
    ("notifications", "id", "created_at"),
    ("narration_assets", "id", "created_at"),
    ("coding_batches", "id", "created_at"),
    ("coding_units", "id", "created_at"),
    ("audit_logs", "id", "created_at"),
    ("run_quality_reviews", "id", "updated_at"),
    ("consistency_reports", "id", "generated_at"),
)


def _column_exists(cursor, database: str, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """,
        (database, table, column),
    )
    return bool(cursor.fetchone()[0])


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
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(64) NOT NULL PRIMARY KEY,
                    applied_at DATETIME NOT NULL,
                    details JSON NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase19_timestamp_backup (
                    table_name VARCHAR(64) NOT NULL,
                    column_name VARCHAR(64) NOT NULL,
                    record_key VARCHAR(255) NOT NULL,
                    original_value DATETIME NOT NULL,
                    PRIMARY KEY (table_name, column_name, record_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            connection.commit()

            cursor.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version=%s",
                (MIGRATION_VERSION,),
            )
            if cursor.fetchone()[0]:
                print("Phase 19 UTC timestamp migration already applied; skipped.")
                return

            cursor.execute(
                "SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW())"
            )
            offset_seconds = int(cursor.fetchone()[0] or 0)
            if abs(offset_seconds) > 14 * 60 * 60:
                raise RuntimeError(
                    f"Unsafe MySQL UTC offset detected: {offset_seconds} seconds"
                )

            shifted_rows: dict[str, int] = {}
            for table, key_column, timestamp_column in DATABASE_GENERATED_COLUMNS:
                if not (
                    _column_exists(cursor, settings.DB_NAME, table, key_column)
                    and _column_exists(
                        cursor, settings.DB_NAME, table, timestamp_column
                    )
                ):
                    continue

                table_sql = f"`{table}`"
                key_sql = f"`{key_column}`"
                timestamp_sql = f"`{timestamp_column}`"
                cursor.execute(
                    f"""
                    INSERT IGNORE INTO phase19_timestamp_backup
                        (table_name, column_name, record_key, original_value)
                    SELECT %s, %s, CAST({key_sql} AS CHAR), {timestamp_sql}
                    FROM {table_sql}
                    WHERE {timestamp_sql} IS NOT NULL
                    """,
                    (table, timestamp_column),
                )
                if offset_seconds:
                    cursor.execute(
                        f"""
                        UPDATE {table_sql}
                        SET {timestamp_sql} = TIMESTAMPADD(
                            SECOND, %s, {timestamp_sql}
                        )
                        WHERE {timestamp_sql} IS NOT NULL
                        """,
                        (-offset_seconds,),
                    )
                    shifted_rows[f"{table}.{timestamp_column}"] = cursor.rowcount

            # The marker itself and every future default timestamp are UTC.
            cursor.execute("SET time_zone = '+00:00'")
            details = {
                "legacy_offset_seconds": offset_seconds,
                "shifted_rows": shifted_rows,
                "backup_table": "phase19_timestamp_backup",
            }
            cursor.execute(
                """
                INSERT INTO schema_migrations (version, applied_at, details)
                VALUES (%s, UTC_TIMESTAMP(), %s)
                """,
                (MIGRATION_VERSION, json.dumps(details, ensure_ascii=False)),
            )
            connection.commit()

        total = sum(shifted_rows.values())
        print(
            "Phase 19 UTC timestamp migration completed: "
            f"legacy_offset_seconds={offset_seconds}, shifted_values={total}."
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
