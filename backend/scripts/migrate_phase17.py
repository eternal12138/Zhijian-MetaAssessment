"""Add auditable manual inclusion/exclusion decisions for completed runs."""
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
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS run_quality_reviews (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL,
                    decision VARCHAR(24) NOT NULL DEFAULT 'automatic',
                    reason TEXT NOT NULL,
                    reviewed_by VARCHAR(36) NULL,
                    reviewed_at DATETIME NULL,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_run_quality_reviews_run (run_id),
                    INDEX ix_run_quality_reviews_decision (decision),
                    CONSTRAINT fk_run_quality_reviews_run
                        FOREIGN KEY (run_id) REFERENCES assessment_runs(id)
                        ON DELETE CASCADE,
                    CONSTRAINT fk_run_quality_reviews_user
                        FOREIGN KEY (reviewed_by) REFERENCES users(id)
                        ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        print("Phase 17 run quality review workflow is ready.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
