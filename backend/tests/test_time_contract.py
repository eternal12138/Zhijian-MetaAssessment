from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from app.core.time import as_utc, utc_isoformat, utc_now_naive
from app.schemas.notification import NotificationOut
from app.schemas.asr import AsrJobOut


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TimeContractTests(unittest.TestCase):
    def test_utc_now_is_naive_for_mysql_datetime_storage(self):
        value = utc_now_naive()
        self.assertIsNone(value.tzinfo)
        self.assertLess(
            abs((datetime.now(timezone.utc).replace(tzinfo=None) - value).total_seconds()),
            2,
        )

    def test_utc_isoformat_marks_naive_database_value_as_utc(self):
        value = datetime(2026, 8, 10, 9, 30, 0)
        self.assertEqual(utc_isoformat(value), "2026-08-10T09:30:00Z")

    def test_utc_isoformat_converts_aware_offsets(self):
        china_time = datetime(
            2026, 8, 10, 17, 30, 0,
            tzinfo=timezone(timedelta(hours=8)),
        )
        self.assertEqual(utc_isoformat(china_time), "2026-08-10T09:30:00Z")
        self.assertEqual(as_utc(china_time).utcoffset(), timedelta(0))

    def test_api_schema_serializes_datetime_with_explicit_z(self):
        model = NotificationOut(
            id="notification-1",
            type="system",
            title="test",
            content="test",
            target_url="/",
            priority="normal",
            is_read=False,
            created_at=datetime(2026, 8, 10, 9, 30, 0),
        )
        self.assertEqual(
            model.model_dump(mode="json")["created_at"],
            "2026-08-10T09:30:00Z",
        )

    def test_orm_response_schema_keeps_inherited_utc_serializer(self):
        model = AsrJobOut(
            id="job-1",
            session_id="session-1",
            provider="volcengine",
            model="test",
            config_version="1",
            status="completed",
            expected_chunk_count=1,
            language="zh",
            retry_count=0,
            max_retries=3,
            created_at=datetime(2026, 8, 10, 9, 30, 0),
            updated_at=datetime(2026, 8, 10, 9, 31, 0),
        )
        payload = model.model_dump(mode="json")
        self.assertEqual(payload["created_at"], "2026-08-10T09:30:00Z")
        self.assertEqual(payload["updated_at"], "2026-08-10T09:31:00Z")

    def test_phase19_is_in_local_and_production_migration_chains(self):
        migration_name = "migrate_phase19.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")

        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("phase19_timestamp_backup", migration)
        self.assertIn("schema_migrations", migration)
        self.assertIn("UTC_TIMESTAMP()", migration)
        self.assertIn("assessment_runs", migration)
        self.assertIn("assessment_sessions", migration)

    def test_runtime_database_connections_initialize_in_utc(self):
        database_module = (
            PROJECT_ROOT / "backend" / "app" / "database.py"
        ).read_text(encoding="utf-8")
        self.assertIn("SET time_zone = '+00:00'", database_module)


if __name__ == "__main__":
    unittest.main()
