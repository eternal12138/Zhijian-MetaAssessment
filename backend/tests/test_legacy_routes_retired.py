import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.reports import list_pending_codings, review_coding
from app.api.research import (
    adjudicate_coding,
    list_disagreements,
    list_review_assignments,
    submit_annotation,
)
from app.api.sessions import chat_sse, get_session_history, send_message
from app.api.tasks import create_task, publish_task
from app.main import app


class LegacyRoutesRetiredTest(unittest.IsolatedAsyncioTestCase):
    async def _assert_gone(self, call):
        with self.assertRaises(HTTPException) as context:
            await call()
        self.assertEqual(context.exception.status_code, 410)

    async def test_dialogue_routes_are_tombstones(self):
        user = SimpleNamespace(id="student-1", role="student")
        await self._assert_gone(lambda: chat_sse(user=user))
        await self._assert_gone(
            lambda: get_session_history("session-1", user=user)
        )
        await self._assert_gone(lambda: send_message("session-1", user=user))

    async def test_single_review_routes_are_tombstones(self):
        user = SimpleNamespace(id="reviewer-1", role="teacher")
        await self._assert_gone(lambda: list_pending_codings(user=user))
        await self._assert_gone(lambda: review_coding("coding-1", user=user))
        await self._assert_gone(lambda: list_review_assignments(user=user))
        await self._assert_gone(lambda: submit_annotation("coding-1", user=user))
        await self._assert_gone(lambda: list_disagreements(user=user))
        await self._assert_gone(lambda: adjudicate_coding("coding-1", user=user))

    async def test_dynamic_task_mutations_are_tombstones(self):
        user = SimpleNamespace(id="teacher-1", role="teacher")
        await self._assert_gone(lambda: create_task(user=user))
        await self._assert_gone(lambda: publish_task("task-1", user=user))

    def test_retired_websocket_route_is_not_registered(self):
        paths = {route.path for route in app.routes}
        self.assertNotIn("/api/sessions/{session_id}/ws", paths)


if __name__ == "__main__":
    unittest.main()
