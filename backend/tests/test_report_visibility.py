import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.reports import _ensure_report_visible_to_user


class ReportVisibilityTest(unittest.TestCase):
    def test_student_cannot_read_draft_report(self):
        report = SimpleNamespace(workflow_status="draft")
        student = SimpleNamespace(role="student")

        with self.assertRaises(HTTPException) as context:
            _ensure_report_visible_to_user(report, student)

        self.assertEqual(context.exception.status_code, 404)

    def test_student_can_read_published_report(self):
        report = SimpleNamespace(workflow_status="published")
        student = SimpleNamespace(role="student")

        _ensure_report_visible_to_user(report, student)

    def test_reviewer_can_read_draft_report(self):
        report = SimpleNamespace(workflow_status="draft")
        teacher = SimpleNamespace(role="teacher")

        _ensure_report_visible_to_user(report, teacher)


if __name__ == "__main__":
    unittest.main()
