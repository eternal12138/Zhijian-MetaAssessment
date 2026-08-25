"""Idempotent migration for per-student balanced task-order assignment."""
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
                CREATE TABLE IF NOT EXISTS task_order_assignments (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL,
                    ordered_task_ids JSON NOT NULL,
                    order_code VARCHAR(32) NOT NULL,
                    assigned_by VARCHAR(36) NOT NULL,
                    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_task_order_assignment_user (user_id),
                    INDEX idx_task_order_assignments_user_id (user_id),
                    CONSTRAINT fk_task_order_assignment_user
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CONSTRAINT fk_task_order_assignment_actor
                        FOREIGN KEY (assigned_by) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            if not column_exists(cursor, "assessment_runs", "task_order_code"):
                cursor.execute(
                    "ALTER TABLE assessment_runs "
                    "ADD COLUMN task_order_code VARCHAR(32) NOT NULL DEFAULT 'AB' "
                    "AFTER protocol_version"
                )
            if not column_exists(cursor, "assessment_runs", "order_assignment_id"):
                cursor.execute(
                    "ALTER TABLE assessment_runs "
                    "ADD COLUMN order_assignment_id VARCHAR(36) NULL "
                    "AFTER task_order_code"
                )
            if not constraint_exists(cursor, "fk_assessment_run_order_assignment"):
                cursor.execute(
                    "ALTER TABLE assessment_runs "
                    "ADD CONSTRAINT fk_assessment_run_order_assignment "
                    "FOREIGN KEY (order_assignment_id) REFERENCES task_order_assignments(id)"
                )
        connection.commit()
        print("Per-student balanced task-order assignment schema is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
