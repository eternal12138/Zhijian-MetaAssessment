import json
import unittest
from unittest.mock import patch
import httpx
from sqlalchemy import create_engine, inspect, text
from app.config import Settings
from app.services.analysis_agent import AnalysisAgent
from app.services.report_analyzer import validate_report_output
from scripts.migrate_phase35 import upgrade

VALID = {"summary":"真实反馈", "level":"学习反馈", "strengths":["检查条件"], "weaknesses":["复盘方法"],
         "suggestions":[{"dimension":d,"title":"练习","description":"依据证据练习","practices":[
             "立即尝试：检查一次", "练习安排：每次任务使用", "效果检查：记录是否完成"]}
                        for d in ("monitoring","controlDebugging","evaluation")]}

class ReportAIContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_snapshot_and_context_reach_model_without_hidden_token_cap(self):
        requests=[]
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200,json={"id":"req-real-format","usage":{"total_tokens":70},
                "choices":[{"finish_reason":"stop","message":{"content":json.dumps(VALID)}}]})
        original=httpx.AsyncClient
        config=Settings(REPORT_USE_LLM=True, LLM_BASE_URL="https://test.example/v1", LLM_API_KEY="test",
                        LLM_MODEL="test-model", LLM_MAX_TOKENS=4096)
        agent=AnalysisAgent(config)
        with patch('app.services.analysis_agent.httpx.AsyncClient',
                   side_effect=lambda **kwargs: original(**kwargs,transport=httpx.MockTransport(handler))):
            value=await agent.generate_metacognitive_profile(overall_score=0, dimension_results=[],
                prompt_template="PROMPT-V2 {overall_score} {dimension_results}",
                report_context={"effective_dialogue_count":13,"is_provisional":True})
        self.assertEqual(validate_report_output(value),VALID)
        self.assertEqual(requests[0]['max_tokens'],4096)
        self.assertIn('PROMPT-V2',requests[0]['messages'][1]['content'])
        self.assertIn('"effective_dialogue_count": 13',requests[0]['messages'][1]['content'])
        self.assertNotIn('{overall_score}',requests[0]['messages'][1]['content'])
        self.assertEqual(agent.last_report_metadata['request_id'],'req-real-format')
        self.assertNotIn('test',agent.last_report_metadata.values())

    async def test_truncated_output_is_rejected_even_if_json_parses(self):
        original=httpx.AsyncClient
        with patch('app.services.analysis_agent.httpx.AsyncClient',side_effect=lambda **kw: original(**kw,
            transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
                "choices":[{"finish_reason":"length","message":{"content":json.dumps(VALID)}}]})))):
            with self.assertRaisesRegex(ValueError,'截断'):
                await AnalysisAgent(Settings(REPORT_USE_LLM=True,LLM_BASE_URL='https://test.example')).generate_metacognitive_profile(
                    overall_score=0,dimension_results=[],prompt_template='test')

    def test_incomplete_duplicate_and_malformed_suggestions_fail(self):
        for suggestions in ([], VALID['suggestions'] + [VALID['suggestions'][0]],
                            [VALID['suggestions'][0]]*2,
                            [{**VALID['suggestions'][0], 'dimension':'invalid'}],
                            [{**item,'practices':[]} for item in VALID['suggestions']]):
            with self.assertRaises(ValueError):
                validate_report_output({**VALID,'suggestions':suggestions})

    def test_recommendation_only_subset_is_valid(self):
        value = {'suggestions': VALID['suggestions'][:1]}
        self.assertEqual(validate_report_output(value), value)

    def test_integrated_strategy_is_valid_but_practice_order_is_strict(self):
        strategy = {**VALID['suggestions'][0], 'dimension': 'integrated'}
        self.assertEqual(validate_report_output({'suggestions': [strategy]}), {'suggestions': [strategy]})
        malformed = {**strategy, 'practices': list(reversed(strategy['practices']))}
        with self.assertRaises(ValueError):
            validate_report_output({'suggestions': [malformed]})

class ReportMigrationTests(unittest.TestCase):
    def test_old_schema_upgrades_twice_without_inventing_provenance(self):
        engine=create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        with engine.begin() as db:
            db.execute(text('CREATE TABLE metacognitive_profiles (id VARCHAR(36) PRIMARY KEY, summary TEXT)'))
            db.execute(text('CREATE TABLE analysis_jobs (id VARCHAR(36) PRIMARY KEY, status VARCHAR(24), error_message TEXT)'))
            db.execute(text("INSERT INTO metacognitive_profiles VALUES ('old','unchanged')"))
            db.execute(text("INSERT INTO analysis_jobs VALUES ('job','running','')"))
        upgrade(engine);upgrade(engine)
        with engine.connect() as db:
            row=db.execute(text("SELECT summary,evidence_snapshot,generation_metadata FROM metacognitive_profiles")).one()
            self.assertEqual(tuple(row),('unchanged',None,None))
            self.assertEqual(db.scalar(text('SELECT status FROM analysis_jobs')),'failed')
            self.assertIn('report_revisions',inspect(db).get_table_names())
