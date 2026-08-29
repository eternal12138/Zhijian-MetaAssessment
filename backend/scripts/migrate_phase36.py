"""Repair duplicate active prompts and enforce one active version per key."""
from __future__ import annotations

from pathlib import Path
import sys
import uuid

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.services.report_prompt_v2 import CONTENT as REPORT_PROMPT_CONTENT
from app.services.report_prompt_v2 import VERSION as REPORT_PROMPT_VERSION


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
            cursor.execute(
                """SELECT id FROM method_templates
                WHERE template_key='report_prompt' AND version=%s""",
                (REPORT_PROMPT_VERSION,),
            )
            report_prompt_id = cursor.fetchone()
            if report_prompt_id:
                report_prompt_id = report_prompt_id[0]
                cursor.execute(
                    "UPDATE method_templates SET content=%s WHERE id=%s",
                    (REPORT_PROMPT_CONTENT, report_prompt_id),
                )
            else:
                report_prompt_id = str(uuid.uuid4())
                cursor.execute(
                    """INSERT INTO method_templates
                    (id, template_key, version, kind, content, is_active)
                    VALUES (%s, 'report_prompt', %s, 'prompt', %s, FALSE)""",
                    (report_prompt_id, REPORT_PROMPT_VERSION, REPORT_PROMPT_CONTENT),
                )
            # This migration represents the administrator-approved prompt rollout.
            cursor.execute(
                "UPDATE method_templates SET is_active = FALSE WHERE template_key='report_prompt'"
            )
            cursor.execute(
                "UPDATE method_templates SET is_active = TRUE WHERE id=%s",
                (report_prompt_id,),
            )
            cursor.execute(
                """SELECT id, template_key FROM method_templates
                WHERE is_active = TRUE
                ORDER BY template_key ASC, created_at DESC, id DESC"""
            )
            active_seen: set[str] = set()
            for template_id, template_key in cursor.fetchall():
                if template_key in active_seen:
                    cursor.execute(
                        "UPDATE method_templates SET is_active = FALSE WHERE id = %s",
                        (template_id,),
                    )
                else:
                    active_seen.add(template_key)

            if not _column_exists(
                cursor, settings.DB_NAME, "method_templates", "active_template_key"
            ):
                cursor.execute(
                    """ALTER TABLE method_templates
                    ADD COLUMN active_template_key VARCHAR(64)
                    GENERATED ALWAYS AS
                    (CASE WHEN is_active THEN template_key ELSE NULL END) STORED"""
                )
            if not _index_exists(
                cursor, settings.DB_NAME, "method_templates", "uq_method_template_active_key"
            ):
                cursor.execute(
                    """ALTER TABLE method_templates ADD UNIQUE INDEX
                    uq_method_template_active_key (active_template_key)"""
                )
        connection.commit()
        print("Phase 36 single-active-prompt constraint completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
