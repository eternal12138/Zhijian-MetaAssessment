from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from .constants import LABELS, MODEL_VERSION, RANDOM_STATE
from .data import LoadedDataset, assert_trainable, write_quality_report
from .evaluation import write_comparison, write_model_reports
from .split import split_dataset
from .remote import config_from_environment, create_embeddings


def build_tfidf_pipeline() -> Pipeline:
    return Pipeline([
        ("vectorizer", TfidfVectorizer(
            analyzer="char", ngram_range=(2, 5), min_df=2,
            max_features=30_000, sublinear_tf=True, norm="l2",
        )),
        ("classifier", LinearSVC(class_weight="balanced", random_state=RANDOM_STATE)),
    ])


def _save_artifact(
    model: object,
    directory: Path,
    *,
    model_name: str,
    feature: str,
    classifier: str,
    metrics: dict[str, Any],
    split_strategy: str,
    dataset_version: str,
    embedding_config: dict[str, Any] | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, directory / "model.joblib", compress=3)
    config = {
        "model_name": model_name,
        "model_version": MODEL_VERSION,
        "feature": feature,
        "classifier": classifier,
        "embedding_model": (embedding_config or {}).get("embedding_model"),
        "embedding_config": embedding_config,
        "labels": list(LABELS),
        "split_strategy": split_strategy,
        "dataset_version": dataset_version,
    }
    (directory / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (directory / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (directory / "label_mapping.json").write_text(
        json.dumps({str(index): label for index, label in enumerate(LABELS)}, indent=2),
        encoding="utf-8",
    )


def run_experiments(
    dataset: LoadedDataset,
    *,
    output_root: Path,
    skip_embedding: bool = False,
    feature_filter: str = "all",
    classifier_filter: str = "all",
) -> list[dict[str, Any]]:
    reports = output_root / "reports"
    models = output_root / "models"
    cache = output_root / "cache"
    reports.mkdir(parents=True, exist_ok=True)
    quality = write_quality_report(dataset, reports)
    assert_trainable(dataset)
    split = split_dataset(dataset.frame)
    train = dataset.frame.iloc[split.train_indices].copy()
    test = dataset.frame.iloc[split.test_indices].copy()
    split_payload = {
        "strategy": split.strategy,
        "leakage_warning": split.leakage_warning,
        "train_samples": len(train),
        "test_samples": len(test),
        "train_groups": int(train["_group_id"].nunique()) if dataset.schema.group else None,
        "test_groups": int(test["_group_id"].nunique()) if dataset.schema.group else None,
        "group_overlap": sorted(set(train["_group_id"]) & set(test["_group_id"]))
        if dataset.schema.group else None,
    }
    if dataset.schema.group:
        assert not split_payload["group_overlap"]
    (reports / "split_report.json").write_text(
        json.dumps(split_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    comparison: list[dict[str, Any]] = []

    if feature_filter in {"all", "tfidf"} and classifier_filter in {"all", "linear_svc"}:
        tfidf = build_tfidf_pipeline()
        tfidf.fit(train["_text"], train["_label"])
        predictions = tfidf.predict(test["_text"])
        metrics = write_model_reports(
            model_name="tfidf_linear_svc", test_frame=test, predictions=predictions,
            reports_root=reports,
        )
        _save_artifact(
            tfidf, models / "tfidf_linear_svc", model_name="tfidf_linear_svc",
            feature="TF-IDF", classifier="LinearSVC", metrics=metrics,
            split_strategy=split.strategy, dataset_version=dataset.dataset_version,
        )
        comparison.append({"feature": "TF-IDF", "classifier": "LinearSVC", **metrics, "status": "completed", "failure_reason": ""})

    if feature_filter == "tfidf":
        write_comparison(comparison, reports)
        return comparison

    if skip_embedding:
        for classifier in ("LinearSVC", "LogisticRegression", "RandomForest"):
            comparison.append({
                "feature": "Remote Embedding", "classifier": classifier,
                "status": "skipped", "failure_reason": "--skip-embedding",
            })
        write_comparison(comparison, reports)
        return comparison

    try:
        embedding_config = config_from_environment()
        embeddings, embedding_metrics = create_embeddings(
            dataset.frame["_text"].tolist(), config=embedding_config,
            cache_path=cache / "remote_embeddings.sqlite3",
        )
        (reports / "embedding_api_metrics.json").write_text(
            json.dumps(embedding_metrics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        x_train = embeddings[split.train_indices]
        x_test = embeddings[split.test_indices]
        candidates: list[tuple[str, str, object]] = [
            ("embedding_linear_svc", "LinearSVC", LinearSVC(class_weight="balanced", random_state=RANDOM_STATE)),
            ("embedding_logistic", "LogisticRegression", LogisticRegression(
                class_weight="balanced", max_iter=5000, random_state=RANDOM_STATE,
            )),
            ("embedding_random_forest", "RandomForest", RandomForestClassifier(
                n_estimators=400, class_weight="balanced_subsample", n_jobs=2,
                random_state=RANDOM_STATE,
            )),
        ]
        for model_name, classifier_name, classifier in candidates:
            canonical_classifier = {
                "LinearSVC": "linear_svc",
                "LogisticRegression": "logistic",
                "RandomForest": "random_forest",
            }[classifier_name]
            if classifier_filter not in {"all", canonical_classifier}:
                continue
            classifier.fit(x_train, train["_label"])
            predictions = classifier.predict(x_test)
            metrics = write_model_reports(
                model_name=model_name, test_frame=test, predictions=predictions,
                reports_root=reports,
            )
            _save_artifact(
                classifier, models / model_name, model_name=model_name,
                feature="remote_embedding", classifier=classifier_name, metrics=metrics,
                split_strategy=split.strategy, dataset_version=dataset.dataset_version,
                embedding_config=embedding_config.identity(),
            )
            comparison.append({"feature": "Remote Embedding", "classifier": classifier_name, **metrics, "status": "completed", "failure_reason": ""})
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        (reports / "embedding_failure.json").write_text(
            json.dumps({"status": "failed", "reason": failure}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for classifier in ("LinearSVC", "LogisticRegression", "RandomForest"):
            comparison.append({
                "feature": "Remote Embedding", "classifier": classifier,
                "status": "failed", "failure_reason": failure,
            })
    write_comparison(comparison, reports)
    return comparison
