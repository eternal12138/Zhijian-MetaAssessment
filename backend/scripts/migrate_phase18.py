"""Store the questionnaire participant name/reference without affecting scale scores."""
from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.services.narration_catalog import QUESTIONNAIRE_NARRATION


def main() -> None:
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s
                  AND TABLE_NAME='assessment_runs'
                  AND COLUMN_NAME='questionnaire_participant_name'
                """,
                (settings.DB_NAME,),
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    """
                    ALTER TABLE assessment_runs
                    ADD COLUMN questionnaire_participant_name VARCHAR(255) NULL
                    AFTER questionnaire_source
                    """
                )

            cursor.execute(
                """
                UPDATE narration_assets
                SET is_active=FALSE
                WHERE is_active=TRUE
                  AND slot_key='questionnaire'
                  AND source_text<>%s
                """,
                (QUESTIONNAIRE_NARRATION,),
            )
            disabled_stale_narrations = cursor.rowcount
        print(
            "Phase 18 questionnaire participant name is ready; "
            f"disabled_stale_narrations={disabled_stale_narrations}."
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
