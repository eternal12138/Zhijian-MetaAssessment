"""Add encrypted model configuration history for administrator rollback."""
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
                CREATE TABLE IF NOT EXISTS system_config_history (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    config_key VARCHAR(64) NOT NULL,
                    config_value LONGTEXT NOT NULL,
                    summary JSON NULL,
                    created_by VARCHAR(36) NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX ix_system_config_history_key (config_key),
                    INDEX ix_system_config_history_created_at (created_at),
                    CONSTRAINT fk_system_config_history_user
                        FOREIGN KEY (created_by) REFERENCES users(id)
                        ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        print("Phase 16 model configuration history is ready.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
