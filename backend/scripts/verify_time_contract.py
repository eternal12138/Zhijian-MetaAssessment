"""Verify UTC database sessions and assessment timestamp ordering."""
import asyncio
from pathlib import Path
import sys

import pymysql
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine


async def _runtime_session_offset() -> int:
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW())")
            )
            return int(result.scalar_one() or 0)
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    runtime_offset = asyncio.run(_runtime_session_offset())
    connection = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
        init_command="SET time_zone = '+00:00'",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW())"
            )
            session_offset = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                """
                SELECT COUNT(*) FROM schema_migrations
                WHERE version='phase19_utc_timestamps'
                """
            )
            migration_markers = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM phase19_timestamp_backup")
            backup_values = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT COUNT(*) FROM assessment_runs
                WHERE completed_at IS NOT NULL AND completed_at < started_at
                """
            )
            invalid_runs = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT COUNT(*) FROM assessment_sessions
                WHERE end_time IS NOT NULL AND end_time < start_time
                """
            )
            invalid_sessions = int(cursor.fetchone()[0])

        print(
            "UTC time contract: "
            f"session_offset_seconds={session_offset}, "
            f"runtime_offset_seconds={runtime_offset}, "
            f"migration_markers={migration_markers}, "
            f"backup_values={backup_values}, "
            f"invalid_runs={invalid_runs}, "
            f"invalid_sessions={invalid_sessions}."
        )
        if (
            session_offset
            or runtime_offset
            or migration_markers != 1
            or invalid_runs
            or invalid_sessions
        ):
            raise SystemExit(1)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
