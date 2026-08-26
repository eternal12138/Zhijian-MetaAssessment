import unittest

from app.services.metacognition_distribution import (
    aggregate_distribution,
    normalize_dimension,
    resolve_run_distributions,
)


class MetacognitionDistributionTests(unittest.TestCase):
    def test_normalizes_supported_dimension_aliases(self):
        self.assertEqual(normalize_dimension("monitoring"), "monitoring")
        self.assertEqual(normalize_dimension("regulation"), "controlDebugging")
        self.assertEqual(normalize_dimension("control_debugging"), "controlDebugging")
        self.assertEqual(normalize_dimension("evaluation"), "evaluation")
        self.assertIsNone(normalize_dimension("planning"))

    def test_expert_result_has_priority_per_run_and_sources_can_mix(self):
        resolved = resolve_run_distributions(
            [("run-1", "monitoring", 2), ("run-1", "regulation", 1)],
            [
                ("run-1", "evaluation", 99),
                ("run-2", "monitoring", 1),
                ("run-2", "evaluation", 3),
            ],
        )
        self.assertEqual(resolved["run-1"]["source"], "expert_consensus")
        self.assertEqual(resolved["run-1"]["counts"]["evaluation"], 0)
        self.assertEqual(resolved["run-2"]["source"], "production_model")

        aggregate = aggregate_distribution(
            ["run-1", "run-2"], resolved, scope="class", label="2026级1班"
        )
        self.assertEqual(aggregate["counts"], {
            "monitoring": 3,
            "controlDebugging": 1,
            "evaluation": 3,
        })
        self.assertEqual(aggregate["total"], 7)
        self.assertEqual(aggregate["sample_count"], 2)
        self.assertEqual(aggregate["primary_source"], "hybrid")
        self.assertAlmostEqual(sum(aggregate["percentages"].values()), 100.0, delta=0.2)

    def test_empty_scope_does_not_emit_fake_radar_values(self):
        aggregate = aggregate_distribution([], {}, scope="participant", label="学生")
        self.assertEqual(aggregate["total"], 0)
        self.assertEqual(aggregate["scores"], [])
        self.assertEqual(aggregate["primary_source"], "none")


if __name__ == "__main__":
    unittest.main()
