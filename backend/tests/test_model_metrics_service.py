import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.models.research import ModelTrainingJob
from app.services.model_artifacts import sha256_file
from app.services.model_metrics_service import (
    group_evaluations,
    load_job_evaluation,
    write_evaluation_bundle,
)


def metrics_payload(macro_f1: float = 0.62) -> dict:
    return {
        "accuracy": 0.64,
        "macro_precision": 0.63,
        "macro_recall": 0.61,
        "weighted_precision": 0.64,
        "weighted_recall": 0.64,
        "macro_specificity": 0.80,
        "macro_f1": macro_f1,
        "weighted_f1": 0.65,
        "macro_auc_ovr": 0.71,
        "cross_entropy": None,
        "per_class": {
            "1": {"precision": 0.60, "recall": 0.70, "specificity": 0.80, "f1": 0.65, "support": 10},
            "2": {"precision": 0.70, "recall": 0.60, "specificity": 0.82, "f1": 0.64, "support": 10},
            "3": {"precision": 0.59, "recall": 0.53, "specificity": 0.78, "f1": 0.56, "support": 10},
        },
        "confusion_matrix": [[7, 2, 1], [2, 6, 2], [2, 3, 5]],
        "folds": [
            {"fold": index, "train_sample_count": 24, "sample_count": 6,
             "train_macro_f1": 0.70 + index / 100, "macro_f1": 0.58 + index / 100,
             "macro_auc_ovr": 0.68 + index / 100,
             "per_class_auc": {"1": 0.70 + index / 100, "2": 0.68 + index / 100, "3": 0.66 + index / 100},
             "participant_overlap_count": 0, "subject_disjoint_verified": True}
            for index in range(1, 6)
        ],
        "evaluation_summary": {
            "sample_count": 30,
            "participant_count": 10,
            "label_distribution": {"1": 10, "2": 10, "3": 10},
            "external_holdout": False,
        },
        "split_strategy": "subject_grouped_stratified_5fold",
        "subject_leakage_risk": False,
    }


class ModelMetricsServiceTests(unittest.TestCase):
    def make_job(
        self, root: Path, suffix: str, experiment: str, group: str = "group-1",
        fingerprint: str = "f" * 64,
        expected_experiments: list[str] | None = None,
    ) -> ModelTrainingJob:
        directory = root / suffix
        directory.mkdir()
        artifact = directory / "model.joblib"
        artifact.write_bytes(f"model-{suffix}".encode())
        metrics = metrics_payload(0.60 + len(suffix) / 100)
        (directory / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        now = datetime.now(timezone.utc)
        job = ModelTrainingJob(
            id=f"job-{suffix}", version=suffix, requested_by="researcher",
            status="completed", stage="completed", progress=100,
            sample_count=30, label_distribution={"1": 10, "2": 10, "3": 10},
            dataset_fingerprint=fingerprint,
            config_snapshot={
                "experiment_type": experiment,
                "comparison_group_id": group,
                "comparison_group_label": "gold-v1",
                "comparison_expected_experiments": expected_experiments,
                "dataset_id": "dataset-1", "dataset_name": "gold_dataset_v1",
                "dataset_fingerprint": fingerprint,
                "dataset_split_strategy": "subject_grouped_stratified_5fold",
                "random_seed": 42,
                "feature": "tfidf" if experiment == "tfidf_linear_svc" else "remote_embedding",
                "classifier": "linear_svc",
            },
            metrics=metrics, artifact_path=str(artifact), artifact_sha256=sha256_file(artifact),
            created_at=now, completed_at=now, updated_at=now,
        )
        write_evaluation_bundle(job, directory, metrics, now)
        return job

    def test_evaluation_uses_bound_artifacts_and_actual_three_labels(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = self.make_job(root, "v1", "tfidf_linear_svc", "single-group")
            result = load_job_evaluation(job, root)
            self.assertEqual([item["id"] for item in result["labels"]], [1, 2, 3])
            self.assertEqual(result["summary"]["accuracy"], job.metrics["accuracy"])
            self.assertEqual(result["summary"]["macro_auc_ovr"], 0.71)
            self.assertEqual(result["confusion_matrix"], job.metrics["confusion_matrix"])
            self.assertEqual(result["cross_validation"]["train_sample_counts"], [24] * 5)
            self.assertAlmostEqual(result["cross_validation"]["macro_f1_range"], 0.04)
            # F1 values: [0.59, 0.60, 0.61, 0.62, 0.63], mean = 0.61, sample std = sqrt(0.0025/4) = sqrt(0.000625) = 0.0158113883
            self.assertAlmostEqual(result["cross_validation"]["macro_f1_mean"], 0.61)
            self.assertAlmostEqual(result["cross_validation"]["macro_f1_std"], 0.015811388300841896)
            # Fold AUC values: [0.69, 0.70, 0.71, 0.72, 0.73]
            self.assertAlmostEqual(result["cross_validation"]["macro_auc_mean"], 0.71)
            self.assertAlmostEqual(result["cross_validation"]["macro_auc_std"], 0.015811388300841896)
            self.assertAlmostEqual(result["cross_validation"]["macro_auc_min"], 0.69)
            self.assertAlmostEqual(result["cross_validation"]["macro_auc_max"], 0.73)
            self.assertAlmostEqual(result["cross_validation"]["macro_auc_range"], 0.04)
            self.assertEqual(result["summary"]["weighted_precision"], 0.64)
            self.assertTrue(result["cross_validation"]["subject_disjoint_audit"]["all_folds_verified"])
            self.assertEqual(result["cross_validation"]["macro_auc_interval"]["n"], 5)
            self.assertEqual(result["cross_validation"]["per_class_auc_intervals"]["1"]["n"], 5)

    def test_modified_metrics_file_is_rejected_instead_of_displayed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = self.make_job(root, "v1", "tfidf_linear_svc", "single-group")
            path = root / "v1" / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["accuracy"] = 0.99
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "完整性校验失败"):
                load_job_evaluation(job, root)

    def test_missing_metric_remains_null(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = self.make_job(root, "v1", "tfidf_linear_svc", "single-group")
            job.metrics.pop("macro_auc_ovr")
            metrics_path = root / "v1" / "metrics.json"
            metrics_path.write_text(json.dumps(job.metrics), encoding="utf-8")
            write_evaluation_bundle(job, root / "v1", job.metrics, job.completed_at)
            result = load_job_evaluation(job, root)
            self.assertIsNone(result["summary"]["macro_auc_ovr"])

    def test_different_dataset_versions_are_not_ranked(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs = [
                self.make_job(root, "tfidf", "tfidf_linear_svc", fingerprint="a" * 64),
                self.make_job(root, "emb-svc", "embedding_linear_svc", fingerprint="b" * 64),
                self.make_job(root, "emb-logistic", "embedding_logistic", fingerprint="a" * 64),
                self.make_job(root, "emb-rf", "embedding_random_forest", fingerprint="a" * 64),
            ]
            version = group_evaluations(jobs, root)["versions"][0]
            self.assertFalse(version["comparable"])
            self.assertIsNone(version["best_model_id"])

    def test_manifest_model_version_mismatch_is_rejected(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = self.make_job(root, "v1", "tfidf_linear_svc", "single-group")
            path = root / "v1" / "evaluation_manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["model_version"] = "another-run"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "model_version"):
                load_job_evaluation(job, root)

    def test_full_suite_best_model_and_version_are_bound(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs = [
                self.make_job(root, "tfidf", "tfidf_linear_svc"),
                self.make_job(root, "emb-svc", "embedding_linear_svc"),
                self.make_job(root, "emb-logistic", "embedding_logistic"),
                self.make_job(root, "emb-rf", "embedding_random_forest"),
            ]
            result = group_evaluations(jobs, root)
            self.assertEqual(result["latest_version_id"], "group-1")
            self.assertEqual(len(result["versions"]), 1)
            version = result["versions"][0]
            self.assertTrue(version["comparable"])
            self.assertEqual(version["best_model_id"], "job-emb-logistic")
            self.assertEqual({model["dataset_fingerprint"] for model in version["models"]}, {"f" * 64})

    def test_custom_suite_is_complete_with_only_selected_models(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = ["tfidf_linear_svc", "embedding_logistic"]
            jobs = [
                self.make_job(
                    root, "custom-tfidf", "tfidf_linear_svc",
                    expected_experiments=expected,
                ),
                self.make_job(
                    root, "custom-logistic", "embedding_logistic",
                    expected_experiments=expected,
                ),
            ]
            version = group_evaluations(jobs, root)["versions"][0]
            self.assertTrue(version["comparable"])
            self.assertEqual(len(version["models"]), 2)
            self.assertEqual(version["best_model_id"], "job-custom-logistic")


if __name__ == "__main__":
    unittest.main()
