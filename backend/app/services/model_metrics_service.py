"""训练评估产物的写入、校验和统一读取层。

前端不得直接读取训练目录中的 JSON/CSV。本服务以 evaluation_manifest.json
绑定模型任务、模型版本、数据集版本和指标文件，并在返回 API 数据前校验
文件、数据库记录和标签顺序的一致性。
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from math import sqrt
from statistics import fmean, pstdev, stdev
from typing import Any, Iterable

from app.models.research import ModelTrainingJob
from app.training.baseline_models import TRAINING_LABEL_NAMES


CORE_METRICS = (
    "accuracy", "macro_precision", "macro_recall", "macro_specificity",
    "weighted_precision", "weighted_recall", "macro_f1", "weighted_f1",
    "macro_auc_ovr", "cross_entropy",
)


def _fold_interval(values: list[float]) -> dict[str, Any]:
    """Return a transparent 95% t interval over fold-level measurements."""
    if not values:
        return {"mean": None, "std": None, "ci95_low": None, "ci95_high": None, "n": 0}
    mean = fmean(values)
    deviation = stdev(values) if len(values) > 1 else 0.0
    # Two-sided t(0.975, df) critical values for the only fold counts used here.
    critical = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776}.get(len(values) - 1, 1.96)
    margin = critical * deviation / sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "mean": mean,
        "std": deviation,
        "ci95_low": max(0.0, mean - margin),
        "ci95_high": min(1.0, mean + margin),
        "n": len(values),
        "method": "two_sided_t_interval_over_folds",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _write_csv_atomic(path: Path, headers: list[str], rows: Iterable[list[Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)
    temporary.replace(path)


def _metric_labels(metrics: dict[str, Any]) -> list[int]:
    try:
        labels = sorted(int(value) for value in (metrics.get("per_class") or {}).keys())
    except (TypeError, ValueError) as error:
        raise ValueError("训练指标中的标签无法解析") from error
    if not labels:
        raise ValueError("训练指标缺少 per_class 标签")
    return labels


def write_evaluation_bundle(
    job: ModelTrainingJob,
    artifact_dir: Path,
    metrics: dict[str, Any],
    trained_at: datetime,
) -> dict[str, Any]:
    """为一次训练写入可追溯评估文件和 manifest。"""
    labels = _metric_labels(metrics)
    label_names = {
        label: TRAINING_LABEL_NAMES.get(label, f"标签{label}") for label in labels
    }
    per_class = metrics.get("per_class") or {}
    matrix = metrics.get("confusion_matrix") or []
    if len(matrix) != len(labels) or any(len(row) != len(labels) for row in matrix):
        raise ValueError("混淆矩阵尺寸与训练标签数量不一致")

    classification_path = artifact_dir / "classification_report.csv"
    _write_csv_atomic(
        classification_path,
        ["label_id", "label_name", "precision", "recall", "specificity", "f1", "support"],
        [[
            label, label_names[label],
            (per_class.get(str(label)) or {}).get("precision"),
            (per_class.get(str(label)) or {}).get("recall"),
            (per_class.get(str(label)) or {}).get("specificity"),
            (per_class.get(str(label)) or {}).get("f1"),
            (per_class.get(str(label)) or {}).get("support"),
        ] for label in labels],
    )
    confusion_path = artifact_dir / "confusion_matrix.csv"
    _write_csv_atomic(
        confusion_path,
        ["actual/predicted", *[label_names[label] for label in labels]],
        [[label_names[labels[index]], *row] for index, row in enumerate(matrix)],
    )
    metrics_path = artifact_dir / "metrics.json"
    if not metrics_path.is_file():
        raise ValueError("训练指标文件尚未生成")
    snapshot = dict(job.config_snapshot or {})
    manifest = {
        "schema_version": 1,
        "model_id": job.id,
        "model_version": job.version,
        "dataset_id": snapshot.get("dataset_id"),
        "dataset_version": snapshot.get("dataset_name"),
        "dataset_fingerprint": job.dataset_fingerprint or snapshot.get("dataset_fingerprint"),
        "comparison_group_id": snapshot.get("comparison_group_id"),
        "comparison_group_label": snapshot.get("comparison_group_label"),
        "classifier_parameters": snapshot.get("classifier_parameters") or {},
        "hyperparameters_tuned": bool(snapshot.get("hyperparameters_tuned")),
        "hyperparameter_source": snapshot.get("hyperparameter_source") or "default",
        "task": "three_class_metacognition",
        "labels": [{"id": label, "name": label_names[label]} for label in labels],
        "trained_at": trained_at.isoformat(),
        "metrics_file": metrics_path.name,
        "metrics_sha256": _sha256(metrics_path),
        "classification_report_file": classification_path.name,
        "classification_report_sha256": _sha256(classification_path),
        "confusion_matrix_file": confusion_path.name,
        "confusion_matrix_sha256": _sha256(confusion_path),
        "artifact_sha256": job.artifact_sha256,
    }
    _write_json_atomic(artifact_dir / "evaluation_manifest.json", manifest)
    return manifest


def _artifact_directory(job: ModelTrainingJob, model_root: Path) -> Path:
    if not job.artifact_path:
        raise ValueError("训练任务缺少模型产物路径")
    root = model_root.resolve()
    artifact = Path(job.artifact_path)
    if not artifact.is_absolute():
        artifact = artifact.resolve()
    directory = artifact.parent.resolve()
    if directory != root and root not in directory.parents:
        raise ValueError("模型评估产物路径超出配置目录")
    return directory


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取训练评估文件：{path.name}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"训练评估文件格式错误：{path.name}")
    return payload


def _same_metric(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= 1e-12
    return left == right


def _validate_manifest(
    job: ModelTrainingJob, manifest: dict[str, Any], metrics: dict[str, Any], directory: Path,
) -> None:
    snapshot = dict(job.config_snapshot or {})
    expected = {
        "model_id": job.id,
        "model_version": job.version,
        "dataset_id": snapshot.get("dataset_id"),
        "dataset_version": snapshot.get("dataset_name"),
        "dataset_fingerprint": job.dataset_fingerprint or snapshot.get("dataset_fingerprint"),
    }
    mismatches = [key for key, value in expected.items() if manifest.get(key) != value]
    if mismatches:
        raise ValueError(f"训练结果 manifest 与任务记录不一致：{', '.join(mismatches)}")
    metrics_path = directory / str(manifest.get("metrics_file") or "")
    if not metrics_path.is_file() or _sha256(metrics_path) != manifest.get("metrics_sha256"):
        raise ValueError("metrics.json 完整性校验失败")
    for file_key, hash_key in (
        ("classification_report_file", "classification_report_sha256"),
        ("confusion_matrix_file", "confusion_matrix_sha256"),
    ):
        report_path = directory / str(manifest.get(file_key) or "")
        if not report_path.is_file() or _sha256(report_path) != manifest.get(hash_key):
            raise ValueError(f"{report_path.name or file_key} 完整性校验失败")
    artifact_path = Path(job.artifact_path or "")
    if not artifact_path.is_absolute():
        artifact_path = artifact_path.resolve()
    if (
        not artifact_path.is_file()
        or manifest.get("artifact_sha256") != job.artifact_sha256
        or _sha256(artifact_path) != job.artifact_sha256
    ):
        raise ValueError("模型文件完整性校验失败")
    manifest_labels = [int(item["id"]) for item in manifest.get("labels") or []]
    if manifest_labels != _metric_labels(metrics):
        raise ValueError("manifest 标签顺序与训练指标不一致")


def _legacy_manifest(job: ModelTrainingJob, metrics: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(job.config_snapshot or {})
    return {
        "schema_version": 0,
        "model_id": job.id,
        "model_version": job.version,
        "dataset_id": snapshot.get("dataset_id"),
        "dataset_version": snapshot.get("dataset_name") or "历史数据集版本未记录",
        "dataset_fingerprint": job.dataset_fingerprint,
        "comparison_group_id": snapshot.get("comparison_group_id"),
        "comparison_group_label": snapshot.get("comparison_group_label"),
        "task": "three_class_metacognition" if _metric_labels(metrics) == [1, 2, 3] else "legacy_metacognition",
        "labels": [
            {"id": label, "name": TRAINING_LABEL_NAMES.get(label, f"标签{label}")}
            for label in _metric_labels(metrics)
        ],
        "trained_at": job.completed_at.isoformat() if job.completed_at else None,
        "metrics_file": "metrics.json",
        "legacy_synthesized": True,
    }


def _confusion_pairs(matrix: list[list[int]], labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = []
    for actual_index, row in enumerate(matrix):
        for predicted_index, count in enumerate(row):
            if actual_index == predicted_index or not count:
                continue
            pairs.append({
                "actual_label": labels[actual_index]["name"],
                "predicted_label": labels[predicted_index]["name"],
                "count": int(count),
            })
    return sorted(pairs, key=lambda item: (-item["count"], item["actual_label"], item["predicted_label"]))


def load_job_evaluation(job: ModelTrainingJob, model_root: Path) -> dict[str, Any]:
    """读取一个已完成任务的真实评估文件并与数据库记录交叉校验。"""
    if job.status != "completed" or not job.metrics:
        raise ValueError("训练任务尚未产生完整评估结果")
    directory = _artifact_directory(job, model_root)
    metrics_path = directory / "metrics.json"
    metrics = _load_json(metrics_path)
    manifest_path = directory / "evaluation_manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.is_file() else _legacy_manifest(job, metrics)
    if manifest_path.is_file():
        _validate_manifest(job, manifest, metrics, directory)
    for key in CORE_METRICS:
        if not _same_metric(metrics.get(key), (job.metrics or {}).get(key)):
            raise ValueError(f"训练文件与任务记录的 {key} 不一致")

    labels = list(manifest.get("labels") or [])
    per_class_raw = metrics.get("per_class") or {}
    matrix = metrics.get("confusion_matrix") or []
    if len(matrix) != len(labels) or any(len(row) != len(labels) for row in matrix):
        raise ValueError("混淆矩阵与 manifest 标签数量不一致")
    per_class = []
    for label in labels:
        values = per_class_raw.get(str(label["id"]))
        if not isinstance(values, dict):
            raise ValueError(f"训练指标缺少标签 {label['id']} 的分类报告")
        per_class.append({"label_id": label["id"], "label_name": label["name"], **values})

    folds = metrics.get("folds") or []
    fold_f1 = [float(item["macro_f1"]) for item in folds if isinstance(item.get("macro_f1"), (int, float))]
    train_fold_f1 = [
        float(item["train_macro_f1"])
        for item in folds
        if isinstance(item.get("train_macro_f1"), (int, float))
    ]
    train_sample_counts = [
        int(item["train_sample_count"])
        for item in folds
        if isinstance(item.get("train_sample_count"), (int, float))
    ]
    test_sample_counts = [
        int(item["sample_count"])
        for item in folds
        if isinstance(item.get("sample_count"), (int, float))
    ]
    fold_mean = fmean(fold_f1) if fold_f1 else None
    train_fold_mean = fmean(train_fold_f1) if train_fold_f1 else None
    fold_macro_auc = [
        float(item["macro_auc_ovr"])
        for item in folds
        if isinstance(item.get("macro_auc_ovr"), (int, float))
    ]
    fold_auc_mean = fmean(fold_macro_auc) if fold_macro_auc else None
    fold_auc_std = stdev(fold_macro_auc) if len(fold_macro_auc) > 1 else (0.0 if fold_macro_auc else None)
    fold_auc_min = min(fold_macro_auc) if fold_macro_auc else None
    fold_auc_max = max(fold_macro_auc) if fold_macro_auc else None
    fold_auc_range = max(fold_macro_auc) - min(fold_macro_auc) if fold_macro_auc else None
    per_class_auc_intervals = {}
    for label in labels:
        values = [
            float((item.get("per_class_auc") or {}).get(str(label["id"])))
            for item in folds
            if isinstance((item.get("per_class_auc") or {}).get(str(label["id"])), (int, float))
        ]
        per_class_auc_intervals[str(label["id"])] = _fold_interval(values)
    overlap_counts = [
        int(item["participant_overlap_count"])
        for item in folds
        if isinstance(item.get("participant_overlap_count"), (int, float))
    ]
    snapshot = dict(job.config_snapshot or {})
    return {
        "model_id": job.id,
        "model_version": job.version,
        "dataset_id": manifest.get("dataset_id"),
        "dataset_version": manifest.get("dataset_version"),
        "dataset_fingerprint": manifest.get("dataset_fingerprint"),
        "comparison_group_id": manifest.get("comparison_group_id"),
        "comparison_group_label": manifest.get("comparison_group_label"),
        "trained_at": manifest.get("trained_at") or (job.completed_at.isoformat() if job.completed_at else None),
        "labels": labels,
        "summary": {key: metrics.get(key) for key in CORE_METRICS},
        "per_class": per_class,
        "confusion_matrix": matrix,
        "confusion_pairs": _confusion_pairs(matrix, labels),
        "cross_validation": {
            "fold_count": len(folds),
            "macro_f1_mean": fold_mean,
            "macro_f1_std": stdev(fold_f1) if len(fold_f1) > 1 else (0.0 if fold_f1 else None),
            "macro_f1_min": min(fold_f1) if fold_f1 else None,
            "macro_f1_max": max(fold_f1) if fold_f1 else None,
            "macro_f1_range": max(fold_f1) - min(fold_f1) if fold_f1 else None,
            "macro_auc_mean": fold_auc_mean,
            "macro_auc_std": fold_auc_std,
            "macro_auc_min": fold_auc_min,
            "macro_auc_max": fold_auc_max,
            "macro_auc_range": fold_auc_range,
            "macro_f1_interval": _fold_interval(fold_f1),
            "macro_auc_interval": _fold_interval(fold_macro_auc),
            "per_class_auc_intervals": per_class_auc_intervals,
            "train_macro_f1_mean": train_fold_mean,
            "train_test_macro_f1_gap": (
                train_fold_mean - float(metrics["macro_f1"])
                if train_fold_mean is not None and isinstance(metrics.get("macro_f1"), (int, float))
                else None
            ),
            "train_sample_counts": train_sample_counts,
            "test_sample_counts": test_sample_counts,
            "folds": folds,
            "subject_disjoint_audit": {
                "available": len(overlap_counts) == len(folds) and bool(folds),
                "all_folds_verified": (
                    len(overlap_counts) == len(folds) and bool(folds)
                    and all(value == 0 for value in overlap_counts)
                ),
                "maximum_overlap_count": max(overlap_counts) if overlap_counts else None,
                "note": (
                    "每折训练被试与测试被试交集均为 0。"
                    if len(overlap_counts) == len(folds) and folds and all(value == 0 for value in overlap_counts)
                    else "该训练版本没有完整的折级被试交集证据。"
                ),
            },
        },
        "dataset": {
            "version": manifest.get("dataset_version"),
            "fingerprint": manifest.get("dataset_fingerprint"),
            "sample_count": metrics.get("evaluation_summary", {}).get("sample_count", job.sample_count),
            "participant_count": metrics.get("evaluation_summary", {}).get("participant_count"),
            "class_count": len(labels),
            "class_distribution": metrics.get("evaluation_summary", {}).get("label_distribution") or job.label_distribution,
            "split_strategy": metrics.get("split_strategy") or snapshot.get("dataset_split_strategy"),
            "random_seed": snapshot.get("random_seed"),
            "external_holdout": bool(metrics.get("evaluation_summary", {}).get("external_holdout", False)),
        },
        "model_info": {
            "feature_type": snapshot.get("feature"),
            "classifier": snapshot.get("classifier"),
            "embedding_provider": snapshot.get("embedding_provider"),
            "embedding_model": snapshot.get("embedding_model"),
            "training_pipeline_version": snapshot.get("training_pipeline_version"),
            "classifier_parameters": snapshot.get("classifier_parameters") or {},
            "hyperparameters_tuned": bool(snapshot.get("hyperparameters_tuned")),
            "hyperparameter_source": snapshot.get("hyperparameter_source") or "default",
            "is_active": job.is_active,
        },
        "roc_curves": metrics.get("roc_curves"),
        "roc_evaluation": metrics.get("roc_evaluation"),
        "subject_leakage_risk": metrics.get("subject_leakage_risk"),
        "evaluation_warning": metrics.get("evaluation_warning"),
        "error_analysis": metrics.get("error_analysis"),
        "evidence_coverage": {
            "subject_level_split": len(overlap_counts) == len(folds) and bool(folds),
            "fold_uncertainty": bool(fold_f1),
            "independent_external_holdout": bool(
                metrics.get("evaluation_summary", {}).get("external_holdout", False)
            ),
            "pairwise_statistical_test": bool(metrics.get("pairwise_statistical_test")),
            "cross_task_transfer": bool(metrics.get("cross_task_transfer")),
            "expert_reliability_bound_to_dataset": bool(metrics.get("expert_reliability")),
            "asr_quality_bound_to_dataset": bool(metrics.get("asr_quality")),
            "notes": {
                "pairwise_statistical_test": "当前训练产物未保存可用于配对显著性检验的完整折外分数矩阵。",
                "cross_task_transfer": "当前冻结训练快照没有 task_id，不能生成跨任务迁移结果。",
                "expert_reliability_bound_to_dataset": "系统已有全局 Cohen κ 统计，但尚未与本次冻结训练数据版本绑定。",
                "asr_quality_bound_to_dataset": "当前训练快照只含清洗后文本和标签，未绑定 ASR 原文或音频质量指标。",
            },
        },
        "source": {
            "type": "training_evaluation_result",
            "manifest_schema_version": manifest.get("schema_version"),
            "legacy_synthesized": bool(manifest.get("legacy_synthesized")),
            "metrics_sha256": manifest.get("metrics_sha256") or _sha256(metrics_path),
        },
    }


def group_evaluations(jobs: list[ModelTrainingJob], model_root: Path) -> dict[str, Any]:
    """按冻结训练版本分组，只返回可安全比较的完整版本。"""
    grouped: dict[str, list[ModelTrainingJob]] = {}
    for job in jobs:
        snapshot = dict(job.config_snapshot or {})
        group_id = str(snapshot.get("comparison_group_id") or f"single:{job.id}")
        grouped.setdefault(group_id, []).append(job)

    versions = []
    errors = []
    for group_id, group_jobs in grouped.items():
        completed_by_experiment: dict[str, ModelTrainingJob] = {}
        for job in sorted(group_jobs, key=lambda item: (item.completed_at or item.created_at, item.id), reverse=True):
            experiment = str((job.config_snapshot or {}).get("experiment_type") or "legacy")
            if job.status == "completed" and experiment not in completed_by_experiment:
                completed_by_experiment[experiment] = job
        is_suite = not group_id.startswith("single:")
        first_job = group_jobs[0]
        first_job_snapshot = dict(first_job.config_snapshot or {})
        expected_experiments = first_job_snapshot.get("comparison_expected_experiments")
        expected_count = (
            len(expected_experiments)
            if is_suite and isinstance(expected_experiments, list) and expected_experiments
            else (4 if is_suite else 1)
        )
        if len(completed_by_experiment) < expected_count:
            continue
        try:
            models = [load_job_evaluation(job, model_root) for job in completed_by_experiment.values()]
        except ValueError as error:
            errors.append({"version_id": group_id, "error": str(error)})
            continue
        fingerprints = {model["dataset_fingerprint"] for model in models}
        label_orders = {tuple(item["id"] for item in model["labels"]) for model in models}
        comparable = len(fingerprints) == 1 and None not in fingerprints and len(label_orders) == 1
        comparison_warning = None if comparable else "数据集版本或标签顺序不同，不允许直接比较或自动标记最佳模型"
        ranked = sorted(
            models,
            key=lambda model: (
                -(model["summary"].get("macro_f1") if model["summary"].get("macro_f1") is not None else -1),
                -(model["summary"].get("macro_recall") if model["summary"].get("macro_recall") is not None else -1),
                -(model["summary"].get("weighted_f1") if model["summary"].get("weighted_f1") is not None else -1),
                model["model_version"],
            ),
        )
        trained_at = max((model.get("trained_at") or "" for model in models), default="")
        first_snapshot = dict(completed_by_experiment[next(iter(completed_by_experiment))].config_snapshot or {})
        versions.append({
            "version_id": group_id,
            "display_version": first_snapshot.get("comparison_group_label") or ranked[0]["model_version"],
            "dataset_version": ranked[0]["dataset_version"] if comparable else None,
            "dataset_fingerprint": ranked[0]["dataset_fingerprint"] if comparable else None,
            "trained_at": trained_at,
            "comparable": comparable,
            "comparison_warning": comparison_warning,
            "best_model_id": ranked[0]["model_id"] if comparable else None,
            "models": ranked,
        })
    versions.sort(key=lambda item: (item["trained_at"], item["version_id"]), reverse=True)
    return {
        "schema_version": 1,
        "primary_metric": "macro_f1",
        "tie_breakers": ["macro_recall", "weighted_f1", "model_version"],
        "latest_version_id": versions[0]["version_id"] if versions else None,
        "versions": versions,
        "errors": errors,
    }
