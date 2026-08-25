import unittest
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.protocol import LIKERT_LABELS, NEXT_STAGE, _next_stage, _order_code, create_run
from app.models.protocol import AssessmentRun
from app.models.user import User
from app.schemas.protocol import (
    QuestionnaireAnswerIn,
    QuestionnaireSubmitIn,
    RunCreateIn,
    RunStageIn,
)
from app.services.questionnaire import CURRENT_QUESTIONNAIRE_SOURCE


class ProtocolRulesTest(unittest.IsolatedAsyncioTestCase):
    def test_protocol_stage_order_is_fixed(self):
        self.assertEqual(
            NEXT_STAGE,
            {
                "device_check": "instructions",
                "instructions": "practice",
                "practice": "task_1",
                "task_1": "task_2",
                "task_2": "questionnaire",
            },
        )

    def test_likert_scale_is_complete(self):
        self.assertEqual(set(LIKERT_LABELS), set(range(1, 8)))

    def test_task_two_routes_to_questionnaire_when_enabled(self):
        run = AssessmentRun(current_stage="task_2", questionnaire_enabled=True)
        self.assertEqual(_next_stage(run), "questionnaire")

    def test_task_two_routes_directly_to_review_when_questionnaire_disabled(self):
        run = AssessmentRun(current_stage="task_2", questionnaire_enabled=False)
        self.assertEqual(_next_stage(run), "review")

    def test_task_order_code_supports_counterbalancing(self):
        self.assertEqual(_order_code(["a", "b"], ["a", "b"]), "AB")
        self.assertEqual(_order_code(["b", "a"], ["a", "b"]), "BA")

    def test_questionnaire_answer_rejects_values_outside_one_to_seven(self):
        with self.assertRaises(ValidationError):
            QuestionnaireAnswerIn(item_id="item-1", value=0)
        with self.assertRaises(ValidationError):
            QuestionnaireAnswerIn(item_id="item-1", value=8)

    def test_questionnaire_requires_and_normalizes_participant_name(self):
        payload = QuestionnaireSubmitIn(
            answers=[QuestionnaireAnswerIn(item_id="item-1", value=4)],
            participant_name="  微信名   示例  ",
        )
        self.assertEqual(payload.participant_name, "微信名 示例")
        with self.assertRaises(ValidationError):
            QuestionnaireSubmitIn(
                answers=[QuestionnaireAnswerIn(item_id="item-1", value=4)],
                participant_name="   ",
            )

    def test_appendix_two_questionnaire_has_24_items_and_one_reverse_item(self):
        seed = (Path(__file__).resolve().parents[1] / "seed_phase2.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(seed.count("\n('zepeda23-"), 24)
        self.assertEqual(
            seed.count(f"'{CURRENT_QUESTIONNAIRE_SOURCE}', TRUE"),
            1,
        )

    def test_both_official_tasks_require_one_best_performer(self):
        seed = (Path(__file__).resolve().parents[1] / "seed_phase2.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("最终明确判断哪台投球机表现最优，并说明理由", seed)
        self.assertIn("设计并说明一种合理的数学程序", seed)
        self.assertIn("整个作答过程中持续口头说出你脑海中实时产生的所有想法", seed)
        self.assertIn("四台投球机落点与距离分布图", seed)
        self.assertIn(
            "最终明确判断Bill和Joe中哪位运动员表现最优，并说明理由",
            seed,
        )
        self.assertIn("表2给出了2000年跳高和跳远最佳成绩", seed)
        self.assertNotIn("表 A1", seed)

    def test_stage_schema_rejects_skipping_or_unknown_stages(self):
        with self.assertRaises(ValidationError):
            RunStageIn(stage="completed")

    async def test_run_requires_consent_before_database_access(self):
        user = User(
            id="student-1",
            username="student-1",
            password_hash="unused",
            name="Student",
            role="student",
            avatar_text="学",
        )
        with self.assertRaises(HTTPException) as context:
            await create_run(RunCreateIn(consent=False), user=user, db=None)
        self.assertEqual(context.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
