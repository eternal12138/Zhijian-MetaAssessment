from __future__ import annotations

import csv
import gc
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .inference import _load_artifact


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except ImportError:
        return float("nan")


def _directory_mb(path: Path) -> float:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) / (1024 * 1024)


def _percentile(values: Sequence[float], percentile: float) -> float:
    return float(np.percentile(np.asarray(values), percentile))


def benchmark_model(
    model_name: str,
    *,
    models_root: Path,
    texts: Sequence[str],
    metrics: dict[str, Any] | None,
    repeats: int = 20,
    batch_size: int = 16,
) -> dict[str, Any]:
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")
    directory = models_root / model_name
    row: dict[str, Any] = {
        "model": model_name,
        "feature": "",
        "accuracy": (metrics or {}).get("accuracy"),
        "macro_f1": (metrics or {}).get("macro_f1"),
        "weighted_f1": (metrics or {}).get("weighted_f1"),
        "model_size_mb": None,
        "load_time_ms": None,
        "resident_memory_delta_mb": None,
        "avg_latency_ms": None,
        "p50_latency_ms": None,
        "p95_latency_ms": None,
        "batch_latency_ms": None,
        "batch_size": min(batch_size, len(texts)),
        "peak_memory_mb": None,
        "cpu_threads": 2,
        "cpu_stable": False,
        "production_recommended": False,
        "status": "failed",
        "failure_reason": "",
    }
    try:
        if not directory.exists():
            raise FileNotFoundError(f"model artifact missing: {directory}")
        _load_artifact.cache_clear()
        gc.collect()
        before = _rss_mb()
        start = time.perf_counter()
        model, config = _load_artifact(str(directory.resolve()))
        remote_embedding = config.get("feature") == "remote_embedding"
        from threadpoolctl import threadpool_limits

        threadpool_limits(limits=2)
        loaded = _rss_mb()
        load_time = (time.perf_counter() - start) * 1000
        row["feature"] = config.get("feature")
        artifact_size = _directory_mb(directory)
        row["model_size_mb"] = artifact_size
        row["load_time_ms"] = load_time
        row["resident_memory_delta_mb"] = max(0.0, loaded - before)
        latencies: list[float] = []
        peak = loaded
        for index in range(repeats):
            text = texts[index % len(texts)]
            started = time.perf_counter()
            features = (
                np.zeros((1, int(config.get("embedding_config", {}).get("embedding_dimension", 0))), dtype=np.float32)
                if remote_embedding else [text]
            )
            model.predict(features)
            latencies.append((time.perf_counter() - started) * 1000)
            peak = max(peak, _rss_mb())
        batch = list(texts[: min(batch_size, len(texts))])
        started = time.perf_counter()
        features = (
            np.zeros((len(batch), int(config.get("embedding_config", {}).get("embedding_dimension", 0))), dtype=np.float32)
            if remote_embedding else batch
        )
        model.predict(features)
        batch_latency = (time.perf_counter() - started) * 1000
        peak = max(peak, _rss_mb())
        row.update({
            "avg_latency_ms": statistics.mean(latencies),
            "p50_latency_ms": _percentile(latencies, 50),
            "p95_latency_ms": _percentile(latencies, 95),
            "batch_latency_ms": batch_latency,
            "peak_memory_mb": peak,
            "cpu_stable": True,
            "status": "completed",
        })
    except Exception as exc:
        row["failure_reason"] = f"{type(exc).__name__}: {exc}"
    return row


def run_deployment_benchmark(
    *,
    output_root: Path,
    texts: Sequence[str],
) -> list[dict[str, Any]]:
    reports_root = output_root / "reports"
    models_root = output_root / "models"
    metrics_by_model: dict[str, dict[str, Any] | None] = {}
    for model_name in ("tfidf_linear_svc", "embedding_linear_svc", "embedding_logistic"):
        metrics_path = models_root / model_name / "metrics.json"
        metrics_by_model[model_name] = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None
    rows = [
        benchmark_model(
            name, models_root=models_root, texts=texts,
            metrics=metrics_by_model[name],
        )
        for name in metrics_by_model
    ]
    completed = [row for row in rows if row["status"] == "completed"]
    scientific_best = max(completed, key=lambda row: row["macro_f1"] or -1, default=None)
    tfidf = next((row for row in completed if row["model"] == "tfidf_linear_svc"), None)
    remote_best = max(
        (row for row in completed if row["model"].startswith("embedding_")),
        key=lambda row: row["macro_f1"] or -1,
        default=None,
    )
    production = None
    architecture = "no deployable model"
    if tfidf:
        production = tfidf
        architecture = "A: TF-IDF + LinearSVC"
        tfidf["production_recommended"] = True
    if remote_best and (
        not tfidf or (remote_best["macro_f1"] or 0) > (tfidf["macro_f1"] or 0) + 0.03
    ):
        production = remote_best
        architecture = "B: remote Embedding API + local scikit-learn classifier"
        if tfidf:
            tfidf["production_recommended"] = False
        remote_best["production_recommended"] = True
    api_metrics_path = reports_root / "embedding_api_metrics.json"
    api_metrics = json.loads(api_metrics_path.read_text(encoding="utf-8")) if api_metrics_path.exists() else {}
    for row in rows:
        is_remote = row["model"].startswith("embedding_")
        row["local_model_size_mb"] = row["model_size_mb"]
        row["local_memory_mb"] = row["resident_memory_delta_mb"]
        row["classifier_latency_ms"] = row["avg_latency_ms"]
        row["embedding_api_latency_ms"] = api_metrics.get("embedding_api_avg_latency_ms") if is_remote else None
        row["embedding_api_p50_ms"] = api_metrics.get("embedding_api_p50_latency_ms") if is_remote else None
        row["embedding_api_p95_ms"] = api_metrics.get("embedding_api_p95_latency_ms") if is_remote else None
        row["embedding_api_failure_rate"] = api_metrics.get("api_failure_rate") if is_remote else None
        row["embedding_api_average_batch_size"] = api_metrics.get("average_batch_size") if is_remote else None
        row["end_to_end_latency_ms"] = (
            (row["avg_latency_ms"] or 0) + (row["embedding_api_latency_ms"] or 0)
            if row["status"] == "completed" else None
        )
    columns = list(rows[0].keys())
    with (reports_root / "deployment_benchmark.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    recommendation = {
        "scientific_best": scientific_best["model"] if scientific_best else None,
        "scientific_best_scope": "completed_models_only",
        "embedding_comparison_complete": bool(
            any(row["model"].startswith("embedding_") and row["status"] == "completed" for row in rows)
        ),
        "production_recommended": production["model"] if production else None,
        "production_recommendation_status": (
            "final" if any(
                row["model"].startswith("embedding_") and row["status"] == "completed" for row in rows
            ) else "provisional_until_embedding_api_benchmark"
        ),
        "production_architecture": architecture,
        "selection_rule": "Macro-F1 + model size + RSS/peak memory + CPU P95 latency",
        "host_constraint": "2 CPU / 4 GiB RAM / no GPU",
        "worker_recommendation": 1,
    }
    (reports_root / "deployment_recommendation.json").write_text(
        json.dumps(recommendation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rows
