"""Regression coverage for MySQL/SQLAlchemy's differently named run-only keys."""
import os
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pymysql

from app.config import get_settings
from scripts import migrate_phase33 as migration


TARGET = "uq_metacognition_measurement_scope"


class IndexCursor:
    """Metadata double that rejects dropping the last FK-supporting index."""
    def __init__(self, name="run_id", *, target=False):
        self.indexes = {
            "PRIMARY": [(0, "id", None)],
            name: [(0, "run_id", None)],
            "user_lookup": [(1, "user_id", None)],
        }
        # Simulate the actual production case: no secondary run index exists.
        if target:
            self.indexes[TARGET] = [(0, "run_id", None), (0, "scope_key", None)]
        self.commands = []
        self.fail_create = False

    def execute(self, sql, args=None):
        self.commands.append(sql)
        if "ADD UNIQUE INDEX" in sql:
            if self.fail_create:
                raise RuntimeError("creation failed")
            self.indexes[TARGET] = [(0, "run_id", None), (0, "scope_key", None)]
        elif "DROP INDEX" in sql:
            quoted = sql.split("DROP INDEX ", 1)[1]
            name = quoted[1:-1].replace("``", "`")
            other = [value for key, value in self.indexes.items() if key != name]
            if not any(value[0][1] == "run_id" for value in other):
                raise RuntimeError("Cannot drop index needed in a foreign key constraint")
            del self.indexes[name]

    def fetchall(self):
        return [(name, *row) for name, rows in self.indexes.items() for row in rows]


class ScopeIndexMigrationTests(unittest.TestCase):
    def test_orm_and_phase32_names_create_replacement_before_drop(self):
        for name in ("run_id", "uq_metacognition_measurement_run", "renamed`run"):
            with self.subTest(name=name):
                cursor = IndexCursor(name)
                migration._upgrade_scope_index(cursor, "test", "metacognition_measurements")
                self.assertNotIn(name, cursor.indexes)
                self.assertIn(TARGET, cursor.indexes)
                create = next(i for i, sql in enumerate(cursor.commands) if "ADD UNIQUE" in sql)
                drop = next(i for i, sql in enumerate(cursor.commands) if "DROP INDEX" in sql)
                self.assertLess(create, drop)

    def test_resume_after_replacement_created(self):
        cursor = IndexCursor(target=True)
        migration._upgrade_scope_index(cursor, "test", "metacognition_measurements")
        self.assertNotIn("run_id", cursor.indexes)
        self.assertFalse(any("ADD UNIQUE" in sql for sql in cursor.commands))

    def test_second_run_has_no_schema_changes(self):
        cursor = IndexCursor()
        migration._upgrade_scope_index(cursor, "test", "metacognition_measurements")
        cursor.commands.clear()
        migration._upgrade_scope_index(cursor, "test", "metacognition_measurements")
        self.assertFalse(any("ALTER TABLE" in sql for sql in cursor.commands))

    def test_creation_failure_preserves_legacy_key(self):
        cursor = IndexCursor()
        cursor.fail_create = True
        with self.assertRaisesRegex(RuntimeError, "creation failed"):
            migration._upgrade_scope_index(cursor, "test", "metacognition_measurements")
        self.assertIn("run_id", cursor.indexes)
        self.assertFalse(any("DROP INDEX" in sql for sql in cursor.commands))

    def test_wrong_existing_target_is_rejected(self):
        cursor = IndexCursor(target=True)
        cursor.indexes[TARGET] = [(1, "run_id", None), (1, "scope_key", None)]
        with self.assertRaisesRegex(RuntimeError, "Unexpected definition"):
            migration._upgrade_scope_index(cursor, "test", "metacognition_measurements")
        self.assertIn("run_id", cursor.indexes)

    def test_other_indexes_are_preserved(self):
        cursor = IndexCursor()
        others = {
            "run_lookup": [(1, "run_id", None)],
            "other_unique": [(0, "run_id", None), (0, "task_id", None)],
        }
        cursor.indexes.update(others)
        migration._upgrade_scope_index(cursor, "test", "metacognition_measurements")
        for name, definition in others.items():
            self.assertEqual(cursor.indexes[name], definition)
        self.assertIn("PRIMARY", cursor.indexes)


@unittest.skipUnless(os.getenv("MIGRATION_TEST_MYSQL") == "1", "Opt-in isolated MySQL integration test")
class ScopeMigrationMySQLTests(unittest.TestCase):
    def test_full_migration_preserves_rows_and_supports_multiple_task_scopes(self):
        settings = get_settings()
        # Never run the migration on the configured application database.
        # Create and finally remove ONLY this randomly named disposable database.
        database = "test_scope_migration_" + uuid4().hex
        self.assertRegex(database, r"^test_scope_migration_[a-f0-9]{32}$")
        conn = pymysql.connect(host=settings.DB_HOST, port=settings.DB_PORT,
                               user=settings.DB_USER, password=settings.DB_PASSWORD,
                               charset="utf8mb4", autocommit=True)
        created = False
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4")
                created = True
                conn.select_db(database)
                for table in ("users", "assessment_runs", "assessment_tasks"):
                    cursor.execute(f"CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY) ENGINE=InnoDB")
                    cursor.execute(f"INSERT INTO {table} VALUES ('fixture')")
                for legacy_name in ("run_id", "uq_metacognition_measurement_run"):
                    with self.subTest(legacy_name=legacy_name):
                        cursor.execute(f"""CREATE TABLE metacognition_measurements (
                            id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL,
                            run_id VARCHAR(36) NOT NULL, payload VARCHAR(100),
                            UNIQUE KEY `{legacy_name}` (run_id),
                            FOREIGN KEY (user_id) REFERENCES users(id),
                            FOREIGN KEY (run_id) REFERENCES assessment_runs(id) ON DELETE CASCADE
                        ) ENGINE=InnoDB""")
                        cursor.execute("INSERT INTO metacognition_measurements VALUES ('original', 'fixture', 'fixture', 'preserve me')")
                        test_settings = SimpleNamespace(DB_HOST=settings.DB_HOST, DB_PORT=settings.DB_PORT,
                                                        DB_USER=settings.DB_USER, DB_PASSWORD=settings.DB_PASSWORD,
                                                        DB_NAME=database)
                        with patch.object(migration, "get_settings", return_value=test_settings):
                            migration.main()
                            migration.main()
                        cursor.execute("SELECT payload, scope_type, scope_key FROM metacognition_measurements WHERE id='original'")
                        self.assertEqual(cursor.fetchone(), ("preserve me", "run", "run"))
                        cursor.execute("""INSERT INTO metacognition_measurements
                            (id, user_id, run_id, scope_type, scope_key, task_id)
                            VALUES ('task-row', 'fixture', 'fixture', 'task', 'fixture', 'fixture')""")
                        with self.assertRaises(pymysql.err.IntegrityError):
                            cursor.execute("""INSERT INTO metacognition_measurements
                                (id, user_id, run_id, scope_type, scope_key)
                                VALUES ('duplicate', 'fixture', 'fixture', 'task', 'fixture')""")
                        with self.assertRaises(pymysql.err.IntegrityError):
                            cursor.execute("""INSERT INTO metacognition_measurements
                                (id, user_id, run_id, scope_key)
                                VALUES ('orphan', 'fixture', 'missing-parent', 'run')""")
                        cursor.execute("SELECT COUNT(*) FROM metacognition_measurements")
                        self.assertEqual(cursor.fetchone()[0], 2)
                        cursor.execute("DROP TABLE metacognition_measurements")
        finally:
            if created and re.fullmatch(r"test_scope_migration_[a-f0-9]{32}", database):
                with conn.cursor() as cursor:
                    cursor.execute(f"DROP DATABASE `{database}`")
            conn.close()


if __name__ == "__main__":
    unittest.main()
