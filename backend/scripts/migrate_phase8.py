"""Idempotent production-security migration for user credentials."""
from pathlib import Path
import sys

import bcrypt
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

    def column_exists(cursor, column: str) -> bool:
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=%s AND TABLE_NAME='users' AND COLUMN_NAME=%s
            """,
            (settings.DB_NAME, column),
        )
        return bool(cursor.fetchone()[0])

    try:
        with connection.cursor() as cursor:
            columns = {
                "must_change_password":
                    "BOOLEAN NOT NULL DEFAULT FALSE AFTER is_active",
                "token_version":
                    "INT NOT NULL DEFAULT 0 AFTER must_change_password",
                "failed_login_attempts":
                    "INT NOT NULL DEFAULT 0 AFTER token_version",
                "locked_until":
                    "DATETIME NULL AFTER failed_login_attempts",
            }
            for name, definition in columns.items():
                if not column_exists(cursor, name):
                    cursor.execute(
                        f"ALTER TABLE users ADD COLUMN {name} {definition}"
                    )

            cursor.execute("SELECT id, password_hash FROM users")
            default_password_users: list[str] = []
            for user_id, password_hash in cursor.fetchall():
                try:
                    if bcrypt.checkpw(
                        b"123456",
                        str(password_hash).encode("utf-8"),
                    ):
                        default_password_users.append(user_id)
                except (ValueError, TypeError):
                    continue
            if default_password_users:
                placeholders = ",".join(["%s"] * len(default_password_users))
                cursor.execute(
                    "UPDATE users SET must_change_password=TRUE "
                    f"WHERE id IN ({placeholders})",
                    default_password_users,
                )
        connection.commit()
        print("Phase 8 production-security migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
