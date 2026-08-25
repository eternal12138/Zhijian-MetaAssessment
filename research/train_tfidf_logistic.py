"""Train and evaluate the TF-IDF + logistic-regression baseline.

Evaluation follows the precomputed participant-grouped five-fold manifest.
TF-IDF is fitted independently inside every training fold to prevent leakage.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(SCRIPT_DIR / ".matplotlib"))

import joblib
import matplotlib
import numpy as np
import pandas as pd
import sklearn
from matplotlib import pyplot as plt
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    auc,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_fscore_support,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import label_binarize


matplotlib.use("Agg")

PROJECT_ROOT = SCRIPT_DIR.parent
DATASET_PATH = Path.home() / "Desktop" / "training_dataset_v1.csv"
MANIFEST_PATH = PROJECT_ROOT / "research" / "datasets" / "split_manifest_v1.csv"
OUTPUT_DIR = PROJECT_ROOT / "research" / "results" / "tfidf_logistic_v1"

LABELS = [0, 1, 2, 3]
LABEL_NAMES = {
    0: "non_metacognitive_or_uncertain",
    1: "monitoring",
    2: "control_regulation",
    3: "evaluation",
}
RANDOM_STATE = 42
N_FOLDS = 5

MODEL_CONFIG = {
    "vectorizer": {
        "analyzer": "char",
        "ngram_range": [2, 5],
        "min_df": 2,
        "max_features": 20_000,
        "sublinear_tf": True,
        "norm": "l2",
    },
    "classifier": {
        "C": 1.0,
        "class_weight": "balanced",
        "solver": "lbfgs",
        "max_iter": 5_000,
        "random_state": RANDOM_STATE,
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char",
                    ngram_range=(2, 5),
                    min_df=2,
                    max_features=20_000,
                    sublinear_tf=True,
                    norm="l2",
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    C=1.0,
                    class_weight="balanced",
                    solver="lbfgs",
                    max_iter=5_000,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def load_and_validate_data() -> pd.DataFrame:
    dataset = pd.read_csv(DATASET_PATH, encoding="utf-8-sig", dtype={"account_id": str})
    manifest = pd.read_csv(MANIFEST_PATH, encoding="utf-8-sig", dtype={"account_id": str})

    required_dataset = {
        "sample_id",
        "account_id",
        "run_id",
        "session_id",
        "task_name",
        "cleaned_text",
        "label_train",
    }
    required_manifest = {"sample_id", "account_id", "label_train", "fold"}
    if missing := required_dataset - set(dataset.columns):
        raise ValueError(f"训练数据缺少字段: {sorted(missing)}")
    if missing := required_manifest - set(manifest.columns):
        raise ValueError(f"划分清单缺少字段: {sorted(missing)}")
    if dataset["sample_id"].duplicated().any():
        raise ValueError("训练数据存在重复sample_id")
    if manifest["sample_id"].duplicated().any():
        raise ValueError("划分清单存在重复sample_id")

    split_columns = manifest[["sample_id", "account_id", "label_train", "fold"]].rename(
        columns={"account_id": "manifest_account_id", "label_train": "manifest_label"}
    )
    data = dataset.merge(split_columns, on="sample_id", how="left", validate="one_to_one")
    if data["fold"].isna().any():
        missing_ids = data.loc[data["fold"].isna(), "sample_id"].tolist()[:10]
        raise ValueError(f"以下样本缺少fold: {missing_ids}")
    if not (data["account_id"] == data["manifest_account_id"]).all():
        raise ValueError("训练数据与划分清单的account_id不一致")
    if not (data["label_train"].astype(int) == data["manifest_label"].astype(int)).all():
        raise ValueError("训练数据与划分清单的label_train不一致")

    data["label_train"] = data["label_train"].astype(int)
    data["fold"] = data["fold"].astype(int)
    data["cleaned_text"] = data["cleaned_text"].fillna("").astype(str).str.strip()
    if (data["cleaned_text"] == "").any():
        raise ValueError("训练数据存在空清洗文本")
    if set(data["label_train"].unique()) != set(LABELS):
        raise ValueError(f"标签集合不是0/1/2/3: {sorted(data['label_train'].unique())}")
    if set(data["fold"].unique()) != set(range(1, N_FOLDS + 1)):
        raise ValueError(f"fold集合不是1-5: {sorted(data['fold'].unique())}")

    account_fold_counts = data.groupby("account_id")["fold"].nunique()
    if (account_fold_counts != 1).any():
        raise ValueError("发现同一账号被拆分到多个fold，存在数据泄漏")
    return data


def safe_multiclass_auc(y_true: np.ndarray, probabilities: np.ndarray, average: str) -> float:
    try:
        return float(
            roc_auc_score(
                y_true,
                probabilities,
                labels=LABELS,
                multi_class="ovr",
                average=average,
            )
        )
    except ValueError:
        return float("nan")


def evaluate_fold(
    fold: int,
    data: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float | int], list[dict[str, float | int | str]], Pipeline, list[str]]:
    train = data[data["fold"] != fold].copy()
    test = data[data["fold"] == fold].copy()
    train_accounts = set(train["account_id"])
    test_accounts = set(test["account_id"])
    if overlap := train_accounts & test_accounts:
        raise ValueError(f"Fold {fold}账号泄漏: {sorted(overlap)}")
    if set(train["label_train"].unique()) != set(LABELS):
        raise ValueError(f"Fold {fold}训练集缺少类别")
    if set(test["label_train"].unique()) != set(LABELS):
        raise ValueError(f"Fold {fold}测试集缺少类别，无法完整计算四分类指标")

    model = build_pipeline()
    convergence_messages: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        model.fit(train["cleaned_text"], train["label_train"])
        convergence_messages = [str(item.message) for item in caught if issubclass(item.category, ConvergenceWarning)]

    predictions = model.predict(test["cleaned_text"])
    raw_probabilities = model.predict_proba(test["cleaned_text"])
    model_classes = model.named_steps["classifier"].classes_.astype(int).tolist()
    probability_lookup = {label: raw_probabilities[:, model_classes.index(label)] for label in LABELS}
    probabilities = np.column_stack([probability_lookup[label] for label in LABELS])
    y_true = test["label_train"].to_numpy()

    fold_metrics: dict[str, float | int] = {
        "fold": fold,
        "train_samples": len(train),
        "test_samples": len(test),
        "train_accounts": len(train_accounts),
        "test_accounts": len(test_accounts),
        "feature_count": len(model.named_steps["tfidf"].get_feature_names_out()),
        "accuracy": float(accuracy_score(y_true, predictions)),
        "macro_precision": float(precision_score(y_true, predictions, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(y_true, predictions, average="macro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, predictions, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, predictions, average="weighted", zero_division=0)),
        "cross_entropy": float(log_loss(y_true, probabilities, labels=LABELS)),
        "macro_auc_ovr": safe_multiclass_auc(y_true, probabilities, "macro"),
        "weighted_auc_ovr": safe_multiclass_auc(y_true, probabilities, "weighted"),
        "convergence_warning_count": len(convergence_messages),
    }

    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        predictions,
        labels=LABELS,
        average=None,
        zero_division=0,
    )
    y_binary = label_binarize(y_true, classes=LABELS)
    class_metrics: list[dict[str, float | int | str]] = []
    for index, label in enumerate(LABELS):
        class_auc = roc_auc_score(y_binary[:, index], probabilities[:, index])
        class_metrics.append(
            {
                "fold": fold,
                "label": label,
                "label_name": LABEL_NAMES[label],
                "precision": float(precision[index]),
                "recall": float(recall[index]),
                "f1": float(f1[index]),
                "support": int(support[index]),
                "auc_ovr": float(class_auc),
            }
        )

    prediction_rows = test[
        ["sample_id", "account_id", "run_id", "session_id", "task_name", "cleaned_text", "label_train", "fold"]
    ].copy()
    prediction_rows = prediction_rows.rename(columns={"label_train": "true_label"})
    prediction_rows["predicted_label"] = predictions
    for label in LABELS:
        prediction_rows[f"probability_{label}"] = probability_lookup[label]
    prediction_rows["is_correct"] = prediction_rows["true_label"] == prediction_rows["predicted_label"]
    return prediction_rows, fold_metrics, class_metrics, model, convergence_messages


def summarize_metrics(metrics_by_fold: pd.DataFrame) -> dict[str, object]:
    metric_columns = [
        "accuracy",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "weighted_f1",
        "cross_entropy",
        "macro_auc_ovr",
        "weighted_auc_ovr",
    ]
    return {
        "primary_metric": "macro_f1",
        "fold_count": N_FOLDS,
        "metrics": {
            metric: {
                "mean": float(metrics_by_fold[metric].mean()),
                "std": float(metrics_by_fold[metric].std(ddof=1)),
                "min": float(metrics_by_fold[metric].min()),
                "max": float(metrics_by_fold[metric].max()),
            }
            for metric in metric_columns
        },
    }


def export_oof_metrics(y_true: np.ndarray, y_pred: np.ndarray, probabilities: np.ndarray) -> None:
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=LABELS, average=None, zero_division=0
    )
    y_binary = label_binarize(y_true, classes=LABELS)
    class_rows = []
    for index, label in enumerate(LABELS):
        class_rows.append(
            {
                "label": label,
                "label_name": LABEL_NAMES[label],
                "precision": float(precision[index]),
                "recall": float(recall[index]),
                "f1": float(f1[index]),
                "support": int(support[index]),
                "auc_ovr": float(roc_auc_score(y_binary[:, index], probabilities[:, index])),
            }
        )
    pd.DataFrame(class_rows).to_csv(
        OUTPUT_DIR / "metrics_by_class_oof.csv", index=False, encoding="utf-8-sig"
    )
    overall = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_precision": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
        "cross_entropy": float(log_loss(y_true, probabilities, labels=LABELS)),
        "macro_auc_ovr": safe_multiclass_auc(y_true, probabilities, "macro"),
        "weighted_auc_ovr": safe_multiclass_auc(y_true, probabilities, "weighted"),
    }
    (OUTPUT_DIR / "metrics_oof_overall.json").write_text(
        json.dumps(overall, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def plot_confusion_matrix(y_true: np.ndarray, y_pred: np.ndarray) -> None:
    matrix = confusion_matrix(y_true, y_pred, labels=LABELS)
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    image = ax.imshow(matrix, interpolation="nearest", cmap="Blues")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    ax.set(
        xticks=np.arange(len(LABELS)),
        yticks=np.arange(len(LABELS)),
        xticklabels=[f"{label}: {LABEL_NAMES[label]}" for label in LABELS],
        yticklabels=[f"{label}: {LABEL_NAMES[label]}" for label in LABELS],
        xlabel="Predicted label",
        ylabel="True label",
        title="Out-of-fold confusion matrix",
    )
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right", rotation_mode="anchor")
    threshold = matrix.max() / 2 if matrix.size else 0
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            ax.text(
                column,
                row,
                str(matrix[row, column]),
                ha="center",
                va="center",
                color="white" if matrix[row, column] > threshold else "#172033",
            )
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "confusion_matrix.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_roc(y_true: np.ndarray, probabilities: np.ndarray) -> None:
    y_binary = label_binarize(y_true, classes=LABELS)
    fig, ax = plt.subplots(figsize=(7.5, 6.2))
    for index, label in enumerate(LABELS):
        false_positive_rate, true_positive_rate, _ = roc_curve(y_binary[:, index], probabilities[:, index])
        class_auc = auc(false_positive_rate, true_positive_rate)
        ax.plot(
            false_positive_rate,
            true_positive_rate,
            linewidth=2,
            label=f"{label}: {LABEL_NAMES[label]} (AUC={class_auc:.3f})",
        )
    ax.plot([0, 1], [0, 1], linestyle="--", color="#7A8497", linewidth=1.2, label="Chance")
    ax.set(
        xlabel="False positive rate",
        ylabel="True positive rate",
        title="Out-of-fold one-vs-rest ROC curves",
        xlim=(0, 1),
        ylim=(0, 1.02),
    )
    ax.grid(alpha=0.2)
    ax.legend(loc="lower right", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "roc_curve.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def export_top_features(model: Pipeline, count: int = 30) -> None:
    vectorizer: TfidfVectorizer = model.named_steps["tfidf"]
    classifier: LogisticRegression = model.named_steps["classifier"]
    feature_names = vectorizer.get_feature_names_out()
    rows: list[dict[str, object]] = []
    for class_index, label in enumerate(classifier.classes_.astype(int)):
        coefficients = classifier.coef_[class_index]
        top_indices = np.argsort(coefficients)[-count:][::-1]
        for rank, feature_index in enumerate(top_indices, start=1):
            rows.append(
                {
                    "label": label,
                    "label_name": LABEL_NAMES[label],
                    "rank": rank,
                    "feature": feature_names[feature_index],
                    "coefficient": float(coefficients[feature_index]),
                }
            )
    pd.DataFrame(rows).to_csv(OUTPUT_DIR / "top_features_by_class.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load_and_validate_data()
    predictions_parts: list[pd.DataFrame] = []
    fold_metrics_rows: list[dict[str, float | int]] = []
    class_metrics_rows: list[dict[str, float | int | str]] = []
    convergence_by_fold: dict[str, list[str]] = {}

    for fold in range(1, N_FOLDS + 1):
        prediction_rows, fold_metrics, class_metrics, _, convergence_messages = evaluate_fold(fold, data)
        predictions_parts.append(prediction_rows)
        fold_metrics_rows.append(fold_metrics)
        class_metrics_rows.extend(class_metrics)
        convergence_by_fold[str(fold)] = convergence_messages
        print(
            f"Fold {fold}: samples={fold_metrics['test_samples']}, "
            f"accuracy={fold_metrics['accuracy']:.4f}, macro_f1={fold_metrics['macro_f1']:.4f}"
        )

    predictions = pd.concat(predictions_parts, ignore_index=True).sort_values(["fold", "sample_id"])
    if len(predictions) != len(data) or predictions["sample_id"].duplicated().any():
        raise ValueError("折外预测未完整覆盖全部样本，或存在重复预测")

    metrics_by_fold = pd.DataFrame(fold_metrics_rows)
    metrics_by_class = pd.DataFrame(class_metrics_rows)
    summary = summarize_metrics(metrics_by_fold)
    y_true = predictions["true_label"].to_numpy()
    y_pred = predictions["predicted_label"].to_numpy()
    probabilities = predictions[[f"probability_{label}" for label in LABELS]].to_numpy()

    predictions.to_csv(OUTPUT_DIR / "predictions_all_folds.csv", index=False, encoding="utf-8-sig")
    metrics_by_fold.to_csv(OUTPUT_DIR / "metrics_by_fold.csv", index=False, encoding="utf-8-sig")
    metrics_by_class.to_csv(OUTPUT_DIR / "metrics_by_class.csv", index=False, encoding="utf-8-sig")
    (OUTPUT_DIR / "metrics_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    export_oof_metrics(y_true, y_pred, probabilities)
    plot_confusion_matrix(y_true, y_pred)
    plot_roc(y_true, probabilities)

    final_model = build_pipeline()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        final_model.fit(data["cleaned_text"], data["label_train"])
        convergence_by_fold["full_dataset"] = [
            str(item.message) for item in caught if issubclass(item.category, ConvergenceWarning)
        ]
    joblib.dump(final_model, OUTPUT_DIR / "tfidf_logistic_v1.joblib")
    export_top_features(final_model)

    metadata = {
        "model_name": "tfidf_logistic_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation": "5-fold grouped out-of-fold evaluation",
        "group_key": "account_id",
        "sample_count": len(data),
        "account_count": int(data["account_id"].nunique()),
        "label_counts": {str(key): int(value) for key, value in data["label_train"].value_counts().sort_index().items()},
        "data_sha256": sha256_file(DATASET_PATH),
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        "config": MODEL_CONFIG,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "leakage_checks": {
            "each_account_in_one_fold": True,
            "tfidf_refit_per_fold": True,
            "all_samples_have_one_oof_prediction": True,
        },
        "convergence_warnings": convergence_by_fold,
    }
    (OUTPUT_DIR / "model_config.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Results: {OUTPUT_DIR}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Training failed: {exc}", file=sys.stderr)
        raise
