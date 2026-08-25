"""Version the questionnaire and preserve historical 12-item responses."""
from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.services.questionnaire import (
    CURRENT_QUESTIONNAIRE_SOURCE,
    LEGACY_QUESTIONNAIRE_SOURCE,
)


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
                  AND COLUMN_NAME='questionnaire_source'
                """,
                (settings.DB_NAME,),
            )
            column_added = not bool(cursor.fetchone()[0])
            if column_added:
                cursor.execute(
                    f"""
                    ALTER TABLE assessment_runs
                    ADD COLUMN questionnaire_source VARCHAR(32) NOT NULL
                    DEFAULT '{LEGACY_QUESTIONNAIRE_SOURCE}'
                    AFTER questionnaire_enabled
                    """
                )

            cursor.execute(
                """
                UPDATE scale_items
                SET source=%s
                WHERE source='Zepeda-2023-adapted'
                """,
                (LEGACY_QUESTIONNAIRE_SOURCE,),
            )
            if column_added:
                cursor.execute(
                    """
                    UPDATE assessment_runs
                    SET questionnaire_source=%s
                    """,
                    (LEGACY_QUESTIONNAIRE_SOURCE,),
                )
            cursor.execute(
                f"""
                ALTER TABLE assessment_runs
                ALTER questionnaire_source
                SET DEFAULT '{CURRENT_QUESTIONNAIRE_SOURCE}'
                """
            )
            cursor.execute(
                """
                SELECT id, dimension
                FROM scale_dimension_groups
                WHERE dimension IN ('monitoring', 'controlDebugging', 'evaluation')
                ORDER BY
                    CASE
                        WHEN id IN (
                            'dim-monitoring-2026-2',
                            'dim-control-2026-2',
                            'dim-evaluation-2026-2'
                        ) THEN 0
                        ELSE 1
                    END,
                    id
                """
            )
            groups_by_dimension: dict[str, str] = {}
            for group_id, dimension in cursor.fetchall():
                groups_by_dimension.setdefault(dimension, group_id)
            if set(groups_by_dimension) == {
                "monitoring",
                "controlDebugging",
                "evaluation",
            }:
                seed_text = (BACKEND_ROOT / "seed_phase2.sql").read_text(
                    encoding="utf-8"
                )
                questionnaire_statement = next(
                    statement.strip()
                    for statement in seed_text.split(";")
                    if statement.strip().startswith("INSERT INTO scale_items")
                )
                questionnaire_statement = questionnaire_statement.replace(
                    "'dim-monitoring-2026-2'",
                    f"'{groups_by_dimension['monitoring']}'",
                ).replace(
                    "'dim-control-2026-2'",
                    f"'{groups_by_dimension['controlDebugging']}'",
                ).replace(
                    "'dim-evaluation-2026-2'",
                    f"'{groups_by_dimension['evaluation']}'",
                )
                cursor.execute(questionnaire_statement)
                cursor.execute(
                    """
                    SELECT COUNT(*), COALESCE(SUM(reversed), 0)
                    FROM scale_items
                    WHERE source=%s
                    """,
                    (CURRENT_QUESTIONNAIRE_SOURCE,),
                )
                item_count, reversed_count = cursor.fetchone()
                if int(item_count) != 24 or int(reversed_count) != 1:
                    raise RuntimeError(
                        "正式问卷初始化失败：应为 24 题且仅 1 道反向题"
                    )
                cursor.execute(
                    """
                    UPDATE assessment_runs r
                    SET r.questionnaire_source=%s
                    WHERE r.status='in_progress'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM questionnaire_responses q
                          WHERE q.run_id=r.id
                      )
                    """,
                    (CURRENT_QUESTIONNAIRE_SOURCE,),
                )
        connection.commit()
        print("Phase 11 questionnaire versioning schema is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
