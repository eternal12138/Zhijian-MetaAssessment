"""Create the first production administrator without importing demo accounts."""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import uuid

import bcrypt
import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "").strip()
    name = os.getenv("BOOTSTRAP_ADMIN_NAME", "系统管理员").strip()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")

    if not username or not re.fullmatch(r"[A-Za-z0-9_.-]{2,64}", username):
        raise RuntimeError(
            "BOOTSTRAP_ADMIN_USERNAME 必须为 2-64 位字母、数字、点、横线或下划线"
        )
    if not name or len(name) > 64:
        raise RuntimeError("BOOTSTRAP_ADMIN_NAME 必须为 1-64 个字符")

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
                "SELECT id, role, can_manage_users FROM users WHERE username=%s",
                (username,),
            )
            existing = cursor.fetchone()
            if existing:
                if existing[1] != "admin":
                    raise RuntimeError(
                        "BOOTSTRAP_ADMIN_USERNAME 已被非管理员账号占用"
                    )
                if not existing[2]:
                    cursor.execute(
                        "UPDATE users SET can_manage_users=TRUE WHERE id=%s",
                        (existing[0],),
                    )
                    connection.commit()
                    print(
                        "Bootstrap administrator already exists; "
                        "user-management permission restored."
                    )
                    return
                print("Bootstrap administrator already exists; no changes made.")
                return

            if len(password) < 12 or password == "123456":
                raise RuntimeError(
                    "首次创建管理员时 BOOTSTRAP_ADMIN_PASSWORD "
                    "必须至少 12 位且不能使用默认密码"
                )
            password_hash = bcrypt.hashpw(
                password.encode("utf-8"),
                bcrypt.gensalt(),
            ).decode("utf-8")
            cursor.execute(
                """
                INSERT INTO users (
                    id, username, password_hash, name, role, avatar_text,
                    is_active, must_change_password, token_version,
                    failed_login_attempts, can_manage_users
                ) VALUES (%s, %s, %s, %s, 'admin', %s, TRUE, FALSE, 0, 0, TRUE)
                """,
                (
                    str(uuid.uuid4()),
                    username,
                    password_hash,
                    name,
                    name[0],
                ),
            )
        connection.commit()
        print(f"Bootstrap administrator created: {username}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
