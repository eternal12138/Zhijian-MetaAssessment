"""Add run/task scopes to formal metacognition measurement snapshots."""
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


def _constraint_exists(cursor, database: str, table: str, constraint: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s""",
        (database, table, constraint),
    )
    return bool(cursor.fetchone()[0])


def _indexes(cursor, database: str, table: str) -> dict[str, list[tuple]]:
    """Read definitions, not just names: ORM and SQL migrations name keys differently."""
    cursor.execute(
        """SELECT INDEX_NAME, NON_UNIQUE, COLUMN_NAME, SUB_PART
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
        ORDER BY INDEX_NAME, SEQ_IN_INDEX""",
        (database, table),
    )
    indexes: dict[str, list[tuple]] = {}
    for name, non_unique, column, prefix in cursor.fetchall():
        indexes.setdefault(name, []).append((non_unique, column, prefix))
    return indexes


def _is_unique_index(definition: list[tuple], columns: tuple[str, ...]) -> bool:
    return (
        tuple(row[1] for row in definition) == columns
        and all(row[0] == 0 and row[2] is None for row in definition)
    )


def _upgrade_scope_index(cursor, database: str, table: str) -> None:
    """Replace only the obsolete run-only uniqueness; retain all foreign keys.

    MySQL DDL commits implicitly. Establish the replacement BEFORE dropping any
    old key so a run_id foreign key always has a supporting leftmost index.
    Re-read metadata to safely resume after an interrupted previous migration.
    """
    target = "uq_metacognition_measurement_scope"
    indexes = _indexes(cursor, database, table)
    if target in indexes:
        if not _is_unique_index(indexes[target], ("run_id", "scope_key")):
            raise RuntimeError(f"Unexpected definition for {target}; no legacy index removed")
    else:
        cursor.execute(
            f"ALTER TABLE {table} ADD UNIQUE INDEX "
            f"{target} (run_id, scope_key)"
        )

    # Handles `run_id` (SQLAlchemy), the Phase 32 SQL name, and renamed keys.
    # Do not remove PRIMARY, non-unique indexes, or any other composite key.
    for name, definition in _indexes(cursor, database, table).items():
        if name != "PRIMARY" and _is_unique_index(definition, ("run_id",)):
            quoted_name = "`" + name.replace("`", "``") + "`"
            cursor.execute(f"ALTER TABLE {table} DROP INDEX {quoted_name}")


def main() -> None:
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME,
        charset="utf8mb4", autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            table = "metacognition_measurements"
            if not _column_exists(cursor, settings.DB_NAME, table, "scope_type"):
                cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN scope_type VARCHAR(16) "
                    "NOT NULL DEFAULT 'run' AFTER run_id"
                )
            if not _column_exists(cursor, settings.DB_NAME, table, "scope_key"):
                cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN scope_key VARCHAR(64) "
                    "NOT NULL DEFAULT 'run' AFTER scope_type"
                )
            if not _column_exists(cursor, settings.DB_NAME, table, "task_id"):
                cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN task_id VARCHAR(36) NULL AFTER scope_key"
                )

            cursor.execute(
                f"UPDATE {table} SET scope_type='run', scope_key='run' "
                "WHERE scope_type='' OR scope_key=''"
            )
            _upgrade_scope_index(cursor, settings.DB_NAME, table)
            if not _index_exists(cursor, settings.DB_NAME, table, "ix_metacognition_measurements_task_id"):
                cursor.execute(
                    f"ALTER TABLE {table} ADD INDEX ix_metacognition_measurements_task_id (task_id)"
                )
            if not _constraint_exists(cursor, settings.DB_NAME, table, "fk_metacognition_measurement_task"):
                cursor.execute(
                    f"ALTER TABLE {table} ADD CONSTRAINT fk_metacognition_measurement_task "
                    "FOREIGN KEY (task_id) REFERENCES assessment_tasks(id) ON DELETE CASCADE"
                )
        connection.commit()
        print("Phase 33 scoped metacognition measurement migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
