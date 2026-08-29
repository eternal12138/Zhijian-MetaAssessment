"""Real SQL integration (isolated SQLite), source policy and role regression tests."""
import asyncio
import io
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, User, AssessmentTask, AssessmentRun, AssessmentSession, TranscriptVersion
from app.models import ExtractionJob, ExtractionCandidate, CodingBatch, CodingUnit, MeasurementCorrection
from app.models.research import ModelTrainingJob
from app.api import ai_evaluation
from app.schemas.ai_evaluation import AiEvaluationRunIn
from app.api.reports import router, upload_measurement_corrections, list_metacognition_measurements, get_metacognition_measurement
from app.api.research import get_macro_analytics
from app.core.security import get_current_user
from app.database import get_db
from app.services.metacognition_distribution import aggregate_distribution
from app.services.metacognition_evidence import resolve_session_evidence, load_run_evidence
from app.services.metacognition_measurement import calculate_and_persist_measurement
from app.services.measurement_corrections import parse_correction_csv


class AsyncAdapter:
    """Execute production SQL statements on an isolated synchronous test database."""
    def __init__(self, db): self.db = db
    async def execute(self, stmt): return self.db.execute(stmt)
    async def scalar(self, stmt): return self.db.scalar(stmt)
    async def scalars(self, stmt): return self.db.scalars(stmt)
    async def get(self, model, key): return self.db.get(model, key)
    async def flush(self): self.db.flush()
    async def commit(self): self.db.commit()
    async def rollback(self): self.db.rollback()
    def add(self, row): self.db.add(row)


class EvidencePolicyTests(unittest.TestCase):
    def candidate(self, label="monitoring", status="accepted", classified="classified"):
        return NS(id="candidate", predicted_dimension=label, review_status=status, classification_status=classified)

    def profile(self, row):
        return aggregate_distribution(["s"], {"s": row}, scope="run", label="test")

    def test_reviewed_denominator_includes_non_metacognition(self):
        row = resolve_session_evidence(job=NS(id="j", status="reviewed"), candidates=[self.candidate(), self.candidate("non_metacognitive")])
        result = self.profile(row)
        self.assertEqual(result["effective_dialogue_count"], 2)
        self.assertEqual(result["percentages"]["monitoring"], 50)
        self.assertEqual(result["fallback_dialogue_count"], 0)

    def test_unreviewed_fallback_does_not_divide_pending_labels_by_accepted_subset(self):
        row = resolve_session_evidence(job=NS(id="j", status="reviewing"), candidates=[
            self.candidate(), self.candidate("regulation", "pending"), self.candidate("evaluation", "rejected"),
            self.candidate("evaluation", "accepted", "failed"),
        ])
        result = self.profile(row)
        self.assertEqual(result["effective_dialogue_count"], 2)
        self.assertEqual(result["fallback_dialogue_count"], 2)
        self.assertEqual(result["percentages"]["monitoring"], 50)

    def test_invalidated_classification_does_not_become_fake_zero_score(self):
        row = resolve_session_evidence(job=NS(id="j", status="reviewed"), candidates=[self.candidate(None, classified="pending_classification")])
        result = self.profile(row)
        self.assertEqual(result["effective_dialogue_count"], 1)
        self.assertEqual(result["unclassified_count"], 1)
        self.assertFalse(result["score_available"])
        self.assertEqual(result["scores"], [])

    def test_expert_overrides_only_matching_candidate(self):
        unit = NS(id="unit", candidate_id="candidate", final_dimension="evaluation", batch_id="b")
        row = resolve_session_evidence(job=NS(id="j", status="reviewed"), candidates=[self.candidate()], units=[unit])
        self.assertEqual(row["counts"]["evaluation"], 1)
        self.assertEqual(row["counts"]["monitoring"], 0)
        self.assertEqual(row["effective_dialogue_count"], 1)

    def test_admin_upload_is_authoritative_and_zero_scores_can_be_real(self):
        correction = NS(id="c", dimension_counts={"monitoring": 0, "controlDebugging": 0, "evaluation": 0}, effective_dialogue_count=4)
        result = self.profile(resolve_session_evidence(correction=correction, candidates=[self.candidate()]))
        self.assertTrue(result["score_available"])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["effective_dialogue_count"], 4)
        self.assertEqual(len(result["scores"]), 3)

    def test_cohort_sums_denominators_not_percentages(self):
        a = resolve_session_evidence(correction=NS(id="a", dimension_counts={"monitoring": 1}, effective_dialogue_count=10))
        b = resolve_session_evidence(candidates=[self.candidate("regulation")])
        result = aggregate_distribution(["a", "b", "a"], {"a": a, "b": b}, scope="class", label="class")
        self.assertEqual(result["effective_dialogue_count"], 11)
        self.assertEqual(result["percentages"]["monitoring"], 9.1)
        self.assertEqual(result["fallback_dialogue_count"], 1)

    def test_parser_accepts_chinese_bom_and_multiline_text(self):
        rows = parse_correction_csv('\ufeff会话ID,校对文本,最终标签\r\ns,"我再想想,\n重新算",2\r\ns,读题,0'.encode())
        self.assertEqual(len(rows["s"]), 2)
        self.assertEqual(rows["s"][0]["label"], "regulation")

    def test_parser_rejects_bad_headers_labels_blank_text_and_empty_file(self):
        for content in ["text,label\ns,1", "session_id,text,label\ns,text,planning", "session_id,text,label\ns,,1", "session_id,text,label", "session_id,text,label\ns,x,1,extra"]:
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_correction_csv(content.encode())


class EvidenceDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sync = Session(self.engine, expire_on_commit=False)
        self.db = AsyncAdapter(self.sync)
        self.admin = User(id="admin", username="admin", name="admin", password_hash="x", role="admin")
        self.student = User(id="student", username="student", name="student", password_hash="x", role="student", class_group="class")
        self.teacher = User(id="teacher", username="teacher", name="teacher", password_hash="x", role="teacher", managed_classes="class")
        self.sync.add_all([self.admin, self.student, self.teacher])
        self.run = AssessmentRun(id="run", user_id="student", status="completed", completed_at=datetime(2026, 8, 1))
        self.sync.add(self.run)
        for i in [1, 2]:
            self.sync.add(AssessmentTask(id=f"t{i}", title=f"task{i}", description="d", scenario="s", publisher_id="admin"))
            self.sync.add(AssessmentSession(id=f"s{i}", user_id="student", task_id=f"t{i}", run_id="run", sequence_no=i))
            self.sync.add(TranscriptVersion(id=f"v{i}", session_id=f"s{i}", version_no=1, source="server_asr", is_authoritative=True, full_text="原文不变"))
        self.sync.flush()

    def tearDown(self):
        self.sync.close()
        self.engine.dispose()

    def add_job(self, session="s1", status="reviewed", generation=1, labels=("monitoring", "non_metacognitive")):
        job = ExtractionJob(session_id=session, transcript_version_id="v" + session[-1], status=status, generation_no=generation,
                            model="model", extractor_version="1", prompt_version="1", prompt_content="p", raw_asr_text="原文")
        self.sync.add(job)
        self.sync.flush()
        for index, label in enumerate(labels):
            self.sync.add(ExtractionCandidate(extraction_job_id=job.id, session_id=session, run_id="run", user_id="student", task_id="t"+session[-1],
                sequence_no=index, raw_asr_text="原文", original_text="原文", clean_text="清洗", review_status="accepted" if status == "reviewed" else "pending",
                predicted_dimension=label, classification_status="classified"))
        self.sync.flush()
        return job

    def upload(self, content, user=None):
        return asyncio.run(upload_measurement_corrections(file=UploadFile(filename="校对.csv", file=io.BytesIO(content.encode())), confirmed=True, user=user or self.admin, db=self.db))

    def test_all_three_roles_share_counts_and_denominator(self):
        self.add_job()
        self.add_job("s2", status="reviewing", labels=("regulation",))
        measurement = asyncio.run(calculate_and_persist_measurement(self.run, self.db))
        self.assertEqual(measurement.effective_dialogue_count, 3)
        self.assertAlmostEqual(measurement.monitoring_score, 1/3)
        for role in [self.student, self.teacher, self.admin]:
            result = asyncio.run(get_macro_analytics(class_group="all", participant_id="student" if role.role != "student" else None, user=role, db=self.db))
            profile = result["radar_profiles"]["participant"]
            self.assertEqual(profile["effective_dialogue_count"], 3)
            self.assertEqual(profile["percentages"]["monitoring"], 33.3)
            self.assertEqual(profile["fallback_dialogue_count"], 1)

    def test_task_counts_sum_to_run_and_refresh_recalculates(self):
        self.add_job()
        self.add_job("s2", labels=("evaluation",))
        a = asyncio.run(calculate_and_persist_measurement(self.run, self.db, task_id="t1"))
        b = asyncio.run(calculate_and_persist_measurement(self.run, self.db, task_id="t2"))
        run = asyncio.run(calculate_and_persist_measurement(self.run, self.db))
        self.assertEqual(a.effective_dialogue_count + b.effective_dialogue_count, run.effective_dialogue_count)
        self.upload("session_id,text,label\ns1,校对一,2\ns1,校对二,2\ns1,读题,0")
        a = asyncio.run(calculate_and_persist_measurement(self.run, self.db, task_id="t1"))
        self.assertEqual(a.monitoring_count, 0)
        self.assertEqual(a.control_debugging_count, 2)
        self.assertEqual(a.effective_dialogue_count, 3)

    def test_student_response_exposes_denominator_and_keeps_ownership_guard(self):
        self.add_job()
        self.add_job("s2", status="reviewing", labels=("evaluation",))
        page = asyncio.run(list_metacognition_measurements(page=1, page_size=20, user=self.student, db=self.db))
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].denominator_breakdown, {"human_review": 2, "label_total_fallback": 1})
        item = asyncio.run(get_metacognition_measurement("run", task_id="t1", user=self.student, db=self.db))
        self.assertEqual(item.dimension_scores["monitoring"], 0.5)
        self.assertEqual(item.fallback_dialogue_count, 0)
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(get_metacognition_measurement("run", task_id=None, user=NS(id="someone-else"), db=self.db))
        self.assertEqual(raised.exception.status_code, 403)

    def test_latest_current_transcript_job_not_older_reviewed_version(self):
        self.add_job()
        self.add_job(status="reviewing", generation=2, labels=("evaluation",))
        result = asyncio.run(load_run_evidence(["run"], self.db))["run"]
        self.assertEqual(result["counts"]["monitoring"], 0)
        self.assertEqual(result["counts"]["evaluation"], 1)
        self.assertEqual(result["fallback_dialogue_count"], 1)
        self.sync.get(TranscriptVersion, "v1").is_authoritative = False
        self.sync.flush()
        result = asyncio.run(load_run_evidence(["run"], self.db))["run"]
        self.assertEqual(result["total"], 0)

    def test_report_snapshot_uses_same_denominator_and_detects_text_only_edit(self):
        from app.services.report_evidence import build_report_snapshot, snapshot_measurement
        self.add_job()
        self.add_job('s2', status='reviewing', labels=('regulation',))
        snapshot=asyncio.run(build_report_snapshot('run', self.db))
        measurement=asyncio.run(calculate_and_persist_measurement(self.run,self.db))
        self.assertEqual(snapshot['effective_dialogue_count'],measurement.effective_dialogue_count)
        self.assertEqual(snapshot['counts']['monitoring'],measurement.monitoring_count)
        self.assertEqual(snapshot_measurement(snapshot)['dimension_scores']['monitoring'],measurement.monitoring_score)
        self.assertTrue(snapshot['is_provisional'])
        self.assertEqual(snapshot['metacognition_pattern']['status'], 'insufficient')
        self.assertEqual(snapshot['metacognition_pattern']['group_norm']['status'], 'not_connected')
        candidate=self.sync.scalar(select(ExtractionCandidate))
        candidate.clean_text='人工更正后的文字';self.sync.flush()
        changed=asyncio.run(build_report_snapshot('run',self.db))
        self.assertNotEqual(changed['data_version'],snapshot['data_version'])
        self.assertEqual(changed['counts'],snapshot['counts'])

    def ai_overview(self):
        model = self.sync.get(ModelTrainingJob, "test-model")
        if model is None:
            model = ModelTrainingJob(id="test-model", version="test-model", requested_by="admin", status="completed", is_active=True,
                config_snapshot={"experiment_type":"tfidf_linear_svc", "dataset_source":"uploaded"})
            self.sync.add(model); self.sync.flush()
        with patch.object(ai_evaluation, "_model_cards", new=AsyncMock(return_value=([model], None))):
            return asyncio.run(ai_evaluation.overview(db=self.db, user=self.admin))

    def test_pending_and_failed_extractions_do_not_hide_completed_classification(self):
        old = self.add_job(labels=("monitoring",))
        old.created_at = datetime(2026,8,1)
        candidate = self.sync.scalar(select(ExtractionCandidate).where(ExtractionCandidate.extraction_job_id == old.id))
        self.ai_overview()
        candidate.classifier_job_id = "test-model"
        newest = self.add_job(status="queued", generation=2, labels=())
        for status in ["queued", "running", "retry_wait", "failed"]:
            newest.status=status; self.sync.flush()
            with self.subTest(status=status):
                self.assertEqual(self.ai_overview().scope_items[0].classified_count, 1)
                m = asyncio.run(calculate_and_persist_measurement(self.run, self.db))
                self.assertTrue(m.score_available)
                self.assertEqual(m.monitoring_count, 1)
                self.assertEqual(m.retained_previous_count, 1)
                self.assertEqual(m.session_states[0]["extraction_generation"], 1)
                for role in [self.student, self.teacher, self.admin]:
                    result=asyncio.run(get_macro_analytics(class_group="all", participant_id=None if role.role=="student" else "student", user=role, db=self.db))
                    p=result["radar_profiles"]["participant"]
                    self.assertEqual(p["counts"]["monitoring"], 1)
                    self.assertEqual(p["retained_previous_count"], 1)
                    self.assertNotIn("session_states", p)

    def test_real_enqueue_superseded_history_retains_success_and_reviewed_denominator(self):
        old = self.add_job(labels=("monitoring", "non_metacognitive"))
        old.status = "superseded"
        old.completed_at = datetime(2026,8,1)
        self.add_job(status="failed", generation=2, labels=())
        m=asyncio.run(calculate_and_persist_measurement(self.run,self.db))
        self.assertTrue(m.score_available)
        self.assertEqual(m.effective_dialogue_count,2)
        self.assertEqual(m.monitoring_score,0.5)
        self.assertEqual(m.denominator_breakdown,{"human_review":2})
        self.assertEqual(self.ai_overview().scope_items[0].available_classified_count,1)
        # A newer superseded unfinished attempt must not displace valid history.
        unfinished=self.add_job(status="superseded",generation=3,labels=())
        unfinished.completed_at=None
        self.add_job(status="queued",generation=4,labels=())
        m=asyncio.run(calculate_and_persist_measurement(self.run,self.db))
        self.assertEqual(m.session_states[0]["extraction_generation"],1)
        # Even an empty completed version replaces old labels, not vice versa.
        unfinished.completed_at=datetime(2026,8,3)
        self.sync.flush()
        m=asyncio.run(calculate_and_persist_measurement(self.run,self.db))
        self.assertFalse(m.score_available)
        self.assertEqual(m.session_states[0]["extraction_generation"],3)

    def test_completed_new_extraction_never_borrows_old_classification(self):
        self.add_job(labels=("monitoring",))
        new = self.add_job(status="completed", generation=2, labels=("evaluation",))
        c = self.sync.scalar(select(ExtractionCandidate).where(ExtractionCandidate.extraction_job_id==new.id))
        c.classification_status="pending_classification"; c.predicted_dimension=None
        self.sync.flush()
        m=asyncio.run(calculate_and_persist_measurement(self.run, self.db))
        self.assertFalse(m.score_available)
        self.assertEqual(m.session_states[0]["status"], "classification_pending")
        c.classification_error="provider unavailable";self.sync.flush()
        failed=asyncio.run(calculate_and_persist_measurement(self.run,self.db))
        self.assertEqual(failed.session_states[0]["status"],"classification_failed")
        c.classification_status="classified"; c.predicted_dimension="evaluation"; self.sync.flush()
        m=asyncio.run(calculate_and_persist_measurement(self.run, self.db))
        self.assertTrue(m.score_available)
        self.assertEqual(m.monitoring_count,0); self.assertEqual(m.evaluation_count,1)

    def test_authoritative_transcript_change_excludes_old_ai_results(self):
        self.add_job(labels=("monitoring",))
        self.sync.get(TranscriptVersion,"v1").is_authoritative=False
        self.sync.add(TranscriptVersion(id="replacement",session_id="s1",version_no=2,source="human_corrected",is_authoritative=True,full_text="new"))
        self.sync.flush()
        self.assertEqual(self.ai_overview().scope_items, [])
        m=asyncio.run(calculate_and_persist_measurement(self.run,self.db))
        self.assertFalse(m.score_available)
        self.assertEqual(m.session_states[0]["status"], "awaiting_extraction")

    def test_ai_counts_require_valid_success_and_keep_old_model_availability(self):
        job=self.add_job(status="completed",labels=("regulation",))
        self.ai_overview()
        c=self.sync.scalar(select(ExtractionCandidate).where(ExtractionCandidate.extraction_job_id==job.id))
        c.classifier_job_id="test-model"; self.sync.flush()
        self.assertEqual(self.ai_overview().scope_items[0].classified_count,1)
        self.assertEqual(self.ai_overview().scope_items[0].dimension_counts["regulation"],1)
        for flag,label in [("pending_classification","monitoring"),("failed","monitoring"),("classified",None),("classified","planning")]:
            c.classification_status=flag;c.predicted_dimension=label;self.sync.flush()
            self.assertEqual(self.ai_overview().scope_items[0].classified_count,0)
            self.assertFalse(asyncio.run(calculate_and_persist_measurement(self.run,self.db)).score_available)
        c.classification_status="classified";c.predicted_dimension="monitoring";c.classifier_job_id=None;self.sync.flush()
        row=self.ai_overview().scope_items[0]
        self.assertEqual(row.classified_count,0);self.assertEqual(row.available_classified_count,1)
        self.assertTrue(asyncio.run(calculate_and_persist_measurement(self.run,self.db)).score_available)

    def test_new_empty_or_all_rejected_extraction_has_explicit_reason(self):
        self.add_job(labels=("monitoring",))
        new=self.add_job(status="completed",generation=2,labels=())
        m=asyncio.run(calculate_and_persist_measurement(self.run,self.db))
        self.assertFalse(m.score_available);self.assertEqual(m.session_states[0]["status"],"no_candidates")
        self.sync.add(ExtractionCandidate(extraction_job_id=new.id,session_id="s1",run_id="run",user_id="student",task_id="t1",sequence_no=0,raw_asr_text="x",original_text="x",clean_text="x",review_status="rejected",classification_status="classified",predicted_dimension="monitoring"))
        self.sync.flush()
        m=asyncio.run(calculate_and_persist_measurement(self.run,self.db))
        self.assertFalse(m.score_available);self.assertEqual(m.session_states[0]["status"],"all_rejected")

    def test_classifier_targets_current_successful_version_and_rejects_invalid_output(self):
        old=self.add_job(labels=("monitoring",));old.status="superseded";old.completed_at=datetime(2026,8,1)
        new=self.add_job(status="queued",generation=2,labels=())
        self.ai_overview();self.sync.commit()
        seen=[]
        async def predict(db,candidates):
            seen.extend(c.extraction_job_id for c in candidates)
            for c in candidates:
                c.classification_status="classified";c.classifier_job_id="test-model";c.predicted_dimension="evaluation"
        with patch.object(ai_evaluation,"classify_candidates",new=predict):
            result=asyncio.run(ai_evaluation.classify_scope(AiEvaluationRunIn(scope="session",ids=["s1"]),db=self.db,user=self.admin))
        self.assertEqual(seen,[old.id]);self.assertEqual(result.remaining,0)
        self.assertEqual(asyncio.run(calculate_and_persist_measurement(self.run,self.db)).evaluation_count,1)
        c=self.sync.scalar(select(ExtractionCandidate).where(ExtractionCandidate.extraction_job_id==old.id))
        c.predicted_dimension=None;self.sync.commit()
        async def invalid(db,candidates):
            for c in candidates:c.predicted_dimension="non_meta";c.classification_status="classified"
        with patch.object(ai_evaluation,"classify_candidates",new=invalid), self.assertRaises(HTTPException) as raised:
            asyncio.run(ai_evaluation.classify_scope(AiEvaluationRunIn(scope="session",ids=["s1"]),db=self.db,user=self.admin))
        self.assertEqual(raised.exception.status_code,409)
        self.assertIn("本批次未保存",raised.exception.detail)
        self.assertIsNone(self.sync.get(ExtractionCandidate,c.id).predicted_dimension)

    def test_old_candidate_expert_unit_does_not_leak_into_new_extraction(self):
        old=self.add_job(labels=("monitoring",))
        c=self.sync.scalar(select(ExtractionCandidate).where(ExtractionCandidate.extraction_job_id==old.id))
        batch=CodingBatch(id="old-batch",name="old",reviewer_a_id="admin",reviewer_b_id="teacher",adjudicator_id="admin",created_by="admin",status="completed")
        self.sync.add(batch);self.sync.flush()
        self.sync.add(CodingUnit(batch_id=batch.id,candidate_id=c.id,session_id="s1",run_id="run",task_id="t1",sequence_no=0,segment="x",status="agreed",final_dimension="monitoring"))
        self.add_job(status="completed",generation=2,labels=())
        m=asyncio.run(calculate_and_persist_measurement(self.run,self.db))
        self.assertFalse(m.score_available);self.assertEqual(m.monitoring_count,0)

    def test_all_completed_rounds_paginate_without_scores_or_published_reports(self):
        for i in range(205):
            self.sync.add(AssessmentRun(id=f"page-{i:03}", user_id="student", status="completed",
                completed_at=datetime(2026, 8, 2) + timedelta(minutes=i)))
        self.sync.add(AssessmentRun(id="unfinished", user_id="student", status="in_progress"))
        self.sync.add(AssessmentRun(id="other-user", user_id="admin", status="completed", completed_at=datetime(2026, 9, 1)))
        self.sync.flush()
        pages = [asyncio.run(list_metacognition_measurements(page=p, page_size=100, user=self.student, db=self.db)) for p in [1,2,3]]
        self.assertEqual([len(p.items) for p in pages], [100,100,6])
        self.assertTrue(all(p.total == 206 for p in pages))
        items = [item for p in pages for item in p.items]
        self.assertEqual(len({item.run_id for item in items}), 206)
        self.assertEqual(items[0].run_id, "page-204")
        self.assertEqual(items[-1].run_id, "run")
        self.assertEqual([item.completed_at for item in items], sorted([item.completed_at for item in items], reverse=True))
        self.assertTrue(all(not item.score_available for item in items))

    def test_task_and_whole_round_results_stay_isolated_across_rounds(self):
        self.add_job(labels=("monitoring", "non_metacognitive"))
        self.add_job("s2", labels=("evaluation",))
        second = AssessmentRun(id="second", user_id="student", status="completed", completed_at=datetime(2026,8,2))
        self.sync.add(second)
        self.sync.add(AssessmentSession(id="second-session", user_id="student", task_id="t1", run_id="second", sequence_no=1))
        self.sync.flush()
        self.upload("session_id,text,label\nsecond-session,校对,2\nsecond-session,读题,0")
        def read(run_id, task_id=None):
            return asyncio.run(get_metacognition_measurement(run_id, task_id=task_id, user=self.student, db=self.db))
        a, b, whole, other = read("run","t1"), read("run","t2"), read("run"), read("second","t1")
        self.assertEqual(a.dimension_scores["monitoring"], 0.5)
        self.assertEqual(b.dimension_scores["evaluation"], 1)
        self.assertAlmostEqual(whole.dimension_scores["monitoring"], 1/3)
        self.assertEqual(other.dimension_scores["control_debugging"], 0.5)
        self.assertEqual(read("run","t1").dimension_scores, a.dimension_scores)
        self.assertEqual(read("second").dimension_scores, other.dimension_scores)
        with self.assertRaises(HTTPException) as raised:
            read("second","t2")
        self.assertEqual(raised.exception.status_code, 404)

    def test_separate_task_expert_batches_are_both_counted(self):
        for i, label in [(1,"monitoring"), (2,"evaluation")]:
            batch = CodingBatch(id=f"b{i}", name="batch", reviewer_a_id="admin", reviewer_b_id="teacher", adjudicator_id="admin", created_by="admin", status="completed", completed_at=datetime(2026,8,i))
            self.sync.add(batch)
            for j in range(i+1):
                self.sync.add(CodingUnit(batch_id=batch.id, session_id=f"s{i}", run_id="run", task_id=f"t{i}", sequence_no=j, segment="text", status="agreed", final_dimension=label))
        self.sync.flush()
        result = asyncio.run(load_run_evidence(["run"], self.db))["run"]
        self.assertEqual(result["effective_dialogue_count"], 5)
        self.assertEqual(result["counts"]["monitoring"], 2)
        self.assertEqual(result["counts"]["evaluation"], 3)

    def test_upload_retains_versions_and_original_text(self):
        self.upload("session_id,text,label\ns1,校对,1")
        self.upload("session_id,text,label\ns1,再次校对,2\ns1,读题,0")
        rows = list(self.sync.scalars(select(MeasurementCorrection).order_by(MeasurementCorrection.version_no)))
        self.assertEqual([r.version_no for r in rows], [1,2])
        self.assertEqual(rows[0].dialogues[0]["label"], "monitoring")
        self.assertEqual(self.sync.get(TranscriptVersion,"v1").full_text, "原文不变")
        result = asyncio.run(load_run_evidence(["run"], self.db))["run"]
        self.assertEqual(result["counts"]["controlDebugging"], 1)
        self.assertEqual(result["effective_dialogue_count"], 2)
        self.assertEqual(result["denominator_breakdown"], {"admin_upload": 2})

    def test_unknown_or_incomplete_session_upload_is_atomic(self):
        with self.assertRaises(HTTPException):
            self.upload("session_id,text,label\ns1,校对,1\nmissing,校对,2")
        self.assertEqual(self.sync.scalar(select(func.count(MeasurementCorrection.id))), 0)
        self.run.status = "in_progress"
        self.sync.flush()
        with self.assertRaises(HTTPException): self.upload("session_id,text,label\ns1,校对,1")

    def test_upload_routes_reject_student_and_teacher(self):
        app = FastAPI()
        app.include_router(router)
        async def db_override(): yield self.db
        app.dependency_overrides[get_db] = db_override
        with TestClient(app) as client:
            for role in [self.student, self.teacher]:
                app.dependency_overrides[get_current_user] = lambda: role
                self.assertEqual(client.get("/reports/measurement-corrections/template").status_code, 403)
                self.assertEqual(client.post("/reports/measurement-corrections", data={"confirmed":"true"}, files={"file":("review.csv", b"session_id,text,label\ns1,x,1")}).status_code, 403)
            app.dependency_overrides[get_current_user] = lambda: self.admin
            self.assertEqual(client.get("/reports/measurement-corrections/template").status_code, 200)


if __name__ == "__main__": unittest.main()
