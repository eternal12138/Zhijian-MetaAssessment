"""Exercise the real generated column/index, not just their SQL strings."""
import sqlite3
import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable, CreateIndex

from app.database import Base
from app.models.research import MethodTemplate, ModelTrainingJob
from app.models.user import User


class ActiveModelConstraintTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, 'connect')
        def reject_vendor_if(connection, _):
            # Force compatibility with CI SQLite even when the local version
            # provides IF(). No custom implementation should mask the defect.
            connection.set_authorizer(lambda action, arg1, arg2, db, trigger:
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_FUNCTION
                and (arg2 or '').lower() == 'if' else sqlite3.SQLITE_OK)
            connection.execute('PRAGMA foreign_keys=ON')

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.db.close)
        self.db.add(User(id='admin', username='admin', name='Test admin',
                         password_hash='test-only', role='admin'))
        self.db.commit()

    def job(self, name, active=False):
        job = ModelTrainingJob(id=name, version=name, requested_by='admin', is_active=active)
        self.db.add(job)
        return job

    def test_multiple_inactive_versions_but_only_one_active(self):
        self.job('inactive-a')
        self.job('inactive-b')
        active = self.job('active', True)
        self.db.commit()
        self.db.refresh(active)
        self.assertEqual(active.active_scope, 1)
        self.job('second-active', True)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()
        self.assertEqual(self.db.scalars(select(ModelTrainingJob.id).where(
            ModelTrainingJob.is_active.is_(True))).all(), ['active'])

    def test_deactivation_and_rollback_to_an_older_model(self):
        old = self.job('old', True)
        new = self.job('new')
        self.db.commit()
        for previous, next_job in [(old, new), (new, old)]:
            previous.is_active = False
            self.db.flush()
            next_job.is_active = True
            self.db.commit()
            self.db.refresh(previous)
            self.db.refresh(next_job)
            self.assertIsNone(previous.active_scope)
            self.assertEqual(next_job.active_scope, 1)

    def test_mysql_schema_preserves_generated_column_and_unique_index(self):
        table = ModelTrainingJob.__table__
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        self.assertIn('CASE WHEN is_active THEN 1 ELSE NULL END', ddl)
        self.assertIn('STORED', ddl)
        index = next(i for i in table.indexes if i.name == 'uq_training_active_scope')
        self.assertTrue(index.unique)
        self.assertIn('CREATE UNIQUE INDEX', str(CreateIndex(index).compile(dialect=mysql.dialect())))

    def test_only_one_active_version_per_template_key(self):
        first = MethodTemplate(template_key='report_prompt', version='v1', kind='prompt',
                               content='first', is_active=True)
        self.db.add(first)
        self.db.commit()
        self.db.refresh(first)
        self.assertEqual(first.active_template_key, 'report_prompt')
        self.db.add(MethodTemplate(template_key='report_prompt', version='v2', kind='prompt',
                                   content='second', is_active=True))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_different_template_keys_can_each_be_active(self):
        self.db.add_all([
            MethodTemplate(template_key='report_prompt', version='v1', kind='prompt', content='one', is_active=True),
            MethodTemplate(template_key='metacognitive_extractor', version='v1', kind='prompt', content='two', is_active=True),
        ])
        self.db.commit()
        self.assertEqual(len(self.db.scalars(select(MethodTemplate).where(
            MethodTemplate.is_active.is_(True))).all()), 2)

    def test_mysql_template_schema_has_active_key_constraint(self):
        table = MethodTemplate.__table__
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        self.assertIn('CASE WHEN is_active THEN template_key ELSE NULL END', ddl)
        index = next(i for i in table.indexes if i.name == 'uq_method_template_active_key')
        self.assertTrue(index.unique)
