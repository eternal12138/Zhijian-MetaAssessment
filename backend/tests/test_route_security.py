import unittest

from fastapi.routing import APIRoute

from app.core.security import get_current_user
from app.main import app


def dependency_calls(route: APIRoute) -> set[object]:
    calls: set[object] = set()

    def walk(dependant) -> None:
        if dependant.call is not None:
            calls.add(dependant.call)
        for child in dependant.dependencies:
            walk(child)

    walk(route.dependant)
    return calls


class RouteSecurityTest(unittest.TestCase):
    def test_sensitive_http_routes_require_current_user(self):
        protected = {
            ("/api/tasks", "GET"),
            ("/api/users/{user_id}", "GET"),
            ("/api/sessions/chat", "POST"),
            ("/api/sessions/{session_id}/history", "GET"),
            ("/api/sessions/{session_id}/events", "POST"),
            ("/api/sessions/{session_id}/events", "GET"),
            ("/api/sessions/asr/review-queue", "GET"),
            ("/api/research/extraction/queue", "GET"),
            ("/api/research/extraction/sessions/batch-rerun", "POST"),
            ("/api/research/extraction/jobs/{job_id}/classify", "POST"),
            ("/api/sessions/{session_id}/asr", "GET"),
            ("/api/sessions/{session_id}/asr/retry", "POST"),
            ("/api/sessions/{session_id}/transcript-versions", "GET"),
            (
                "/api/sessions/{session_id}/transcript-versions/{version_id}/approve",
                "POST",
            ),
            (
                "/api/sessions/{session_id}/transcript-versions/corrections",
                "POST",
            ),
            ("/api/assessment/protocol", "GET"),
            ("/api/assessment/task-order/assignments", "GET"),
            ("/api/assessment/task-order/assignments/{user_id}", "PUT"),
            ("/api/assessment/task-order/assignments/balance", "POST"),
            ("/api/assessment/runs", "POST"),
            ("/api/assessment/runs/current", "GET"),
            ("/api/assessment/runs/{run_id}/stage", "PATCH"),
            ("/api/assessment/runs/{run_id}/questionnaire", "POST"),
            ("/api/assessment/runs/{run_id}/complete", "POST"),
            ("/api/reports/runs/{run_id}/generate", "POST"),
            ("/api/reports/runs/{run_id}", "GET"),
            ("/api/reports/review/pending", "GET"),
            ("/api/reports/codings/{coding_id}", "PATCH"),
            ("/api/research/analysis/runs/{run_id}", "POST"),
            ("/api/research/review/assignments", "GET"),
            ("/api/research/review/reviewers", "GET"),
            ("/api/research/review/batches", "GET"),
            ("/api/research/review/batches", "POST"),
            ("/api/research/review/batches/scope-options", "GET"),
            ("/api/research/review/batches/preview", "POST"),
            (
                "/api/research/review/batches/{batch_id}/assignments",
                "PUT",
            ),
            ("/api/research/review/unit-assignments", "GET"),
            (
                "/api/research/review/units/{unit_id}/annotations",
                "POST",
            ),
            (
                "/api/research/review/units/{unit_id}/expert-annotation",
                "PUT",
            ),
            ("/api/research/review/unit-disagreements", "GET"),
            (
                "/api/research/review/units/{unit_id}/adjudicate",
                "POST",
            ),
            ("/api/research/dashboard", "GET"),
            ("/api/research/analytics", "GET"),
            ("/api/research/review/training-dataset/stats", "GET"),
            ("/api/research/review/training-dataset/export", "GET"),
            ("/api/research/exports", "POST"),
            ("/api/research/exports/audio-transcripts", "POST"),
            ("/api/research/exports/{job_id}", "GET"),
            ("/api/research/exports/{job_id}/download", "GET"),
            ("/api/notifications", "GET"),
            ("/api/notifications/unread-count", "GET"),
            ("/api/notifications/read-all", "POST"),
            ("/api/notifications/{notification_id}/read", "PATCH"),
            ("/api/auth/skip-password-change", "POST"),
            ("/api/admin/model-services/config", "GET"),
            ("/api/admin/model-services/config", "PUT"),
            ("/api/admin/model-services/diagnostics", "POST"),
            ("/api/research/model-training/jobs", "GET"),
            ("/api/research/model-training/jobs", "POST"),
            ("/api/research/model-training/jobs/{job_id}", "GET"),
            ("/api/research/model-training/jobs/{job_id}/activate", "POST"),
            ("/api/research/model-training/jobs/{job_id}/cancel", "POST"),
            ("/api/research/model-training/jobs/{job_id}/retry", "POST"),
            ("/api/research/model-training/audit", "GET"),
            ("/api/admin/protocol-config", "GET"),
            ("/api/admin/protocol-config", "PUT"),
            ("/api/admin/users/classes", "GET"),
            ("/api/admin/users/{user_id}/class-group", "PATCH"),
            ("/api/admin/narration-assets", "GET"),
            ("/api/admin/narration-assets/{slot_key}/upload", "POST"),
            ("/api/admin/narration-assets/{asset_id}", "DELETE"),
            ("/api/narrations/{asset_id}/audio", "GET"),
        }
        routes = {
            (route.path, method): route
            for route in app.routes
            if isinstance(route, APIRoute)
            for method in route.methods
        }

        for route_key in protected:
            with self.subTest(route=route_key):
                route = routes[route_key]
                self.assertIn(get_current_user, dependency_calls(route))

    def test_report_generation_routes_use_role_guards(self):
        protected = {
            ("/api/reports/runs/{run_id}/generate", "POST"),
            ("/api/research/analysis/runs/{run_id}", "POST"),
            ("/api/research/analysis/jobs/{job_id}", "GET"),
        }
        routes = {
            (route.path, method): route
            for route in app.routes
            if isinstance(route, APIRoute)
            for method in route.methods
        }

        for route_key in protected:
            with self.subTest(route=route_key):
                direct_calls = {
                    dependency.call for dependency in routes[route_key].dependant.dependencies
                }
                self.assertNotIn(get_current_user, direct_calls)
                self.assertTrue(
                    any(
                        getattr(call, "__name__", "") == "role_checker"
                        for call in direct_calls
                    )
                )

    def test_high_volume_queues_expose_server_pagination(self):
        paginated = {
            ("/api/admin/users", "GET"),
            ("/api/sessions/asr/review-queue", "GET"),
            ("/api/research/quality/runs", "GET"),
            ("/api/assessment/task-order/assignments", "GET"),
            ("/api/reports/review/pending", "GET"),
        }
        routes = {
            (route.path, method): route
            for route in app.routes
            if isinstance(route, APIRoute)
            for method in route.methods
        }
        for route_key in paginated:
            with self.subTest(route=route_key):
                names = {field.name for field in routes[route_key].dependant.query_params}
                self.assertIn("page", names)
                self.assertIn("page_size", names)


if __name__ == "__main__":
    unittest.main()
