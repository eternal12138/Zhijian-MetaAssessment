"""Optional real MySQL validation, using an isolated disposable database only."""
import os
import re
import unittest
import uuid
from unittest.mock import patch

import pymysql
from app.config import get_settings
from scripts import migrate_phase34


@unittest.skipUnless(os.getenv("MIGRATION_TEST_MYSQL") == "1", "Opt-in isolated MySQL integration test")
class CorrectionMigrationTests(unittest.TestCase):
    def test_idempotent_migration_preserves_rows_versions_and_cascades(self):
        settings = get_settings()
        database = "test_correction_" + uuid.uuid4().hex
        connection = pymysql.connect(host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER, password=settings.DB_PASSWORD, autocommit=True, charset="utf8mb4")
        created = False
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                created = True
                cursor.execute(f"USE `{database}`")
                cursor.execute("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)")
                cursor.execute("CREATE TABLE assessment_sessions (id VARCHAR(36) PRIMARY KEY)")
                cursor.execute("INSERT INTO users VALUES ('admin')")
                cursor.execute("INSERT INTO assessment_sessions VALUES ('session')")
                with patch.object(migrate_phase34, "get_settings", return_value=settings.model_copy(update={"DB_NAME": database})):
                    migrate_phase34.main()
                    cursor.execute("""INSERT INTO measurement_corrections
                        (id,session_id,uploaded_by,filename,file_sha256,dialogues,dimension_counts,effective_dialogue_count,version_no)
                        VALUES ('v1','session','admin','review.csv',%s,'[]','{}',1,1)""", ("a" * 64,))
                    migrate_phase34.main()
                cursor.execute("SELECT version_no FROM measurement_corrections")
                self.assertEqual(cursor.fetchall(), ((1,),))
                cursor.execute("DELETE FROM assessment_sessions WHERE id='session'")
                cursor.execute("SELECT COUNT(*) FROM measurement_corrections")
                self.assertEqual(cursor.fetchone()[0], 0)
        finally:
            if created and re.fullmatch(r"test_correction_[a-f0-9]{32}", database):
                with connection.cursor() as cursor: cursor.execute(f"DROP DATABASE `{database}`")
            connection.close()
