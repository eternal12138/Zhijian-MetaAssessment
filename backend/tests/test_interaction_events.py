import unittest

from pydantic import ValidationError

from app.models.session import InteractionEvent
from app.schemas.session import InteractionEventBatchIn, InteractionEventIn


def make_event(**overrides) -> InteractionEventIn:
    values = {
        "client_event_id": "event-1",
        "sequence_no": 1,
        "event_type": "recording_started",
        "occurred_at_ms": 100,
        "client_timestamp_ms": 1_700_000_000_000,
        "payload": {},
    }
    values.update(overrides)
    return InteractionEventIn(**values)


class InteractionEventTest(unittest.TestCase):
    def test_event_type_is_constrained(self):
        with self.assertRaises(ValidationError):
            make_event(event_type="arbitrary_event")

    def test_assessment_tool_usage_is_a_valid_content_free_event(self):
        event = make_event(
            event_type="assessment_tool_used",
            payload={"tool": "calculator", "action": "opened"},
        )
        self.assertEqual(event.event_type, "assessment_tool_used")

    def test_event_payload_is_limited_to_eight_kilobytes(self):
        with self.assertRaises(ValidationError):
            make_event(payload={"content": "测" * 3_000})

    def test_batch_rejects_duplicate_client_event_ids(self):
        with self.assertRaises(ValidationError):
            InteractionEventBatchIn(events=[make_event(), make_event()])

    def test_database_model_has_session_scoped_idempotency_constraint(self):
        constraints = {
            constraint.name
            for constraint in InteractionEvent.__table__.constraints
            if constraint.name
        }
        self.assertIn("uq_interaction_event_session_client_id", constraints)
        self.assertIn(
            "idx_interaction_events_timeline",
            {index.name for index in InteractionEvent.__table__.indexes},
        )


if __name__ == "__main__":
    unittest.main()
