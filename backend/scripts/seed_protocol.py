"""Idempotently publish the versioned official assessment protocol."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


OFFICIAL_TASK_IDS = (
    "task-pitching-2026-2",
    "task-jumps-2026-2",
)


def main(*, skip_if_active: bool = False) -> None:
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
                "SELECT COUNT(*) FROM assessment_runs WHERE status='in_progress'"
            )
            in_progress_count = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT COUNT(*) FROM assessment_tasks
                WHERE id IN (%s, %s) AND status='published'
                """,
                OFFICIAL_TASK_IDS,
            )
            current_protocol_task_count = int(cursor.fetchone()[0])
            if in_progress_count and current_protocol_task_count < len(
                OFFICIAL_TASK_IDS
            ):
                if skip_if_active:
                    print(
                        "An assessment is in progress; keeping the current "
                        "protocol for local development."
                    )
                    return
                raise RuntimeError(
                    "检测到进行中的测评，不能切换到协议 2026.2。"
                    "请先让参与者完成测评，或由管理员将无效测评标记为放弃。"
                )

            cursor.execute(
                """
                SELECT id FROM users
                WHERE role='admin' AND is_active=TRUE
                ORDER BY can_manage_users DESC, created_at ASC
                LIMIT 1
                """
            )
            publisher = cursor.fetchone()
            if not publisher:
                raise RuntimeError(
                    "正式测评协议初始化前必须先创建至少一个管理员"
                )
            cursor.execute("SET @protocol_publisher_id=%s", (publisher[0],))

            seed_path = BACKEND_ROOT / "seed_phase2.sql"
            statements = [
                statement.strip()
                for statement in seed_path.read_text(encoding="utf-8").split(";")
                if statement.strip()
            ]
            for statement in statements:
                cursor.execute(statement)
        connection.commit()
        print("Official assessment protocol 2026.2 is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-if-active",
        action="store_true",
        help="Keep the current protocol when an assessment is in progress.",
    )
    arguments = parser.parse_args()
    main(skip_if_active=arguments.skip_if_active)
