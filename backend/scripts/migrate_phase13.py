"""Persist immutable coding-batch scope criteria and creation summaries."""
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
            for column_name in ("scope_filter", "scope_summary"):
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=%s
                      AND TABLE_NAME='coding_batches'
                      AND COLUMN_NAME=%s
                    """,
                    (settings.DB_NAME, column_name),
                )
                if not cursor.fetchone()[0]:
                    cursor.execute(
                        f"""
                        ALTER TABLE coding_batches
                        ADD COLUMN {column_name} JSON NULL
                        AFTER rubric_version
                        """
                    )
        connection.commit()
        print("Phase 13 coding-batch scope metadata is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
