import unittest

from app.services.metacognition_pattern import classify_metacognition_pattern


class MetacognitionPatternTests(unittest.TestCase):
    def test_too_few_dialogues_never_forces_a_pattern(self):
        result = classify_metacognition_pattern(
            {"monitoring": 1 / 3, "controlDebugging": 2 / 3, "evaluation": 0},
            3,
        )
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["label"], "证据不足，暂不判定")
        self.assertTrue(result["is_provisional"])

    def test_relative_contrast_uses_personal_mean_and_requested_wording(self):
        result = classify_metacognition_pattern(
            {"monitoring": 1 / 3, "controlDebugging": 2 / 3, "evaluation": 0},
            10,
        )
        self.assertEqual(result["status"], "provisional")
        self.assertEqual(result["relative_high_dimensions"], ["controlDebugging"])
        self.assertEqual(result["relative_low_dimensions"], ["evaluation"])
        self.assertEqual(result["label"], "控制/调试相对突出－评估证据相对较少型")
        self.assertIn("仅供参考并非稳定能力或人格类型", result["title"])

    def test_balanced_profile_is_available_with_enough_dialogues(self):
        result = classify_metacognition_pattern(
            {"monitoring": 0.42, "controlDebugging": 0.36, "evaluation": 0.31},
            15,
        )
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["key"], "relative_balanced")
        self.assertEqual(result["relative_high_dimensions"], [])
        self.assertEqual(result["relative_low_dimensions"], [])

    def test_upstream_provisional_state_is_preserved(self):
        result = classify_metacognition_pattern(
            {"monitoring": 0.7, "controlDebugging": 0.35, "evaluation": 0.1},
            30,
            source_is_provisional=True,
        )
        self.assertEqual(result["status"], "provisional")
        self.assertTrue(result["is_provisional"])

    def test_mixed_result_and_group_norm_hook_have_stable_contract(self):
        result = classify_metacognition_pattern(
            {"monitoring": 0, "controlDebugging": 0.09, "evaluation": 0.16},
            20,
        )
        self.assertEqual(result["key"], "relative_mixed")
        self.assertEqual(result["group_norm"]["status"], "not_connected")
        self.assertIsNone(result["group_norm"]["percentiles"])

        connected = classify_metacognition_pattern(
            {"monitoring": 0.4, "controlDebugging": 0.3, "evaluation": 0.2},
            20,
            group_norm={
                "reference_id": "class-2026-v1",
                "reference_label": "2026级参考样本",
                "percentiles": {
                    "monitoring": 62.34,
                    "controlDebugging": 51,
                    "evaluation": 37.8,
                },
            },
        )
        self.assertEqual(connected["group_norm"]["status"], "available")
        self.assertEqual(connected["group_norm"]["percentiles"]["monitoring"], 62.3)

    def test_invalid_score_is_rejected(self):
        with self.assertRaises(ValueError):
            classify_metacognition_pattern(
                {"monitoring": 1.1, "controlDebugging": 0.2, "evaluation": 0.1},
                20,
            )


if __name__ == "__main__":
    unittest.main()
