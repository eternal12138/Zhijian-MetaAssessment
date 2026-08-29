"""Real SQL pagination, totals and role isolation; quality evaluation is fixed for fixtures."""
import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, User, AssessmentTask, AssessmentRun, AssessmentSession, CodingBatch, CodingUnit
from app.models.report import MetacognitiveProfile
from app.api import research
from app.core.security import get_current_user
from app.database import get_db


class AsyncDB:
    def __init__(self, db): self.db = db
    async def execute(self, stmt): return self.db.execute(stmt)
    async def scalars(self, stmt): return self.db.scalars(stmt)


class DashboardPaginationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.db.close)
        self.admin = User(id='admin', username='admin', name='Admin', password_hash='test', role='admin')
        self.teacher = User(id='teacher', username='teacher', name='Teacher', password_hash='test', role='teacher', managed_classes='A')
        self.owner = User(id='student', username='student', name='Student', password_hash='test', role='student', class_group='A')
        other = User(id='other', username='other', name='Other', password_hash='test', role='student', class_group='B')
        self.db.add_all([self.admin, self.teacher, self.owner, other])
        self.db.flush()
        self.db.add(AssessmentTask(id='task', title='Task', description='test', scenario='test', publisher_id='admin'))
        self.db.flush()
        stamp = datetime(2026, 8, 1)
        self.db.add(CodingBatch(id='batch', name='Batch', reviewer_a_id='admin', reviewer_b_id='teacher', adjudicator_id='admin', created_by='admin', created_at=stamp))
        for i in range(94):
            owner = 'student' if i < 92 else 'other'
            self.db.add(AssessmentRun(id=f'r{i:03}', user_id=owner, status='completed', completed_at=stamp + timedelta(minutes=i)))
            self.db.flush()
            self.db.add(AssessmentSession(id=f's{i:03}', run_id=f'r{i:03}', user_id=owner, task_id='task', status='completed'))
            self.db.flush()
            if i < 25 or i == 93:
                self.db.add(MetacognitiveProfile(id=f'p{i:03}', run_id=f'r{i:03}', session_id=f's{i:03}', user_id=owner, overall_score=50, generated_at=stamp + timedelta(minutes=i)))
                self.db.add(CodingUnit(id=f'u{i:03}', batch_id='batch', session_id=f's{i:03}', run_id=f'r{i:03}', task_id='task', sequence_no=i, segment='test', status='agreed'))
        self.db.commit()
        p = patch.object(research, 'evaluate_run_quality', return_value={'effective_status': 'eligible'})
        p.start(); self.addCleanup(p.stop)

    def call(self, user=None, **kwargs):
        params = dict(reports_page=1, reports_page_size=10, pending_page=1, pending_page_size=10, user=user or self.admin, db=AsyncDB(self.db))
        params.update(kwargs)
        return asyncio.run(research.research_dashboard(**params))

    def test_all_records_reachable_without_twenty_or_fifty_row_caps(self):
        first = self.call()
        self.assertEqual((first['reports'], first['unanalyzed_total']), (26, 68))
        self.assertEqual((len(first['recent_reports']), len(first['unanalyzed_runs'])), (10, 10))
        self.assertEqual(first['recent_reports'][0]['id'], 'p093')
        self.assertEqual(first['unanalyzed_runs'][0]['run_id'], 'r092')
        report_ids, pending_ids = [], []
        for page in range(1, 8):
            result = self.call(reports_page=min(page, 3), pending_page=page)
            if page <= 3: report_ids.extend(item['id'] for item in result['recent_reports'])
            pending_ids.extend(item['run_id'] for item in result['unanalyzed_runs'])
            self.assertEqual(result['publishable'], 26)
        self.assertEqual(len(set(report_ids)), 26)
        self.assertEqual(len(pending_ids), len(set(pending_ids)))
        self.assertEqual(len(pending_ids), 68)

    def test_pages_clamp_and_teacher_totals_do_not_leak_other_classes(self):
        result = self.call(self.teacher, reports_page=999, pending_page=999)
        self.assertEqual((result['reports_page'], result['pending_page']), (3, 7))
        self.assertEqual((result['reports'], result['unanalyzed_total'], result['publishable']), (25, 67, 25))
        for rows in (result['recent_reports'], result['unanalyzed_runs']):
            self.assertTrue(all(row['user_id'] == 'student' for row in rows))
        self.teacher.managed_classes = 'empty'
        self.db.commit()
        empty = self.call(self.teacher, reports_page=999, pending_page=999)
        self.assertEqual((empty['reports_page'], empty['pending_page'], empty['reports'], empty['unanalyzed_total']), (1, 1, 0, 0))

    def test_latest_coding_batch_controls_publishable_total(self):
        self.db.add(CodingBatch(id='new', name='New', reviewer_a_id='admin', reviewer_b_id='teacher', adjudicator_id='admin', created_by='admin', created_at=datetime(2026, 8, 2)))
        self.db.flush()
        self.db.add(CodingUnit(id='new-unit', batch_id='new', session_id='s000', run_id='r000', task_id='task', sequence_no=1, segment='new', status='pending'))
        self.db.commit()
        result = self.call(reports_page=3)
        self.assertEqual(result['publishable'], 25)
        self.assertEqual(next(row for row in result['recent_reports'] if row['id']=='p000')['double_review_pending'], 1)

    def test_http_rejects_invalid_pages_and_students(self):
        app = FastAPI(); app.include_router(research.router)
        app.dependency_overrides[get_db] = lambda: AsyncDB(self.db)
        app.dependency_overrides[get_current_user] = lambda: self.admin
        with TestClient(app) as client:
            path = research.router.prefix + '/dashboard'
            for params in ({'reports_page': 0}, {'pending_page': -1}, {'reports_page_size': 101}, {'pending_page_size': 0}):
                self.assertEqual(client.get(path, params=params).status_code, 422)
            app.dependency_overrides[get_current_user] = lambda: self.owner
            self.assertEqual(client.get(path).status_code, 403)

    def test_generation_time_controls_order_and_archived_is_not_publishable(self):
        report=self.db.get(MetacognitiveProfile,'p000')
        report.generated_at=datetime(2026,8,20)
        report.version_no=2
        self.db.commit()
        result=self.call()
        self.assertEqual(result['recent_reports'][0]['id'],'p000')
        self.assertTrue(result['recent_reports'][0]['generated_at'].endswith('Z'))
        self.assertEqual(result['recent_reports'][0]['version_no'],2)
        self.assertTrue(result['recent_reports'][0]['can_reanalyze'])
        for state in ['published','archived']:
            report.workflow_status=state;self.db.commit()
            result=self.call()
            self.assertFalse(result['recent_reports'][0]['can_reanalyze'])
            self.assertEqual(result['publishable'],25)
