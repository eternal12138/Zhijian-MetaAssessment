"""Idempotent migration for in-app notifications."""
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL,
                    event_key VARCHAR(160) NULL UNIQUE,
                    type VARCHAR(32) NOT NULL DEFAULT 'system',
                    title VARCHAR(128) NOT NULL,
                    content TEXT NOT NULL,
                    target_url VARCHAR(512) NOT NULL DEFAULT '/',
                    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
                    is_read BOOLEAN NOT NULL DEFAULT FALSE,
                    metadata JSON NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    read_at DATETIME NULL,
                    INDEX idx_notifications_user_id (user_id),
                    INDEX idx_notifications_user_unread (user_id, is_read, created_at),
                    CONSTRAINT fk_notifications_user
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        connection.commit()
        print("Phase-5 notification schema is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
