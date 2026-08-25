"""Idempotent migration for phase-4 research workflow."""
from pathlib import Path
import sys
import uuid

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.services.method_templates import DEFAULT_TEMPLATES


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
            additions = [
                ("workflow_status", "VARCHAR(24) NOT NULL DEFAULT 'draft'"),
                ("version_no", "INT NOT NULL DEFAULT 1"),
                ("template_version", "VARCHAR(32) NOT NULL DEFAULT 'draft-1'"),
                ("published_at", "DATETIME NULL"),
                ("published_by", "VARCHAR(36) NULL"),
            ]
            for column, definition in additions:
                if not column_exists(cursor, "metacognitive_profiles", column):
                    cursor.execute(
                        f"ALTER TABLE metacognitive_profiles ADD COLUMN {column} {definition}"
                    )
            if not constraint_exists(cursor, "fk_profiles_published_by"):
                cursor.execute(
                    "ALTER TABLE metacognitive_profiles "
                    "ADD CONSTRAINT fk_profiles_published_by "
                    "FOREIGN KEY (published_by) REFERENCES users(id)"
                )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS method_templates (
                    id VARCHAR(36) PRIMARY KEY,
                    template_key VARCHAR(64) NOT NULL,
                    version VARCHAR(32) NOT NULL,
                    kind VARCHAR(32) NOT NULL,
                    content TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_by VARCHAR(36) NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_method_template_version (template_key, version),
                    INDEX idx_method_template_key (template_key),
                    FOREIGN KEY (created_by) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id VARCHAR(36) PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL,
                    requested_by VARCHAR(36) NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'queued',
                    progress INT NOT NULL DEFAULT 0,
                    error_message TEXT NOT NULL,
                    context_key VARCHAR(128) NULL,
                    result_profile_id VARCHAR(36) NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    started_at DATETIME NULL,
                    completed_at DATETIME NULL,
                    INDEX idx_analysis_jobs_run_id (run_id),
                    FOREIGN KEY (run_id) REFERENCES assessment_runs(id),
                    FOREIGN KEY (requested_by) REFERENCES users(id),
                    FOREIGN KEY (result_profile_id) REFERENCES metacognitive_profiles(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_annotations (
                    id VARCHAR(36) PRIMARY KEY,
                    coding_id VARCHAR(36) NOT NULL,
                    reviewer_id VARCHAR(36) NOT NULL,
                    dimension VARCHAR(32) NULL,
                    score INT NULL,
                    note TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_coding_reviewer (coding_id, reviewer_id),
                    INDEX idx_coding_annotations_coding_id (coding_id),
                    INDEX idx_coding_annotations_reviewer_id (reviewer_id),
                    FOREIGN KEY (coding_id) REFERENCES coded_segments(id) ON DELETE CASCADE,
                    FOREIGN KEY (reviewer_id) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_adjudications (
                    id VARCHAR(36) PRIMARY KEY,
                    coding_id VARCHAR(36) NOT NULL UNIQUE,
                    adjudicator_id VARCHAR(36) NOT NULL,
                    dimension VARCHAR(32) NULL,
                    score INT NULL,
                    note TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (coding_id) REFERENCES coded_segments(id) ON DELETE CASCADE,
                    FOREIGN KEY (adjudicator_id) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS export_jobs (
                    id VARCHAR(36) PRIMARY KEY,
                    requested_by VARCHAR(36) NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'queued',
                    export_type VARCHAR(32) NOT NULL DEFAULT 'research_csv',
                    storage_path VARCHAR(512) NULL,
                    row_count INT NOT NULL DEFAULT 0,
                    filters JSON NULL,
                    error_message TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME NULL,
                    FOREIGN KEY (requested_by) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id VARCHAR(36) PRIMARY KEY,
                    actor_id VARCHAR(36) NULL,
                    action VARCHAR(64) NOT NULL,
                    target_type VARCHAR(64) NOT NULL,
                    target_id VARCHAR(64) NULL,
                    detail JSON NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_audit_logs_actor_id (actor_id),
                    INDEX idx_audit_logs_action (action),
                    FOREIGN KEY (actor_id) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )

            for key, template in DEFAULT_TEMPLATES.items():
                cursor.execute(
                    """
                    INSERT IGNORE INTO method_templates (
                        id, template_key, version, kind, content, is_active
                    ) VALUES (%s, %s, %s, %s, %s, TRUE)
                    """,
                    (
                        str(uuid.uuid4()),
                        key,
                        template["version"],
                        template["kind"],
                        template["content"],
                    ),
                )
            cursor.execute(
                "UPDATE users SET class_group='演示班' "
                "WHERE id='demo-student-001' AND class_group IS NULL"
            )
            cursor.execute(
                "UPDATE users SET managed_classes='演示班' "
                "WHERE id='demo-teacher-001' "
                "AND (managed_classes IS NULL OR managed_classes='')"
            )
        connection.commit()
        print("Phase-4 research workflow schema and draft templates are ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
