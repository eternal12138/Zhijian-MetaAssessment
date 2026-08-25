from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Sequence

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).parents[1] / ".matplotlib"))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

from .constants import LABELS
from .data import add_context_columns


def evaluate_predictions(y_true: Sequence[str], y_pred: Sequence[str]) -> dict[str, Any]:
    report = classification_report(
        y_true, y_pred, labels=list(LABELS), output_dict=True, zero_division=0
    )
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_precision": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
        "per_class": {
            label: {
                "precision": float(report[label]["precision"]),
                "recall": float(report[label]["recall"]),
                "f1": float(report[label]["f1-score"]),
                "support": int(report[label]["support"]),
            }
            for label in LABELS
        },
    }


def write_model_reports(
    *,
    model_name: str,
    test_frame: pd.DataFrame,
    predictions: Sequence[str],
    reports_root: Path,
) -> dict[str, Any]:
    output = reports_root / model_name
    output.mkdir(parents=True, exist_ok=True)
    y_true = test_frame["_label"].tolist()
    y_pred = list(predictions)
    metrics = evaluate_predictions(y_true, y_pred)
    (output / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    matrix = confusion_matrix(y_true, y_pred, labels=list(LABELS))
    pd.DataFrame(matrix, index=LABELS, columns=LABELS).to_csv(
        output / "confusion_matrix.csv", encoding="utf-8-sig"
    )
    figure, axis = plt.subplots(figsize=(8, 6))
    image = axis.imshow(matrix, cmap="Blues")
    figure.colorbar(image, ax=axis)
    axis.set_xticks(range(len(LABELS)), LABELS, rotation=30, ha="right")
    axis.set_yticks(range(len(LABELS)), LABELS)
    axis.set_xlabel("Predicted")
    axis.set_ylabel("True")
    axis.set_title(model_name)
    for row in range(len(LABELS)):
        for column in range(len(LABELS)):
            axis.text(column, row, int(matrix[row, column]), ha="center", va="center")
    figure.tight_layout()
    figure.savefig(output / "confusion_matrix.png", dpi=180)
    plt.close(figure)

    contextual = add_context_columns(test_frame)
    errors = contextual.loc[np.asarray(y_true) != np.asarray(y_pred)].copy()
    errors["true_label"] = np.asarray(y_true)[np.asarray(y_true) != np.asarray(y_pred)]
    errors["predicted_label"] = np.asarray(y_pred)[np.asarray(y_true) != np.asarray(y_pred)]
    error_columns: dict[str, str] = {
        "_segment_id": "segment_id",
        "_group_id": "user_id",
        "_text": "text",
        "previous_text": "previous_text",
        "next_text": "next_text",
        "true_label": "true_label",
        "predicted_label": "predicted_label",
    }
    errors[list(error_columns)].rename(columns=error_columns).to_csv(
        output / "error_cases.csv", index=False, encoding="utf-8-sig"
    )
    pairs = (
        errors.groupby(["true_label", "predicted_label"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    pairs.to_csv(output / "confusion_pairs.csv", index=False, encoding="utf-8-sig")
    return metrics


def write_comparison(rows: list[dict[str, Any]], reports_root: Path) -> None:
    columns = (
        "feature", "classifier", "accuracy", "macro_precision", "macro_recall",
        "macro_f1", "weighted_f1", "status", "failure_reason",
    )
    ordered = sorted(rows, key=lambda row: row.get("macro_f1") or -1, reverse=True)
    with (reports_root / "baseline_comparison.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)
