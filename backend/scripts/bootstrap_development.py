"""Create local-only demonstration accounts when they are missing."""
from __future__ import annotations

from pathlib import Path
import sys
import uuid

import bcrypt
import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


DEMO_USERS = (
    ("student", "演示学生", "student", "学", "演示班", False),
    ("teacher", "演示教师", "teacher", "师", None, False),
    ("admin", "演示管理员", "admin", "管", None, True),
)


def main() -> None:
    settings = get_settings()
    if not settings.APP_DEBUG:
        raise RuntimeError("演示账号只能在 APP_DEBUG=true 的本地开发环境创建")

    password_hash = bcrypt.hashpw(
        b"123456",
        bcrypt.gensalt(),
    ).decode("utf-8")
    connection = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
        autocommit=False,
    )
    created: list[str] = []
    try:
        with connection.cursor() as cursor:
            for username, name, role, avatar, class_group, can_manage in DEMO_USERS:
                cursor.execute(
                    "SELECT role FROM users WHERE username=%s",
                    (username,),
                )
                existing = cursor.fetchone()
                if existing:
                    if existing[0] != role:
                        raise RuntimeError(
                            f"本地演示用户名 {username} 已被其他角色占用"
                        )
                    continue
                cursor.execute(
                    """
                    INSERT INTO users (
                        id, username, password_hash, name, role, avatar_text,
                        class_group, is_active, must_change_password,
                        token_version, failed_login_attempts, can_manage_users
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, TRUE, TRUE, 0, 0, %s
                    )
                    """,
                    (
                        str(uuid.uuid4()),
                        username,
                        password_hash,
                        name,
                        role,
                        avatar,
                        class_group,
                        can_manage,
                    ),
                )
                created.append(username)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    if created:
        print(f"Local demo accounts created: {', '.join(created)}")
    else:
        print("Local demo accounts are already ready.")


if __name__ == "__main__":
    main()
