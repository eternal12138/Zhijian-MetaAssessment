"""Draft review and publication authorization on a disposable SQL database."""
import unittest
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, User, AssessmentRun, AssessmentTask, AssessmentSession
from app.models.report import MetacognitiveProfile
from app.models.research import AuditLog
from app.models.notification import Notification
from app.api import reports, research
from app.database import get_db
from app.core.security import get_current_user


class AsyncDB:
    def __init__(self, db): self.db = db
    async def execute(self, stmt): return self.db.execute(stmt)
    async def scalar(self, stmt): return self.db.scalar(stmt)
    async def scalars(self, stmt): return self.db.scalars(stmt)
    async def get(self, model, key, **kwargs): return self.db.get(model, key, **kwargs)
    async def flush(self): self.db.flush()
    def add(self, item): self.db.add(item)
    async def refresh(self, item): self.db.refresh(item)
    async def commit(self): self.db.commit()
    async def rollback(self): self.db.rollback()
    async def __aenter__(self): return self
    async def __aexit__(self, *args):
        if args[0]: self.db.rollback()
    @asynccontextmanager
    async def begin_nested(self):
        with self.db.begin_nested():
            yield


class ReportReviewFlowTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.db = Session(engine, expire_on_commit=False)
        self.addCleanup(self.db.close)
        self.users = {role: User(id=role, username=role, name=role, role=role, password_hash='test', class_group='A' if role=='student' else None, managed_classes='A' if role=='teacher' else None) for role in ['admin','teacher','student']}
        self.db.add_all(self.users.values()); self.db.flush()
        self.run = AssessmentRun(id='run', user_id='student', status='completed', completed_at=datetime(2026,8,1))
        self.db.add(self.run)
        self.db.add(AssessmentTask(id='task', title='task', description='test', scenario='test', publisher_id='admin')); self.db.flush()
        self.db.add(AssessmentSession(id='session', user_id='student', task_id='task', run_id='run')); self.db.flush()
        self.profile = MetacognitiveProfile(id='profile', user_id='student', session_id='session', run_id='run', summary='真实草稿内容', generated_at=datetime(2026,8,1), workflow_status='draft')
        self.db.add(self.profile); self.db.commit()
        self.add_correction('session', 'correction1')
        from app.services.report_evidence import build_report_snapshot
        self.profile.evidence_snapshot = asyncio.run(build_report_snapshot('run', AsyncDB(self.db)))
        self.profile.generation_metadata = {'status':'ai_success', 'model':'test'}
        self.db.commit()
        self.quality = AsyncMock(return_value=(self.run, None, {'effective_status':'eligible'}))
        self.pending = AsyncMock(return_value=0)
        for p in [patch.object(research,'_quality_for_run',self.quality), patch.object(research,'_coding_unit_pending_for_run',self.pending),
                  patch('app.services.metacognition_measurement.calculate_and_persist_measurement',new=AsyncMock(side_effect=ValueError('无测量数据')))]:
            p.start(); self.addCleanup(p.stop)
        app = FastAPI(); app.include_router(reports.router); app.include_router(research.router)
        self.actor = self.users['admin']
        app.dependency_overrides[get_current_user] = lambda: self.actor
        app.dependency_overrides[get_db] = lambda: AsyncDB(self.db)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def publish(self, **kwargs):
        data = {'note':'审阅确认', 'review_confirmed':True, 'expected_generated_at': self.profile.generated_at.isoformat()}
        data.update(kwargs)
        return self.client.post('/research/reports/profile/publish', json=data)

    def add_correction(self, session_id, correction_id):
        from app.models.report import MeasurementCorrection
        self.db.add(MeasurementCorrection(id=correction_id, session_id=session_id, uploaded_by='admin',
            filename='test.csv', file_sha256='a'*64, dialogues=[{'text':'核对结果', 'label':'monitoring'}],
            dimension_counts={'monitoring':1,'controlDebugging':0,'evaluation':0},
            effective_dialogue_count=1, version_no=1))
        self.db.commit()

    def test_staff_read_draft_and_student_only_sees_it_after_publication(self):
        for role in ['admin','teacher']:
            self.actor=self.users[role]
            response=self.client.get('/research/reports/profile/review')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['report']['summary'],'真实草稿内容')
            self.assertTrue(response.json()['can_publish'])
            self.assertEqual(self.client.get('/reports/runs/run').status_code,200)
        self.actor=self.users['student']
        self.assertEqual(self.client.get('/reports/profile').status_code,404)
        self.assertEqual(self.client.get('/research/reports/profile/review').status_code,403)
        self.assertEqual(self.publish().status_code,403)
        self.actor=self.users['teacher']
        self.assertEqual(self.publish().status_code,200)
        self.db.flush()
        audit=self.db.scalar(select(AuditLog).where(AuditLog.action=='report.publish'))
        self.assertTrue(audit.detail['review_confirmed'])
        self.assertEqual(audit.detail['note'],'审阅确认')
        self.assertEqual(len(self.db.scalars(select(Notification)).all()),1)
        self.assertEqual(self.publish().status_code,409)
        self.assertEqual(len(self.db.scalars(select(Notification)).all()),1)
        self.actor=self.users['student']
        self.assertEqual(self.client.get('/reports/profile').status_code,200)

    def test_teacher_cannot_read_or_publish_other_class(self):
        self.users['teacher'].managed_classes='B'; self.db.commit(); self.actor=self.users['teacher']
        self.assertEqual(self.client.get('/research/reports/profile/review').status_code,403)
        self.assertEqual(self.client.get('/reports/profile').status_code,403)
        self.assertEqual(self.publish().status_code,403)

    def test_risky_draft_is_readable_and_publishable_after_risk_acknowledgement(self):
        self.pending.return_value=None
        self.profile.requires_review_count=2; self.db.commit()
        response=self.client.get('/research/reports/profile/review')
        self.assertEqual(response.status_code,200)
        # Only overridable checks fail, so publishing is unlocked after confirming risks.
        self.assertTrue(response.json()['can_publish'])
        self.assertTrue(response.json()['risks'])
        error=self.publish()
        self.assertEqual(error.status_code,409)
        self.assertIn('确认风险警告', error.json()['detail'])
        for check in response.json()['checks']:
            if not check['passed']: self.assertIn(check['message'],error.json()['detail'])
        self.assertEqual(self.profile.workflow_status,'draft')
        self.assertEqual(self.publish(acknowledge_risks=True).status_code,200)
        self.assertEqual(self.profile.workflow_status,'published')
        self.assertEqual(len(self.db.scalars(select(Notification)).all()),1)

    def test_stale_or_unconfirmed_review_cannot_publish(self):
        old=(self.profile.generated_at-timedelta(minutes=1)).isoformat()
        self.assertEqual(self.publish(expected_generated_at=old).status_code,409)
        self.assertEqual(self.publish(review_confirmed=False).status_code,422)
        self.quality.return_value=(self.run,None,{'effective_status':'ineligible'})
        self.assertEqual(self.publish().status_code,409)

    def prepare_refresh(self):
        from app.models.session import CodedSegment, TranscriptSegment
        from app.models.report import LearningSuggestion
        from app.services import report_analyzer
        self.db.add(AssessmentSession(id='session2', user_id='student', task_id='task', run_id='run', sequence_no=2))
        self.db.add(TranscriptSegment(id='text1',session_id='session',client_segment_id='text1',text='我检查一下条件',is_final=True))
        self.db.flush()
        self.db.add(CodedSegment(id='code1',session_id='session',transcript_segment_id='text1',segment='我检查一下条件',dimension='monitoring',score=5,human_score=7,confidence=.9,needs_review=False))
        self.db.add(LearningSuggestion(id='old-suggestion',profile_id='profile',dimension='monitoring',title='原建议',description='保留',practices='[]'))
        self.db.commit()
        self.add_correction('session2', 'correction2')
        self.ai = AsyncMock(return_value={
            'summary':'新的 AI 画像内容', 'level':'发展中', 'strengths':['监控'], 'weaknesses':['评估'],
            'suggestions':[{'dimension':d,'title':'复盘','description':'核对结果','practices':[
                '立即尝试：解释方法','练习安排：每次任务后','效果检查：记录是否完成']}
                           for d in ('monitoring','controlDebugging','evaluation')],
        })
        self.recode = AsyncMock(side_effect=AssertionError('must not re-code original evidence'))
        for p in [patch.object(report_analyzer, 'load_runtime_model_settings', AsyncMock()),
                  patch.object(report_analyzer.settings,'REPORT_USE_LLM',True),
                  patch('app.services.analysis_agent.AnalysisAgent.generate_metacognitive_profile',self.ai),
                  patch.object(report_analyzer,'analyze_transcripts',self.recode)]:
            p.start();self.addCleanup(p.stop)

    def test_publish_requires_confirmation_even_without_timestamp(self):
        for data in ({}, {'review_confirmed':False}, {'review_confirmed':True}):
            self.assertEqual(self.client.post('/research/reports/profile/publish', json=data).status_code,422)
        response=self.client.post('/research/reports/bulk-publish',json={'report_ids':['profile'],'review_confirmed':True})
        self.assertEqual(response.json()['processed'],0)
        self.assertEqual(self.profile.workflow_status,'draft')

    def test_snapshot_drift_blocks_publish_even_if_counts_unchanged(self):
        from app.models.report import MeasurementCorrection
        correction=self.db.get(MeasurementCorrection,'correction1')
        correction.dialogues=[{'text':'更正后的不同文字','label':'monitoring'}];self.db.commit()
        response=self.publish()
        self.assertEqual(response.status_code,409)
        self.assertIn('数据已更新',response.text)

    def test_published_snapshot_is_identical_for_all_roles_after_data_changes(self):
        from app.models.report import MeasurementCorrection
        self.assertEqual(self.publish().status_code,200)
        published=self.client.get('/reports/profile').json()
        original=published['measurement_snapshot']
        original_pattern=published['metacognition_pattern']
        correction=self.db.get(MeasurementCorrection,'correction1')
        correction.dimension_counts={'monitoring':0,'controlDebugging':0,'evaluation':1}
        correction.dialogues=[{'text':'重新核验','label':'evaluation'}];self.db.commit()
        for role in ('admin','teacher','student'):
            self.actor=self.users[role]
            result=self.client.get('/reports/profile').json()
            self.assertEqual(result['measurement_snapshot'],original)
            self.assertEqual(result['metacognition_pattern'],original_pattern)
            self.assertFalse(result['overall_score_available'])
        self.actor=self.users['admin']
        self.assertEqual(self.client.get('/research/reports/profile/review').json()['measurement'],original)

    def test_queue_deduplicates_and_exposes_state_without_calling_ai(self):
        self.prepare_refresh()
        first=self.client.post('/research/analysis/runs/run',json={})
        second=self.client.post('/research/analysis/runs/run',json={})
        self.assertEqual(first.status_code,202)
        self.assertEqual(first.json()['id'],second.json()['id'])
        self.assertEqual(first.json()['status'],'queued')
        self.ai.assert_not_awaited()
        self.assertEqual(self.client.get('/research/analysis/jobs').json()[0]['status'],'queued')
        self.assertEqual(self.publish().status_code,409)

    def test_worker_slot_and_stale_recovery_allow_retry_without_server_restart(self):
        from app.services import report_jobs
        from app.models.research import AnalysisJob
        self.prepare_refresh()
        response=self.client.post('/research/analysis/runs/run',json={})
        self.db.commit()
        with patch.object(report_jobs,'AsyncSessionLocal',lambda:AsyncDB(self.db)):
            self.assertEqual(asyncio.run(report_jobs.claim_report_job()),response.json()['id'])
            self.assertIsNone(asyncio.run(report_jobs.claim_report_job()))
            job=self.db.get(AnalysisJob,response.json()['id'])
            job.heartbeat_at=datetime.utcnow()-timedelta(minutes=4);self.db.commit()
            self.assertIsNone(asyncio.run(report_jobs.claim_report_job()))
        self.assertEqual(job.status,'failed')
        self.assertIsNone(job.active_run_id)
        self.assertIsNone(job.running_slot)
        retry=self.client.post('/research/analysis/runs/run',json={})
        self.assertEqual(retry.status_code,202)
        self.assertNotEqual(retry.json()['id'],job.id)

    def test_bulk_publish_requires_each_reviewed_version(self):
        bad=self.client.post('/research/reports/bulk-publish',json={'report_ids':['profile'],
            'review_confirmed':True,'reviewed_versions':{'profile':'2000-01-01T00:00:00Z'}})
        self.assertEqual(bad.json()['processed'],0)
        good=self.client.post('/research/reports/bulk-publish',json={'report_ids':['profile'],
            'review_confirmed':True,'reviewed_versions':{'profile':self.profile.generated_at.isoformat()}})
        self.assertEqual(good.json()['processed'],1)

    def test_first_generation_ai_failure_is_not_reported_as_completed(self):
        self.prepare_refresh()
        self.db.delete(self.profile);self.db.commit()
        self.ai.return_value=None
        response=self.refresh_report(report_only=False,expected_generated_at=None)
        self.assertEqual(response.json()['status'],'failed')
        self.assertIsNone(self.db.get(MetacognitiveProfile,'profile'))

    def test_revision_history_keeps_old_draft_and_denies_student(self):
        self.prepare_refresh()
        self.assertEqual(self.refresh_report().json()['status'],'completed')
        history=self.client.get('/research/reports/profile/versions').json()
        self.assertEqual(history['total'],1)
        self.assertEqual(history['items'][0]['content']['summary'],'真实草稿内容')
        self.actor=self.users['student']
        self.assertEqual(self.client.get('/research/reports/profile/versions').status_code,403)

    def test_data_edit_during_ai_call_preserves_draft(self):
        from app.models.report import MeasurementCorrection
        self.prepare_refresh()
        valid=self.ai.return_value
        async def edit_during_call(**kwargs):
            correction=self.db.get(MeasurementCorrection,'correction1')
            correction.dialogues=[{'text':'生成期间更改文本','label':'monitoring'}]
            self.db.commit()
            return valid
        self.ai.side_effect=edit_during_call
        result=self.refresh_report().json()
        self.assertEqual(result['status'],'failed')
        self.assertIn('数据已更新',result['error_message'])
        self.assertEqual(self.profile.summary,'真实草稿内容')
        self.assertEqual(self.profile.version_no,1)

    def refresh_report(self, **kwargs):
        data={'report_only':True,'expected_generated_at':self.profile.generated_at.isoformat()}
        data.update(kwargs)
        response = self.client.post('/research/analysis/runs/run',json=data)
        if response.status_code == 202:
            self.db.commit()
            from app.services import report_jobs
            async def process():
                job_id = await report_jobs.claim_report_job()
                if job_id: await report_jobs.process_report_job(job_id)
            with patch.object(report_jobs, 'AsyncSessionLocal', lambda: AsyncDB(self.db)):
                asyncio.run(process())
            return self.client.get('/research/analysis/jobs/' + response.json()['id'])
        return response

    def test_ai_refresh_changes_draft_version_not_original_coding_or_publication(self):
        from app.models.session import CodedSegment
        self.prepare_refresh(); old=self.profile.generated_at
        response=self.refresh_report()
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'completed',response.text)
        self.assertEqual(self.profile.summary,'新的 AI 画像内容')
        self.assertEqual(self.profile.version_no,2)
        self.assertGreater(self.profile.generated_at,old)
        self.assertNotEqual(self.profile.workflow_status,'published')
        self.assertTrue(self.profile.is_provisional)
        self.assertIsNone(self.profile.published_at)
        self.assertEqual(self.db.get(CodedSegment,'code1').human_score,7)
        self.recode.assert_not_awaited()
        self.assertEqual(self.publish(expected_generated_at=old.isoformat()).status_code,409)
        audit=self.db.scalar(select(AuditLog).where(AuditLog.action=='analysis.complete'))
        self.assertEqual(audit.detail['version_no'],2)

    def test_failed_ai_refresh_keeps_original_draft_and_can_retry(self):
        self.prepare_refresh();old=self.profile.generated_at
        valid=self.ai.return_value
        for invalid in (None, {}, {'summary':'partial'}):
            self.ai.return_value=invalid
            result=self.refresh_report().json()
            self.assertEqual(result['status'],'failed',result)
            self.assertIn('原草稿已保留',result['error_message'])
            self.assertEqual(self.profile.summary,'真实草稿内容')
            self.assertEqual(self.profile.generated_at,old)
            self.assertEqual(self.profile.version_no,1)
            self.assertEqual(self.profile.suggestions[0].title,'原建议')
        self.ai.return_value=valid
        self.assertEqual(self.refresh_report().json()['status'],'completed')

    def test_refresh_rejects_stale_published_archived_and_invalid_mode(self):
        self.prepare_refresh()
        self.assertEqual(self.refresh_report(reanalyze=True).status_code,422)
        self.assertEqual(self.refresh_report(expected_generated_at=None).status_code,422)
        self.assertEqual(self.refresh_report(expected_generated_at='2020-01-01T00:00:00Z').status_code,409)
        for state in ['published','archived']:
            self.profile.workflow_status=state; self.db.commit()
            self.assertEqual(self.refresh_report().status_code,409)
            # The old generation endpoint must not bypass the same guard.
            self.assertEqual(self.client.post('/reports/runs/run/generate',json={}).status_code,409)
        self.ai.assert_not_awaited()

    def test_refresh_enforces_teacher_scope_and_student_denial(self):
        self.prepare_refresh()
        self.actor=self.users['student']
        self.assertEqual(self.refresh_report().status_code,403)
        self.actor=self.users['teacher'];self.actor.managed_classes='B';self.db.commit()
        self.assertEqual(self.refresh_report().status_code,403)
        self.ai.assert_not_awaited()
        self.actor.managed_classes='A';self.db.commit()
        self.assertEqual(self.refresh_report().json()['status'],'completed')

    def test_disabled_ai_preserves_draft_without_rule_fallback(self):
        from app.services import report_analyzer
        self.prepare_refresh()
        with patch.object(report_analyzer.settings,'REPORT_USE_LLM',False):
            result=self.refresh_report().json()
        self.assertEqual(result['status'],'failed')
        self.assertIn('未启用',result['error_message'])
        self.assertEqual(self.profile.summary,'真实草稿内容')
        self.ai.assert_not_awaited()

    def test_later_expert_batch_completes_without_overwriting_published_report(self):
        from app.models.research import CodingBatch, CodingUnit
        self.profile.workflow_status='published';self.db.commit()
        batch=CodingBatch(id='later',name='Later',reviewer_a_id='admin',reviewer_b_id='teacher',adjudicator_id='admin',created_by='admin',status='active')
        self.db.add(batch);self.db.flush()
        self.db.add(CodingUnit(id='later-unit',batch_id='later',run_id='run',session_id='session',task_id='task',sequence_no=1,segment='新编码',status='agreed',final_dimension='monitoring'))
        self.db.commit()
        asyncio.run(research._finish_coding_batch_if_ready(batch,AsyncDB(self.db)))
        self.assertEqual(batch.status,'completed')
        self.assertEqual(self.profile.workflow_status,'published')
        self.assertEqual(self.profile.summary,'真实草稿内容')
