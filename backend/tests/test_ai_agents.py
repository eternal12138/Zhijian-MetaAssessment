import json
import unittest
from types import SimpleNamespace

from app.api.sessions import ChatRequest
from app.services.analysis_agent import (
    AnalysisAgent,
    AnalysisSegment,
)
from app.services.protocol_agent import (
    NEUTRAL_PROMPTS,
    ProtocolAgent,
    ProtocolEvent,
)


class ProtocolAgentTest(unittest.TestCase):
    def setUp(self):
        self.agent = ProtocolAgent()

    def test_participant_turn_never_triggers_an_automatic_reply(self):
        decision = self.agent.handle(ProtocolEvent.PARTICIPANT_TURN)

        self.assertFalse(decision.should_respond)
        self.assertIsNone(decision.message)

    def test_silence_reminders_are_limited_to_the_four_protocol_prompts(self):
        generated = [
            self.agent.handle(ProtocolEvent.SILENCE_REMINDER, reminder_index=index)
            for index in range(8)
        ]

        self.assertEqual(
            [item.message for item in generated],
            list(NEUTRAL_PROMPTS) * 2,
        )
        self.assertTrue(all(item.should_respond for item in generated))
        self.assertTrue(all(
            self.agent.is_allowed_formal_task_message(item.message or "")
            for item in generated
        ))
        self.assertFalse(
            self.agent.is_allowed_formal_task_message("你为什么选择这种算法？")
        )

    def test_silence_event_does_not_require_a_fake_participant_message(self):
        request = ChatRequest(
            session_id="session-1",
            event=ProtocolEvent.SILENCE_REMINDER,
            reminder_index=2,
        )

        self.assertEqual(request.message, "")


class AnalysisAgentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.segments = [
            AnalysisSegment(segment_id="segment-1", text="我发现结果矛盾了。"),
            AnalysisSegment(segment_id="segment-2", text="我准备换一种方法。"),
        ]

    def test_parse_codes_accepts_only_valid_structured_evidence(self):
        content = json.dumps([
            {
                "segment_id": "segment-1",
                "dimension": "monitoring",
                "score": 6,
                "reason": "发现结果矛盾",
                "confidence": 0.91,
            },
            {
                "segment_id": "unknown",
                "dimension": "evaluation",
                "score": 5,
                "reason": "不存在的片段",
                "confidence": 0.8,
            },
            {
                "segment_id": "segment-2",
                "dimension": "controlDebugging",
                "score": 9,
                "reason": "非法分数",
                "confidence": 0.8,
            },
        ], ensure_ascii=False)

        results = AnalysisAgent.parse_codes(content, self.segments)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].segment_id, "segment-1")
        self.assertEqual(results[0].dimension, "monitoring")

    async def test_disabled_llm_returns_without_calling_a_provider(self):
        settings = SimpleNamespace(REPORT_USE_LLM=False)
        agent = AnalysisAgent(settings=settings)

        results = await agent.code_segments(self.segments, "片段：{segments}")

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
