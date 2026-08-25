"""Train a versioned fully-connected classifier on cached Qwen embeddings."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd
import sklearn

SCRIPT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(SCRIPT_DIR / ".matplotlib"))
matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    accuracy_score,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_fscore_support,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.neural_network import MLPClassifier  # noqa: E402
from sklearn.preprocessing import StandardScaler, label_binarize  # noqa: E402


PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_EMBEDDING_DIR = PROJECT_ROOT / "research" / "embeddings" / "qwen3_7_text_embedding_v1"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "research" / "results" / "qwen_fc_v1"
LABELS = np.asarray([0, 1, 2, 3], dtype=np.int64)
LABEL_NAMES = {
    0: "non_metacognitive_or_uncertain",
    1: "monitoring",
    2: "control_regulation",
    3: "evaluation",
}
RANDOM_STATE = 42


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="训练Qwen向量全连接四分类模型")
    parser.add_argument("--embedding-dir", type=Path, default=DEFAULT_EMBEDDING_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--hidden-units", type=int, default=128)
    parser.add_argument("--max-epochs", type=int, default=200)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--alpha", type=float, default=0.0001)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_embeddings(directory: Path) -> tuple[np.ndarray, pd.DataFrame, dict]:
    npz_path = directory / "embeddings.npz"
    manifest_path = directory / "embedding_manifest.csv"
    config_path = directory / "embedding_config.json"
    with np.load(npz_path, allow_pickle=False) as archive:
        embeddings = archive["embeddings"].astype(np.float32)
        sample_ids = archive["sample_ids"].astype(str)
        account_ids = archive["account_ids"].astype(str)
        labels = archive["labels"].astype(np.int64)
        folds = archive["folds"].astype(np.int64)
    manifest = pd.read_csv(manifest_path, encoding="utf-8-sig", dtype={"account_id": str})
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if embeddings.ndim != 2 or embeddings.shape[0] != len(manifest):
        raise ValueError("向量矩阵与清单行数不一致")
    if embeddings.shape[1] != int(config["dimensions"]):
        raise ValueError("向量矩阵维度与配置不一致")
    if not np.array_equal(sample_ids, manifest["sample_id"].astype(str).to_numpy()):
        raise ValueError("向量sample_id顺序与清单不一致")
    if not np.array_equal(account_ids, manifest["account_id"].astype(str).to_numpy()):
        raise ValueError("向量account_id顺序与清单不一致")
    if not np.array_equal(labels, manifest["label_train"].astype(np.int64).to_numpy()):
        raise ValueError("向量标签与清单不一致")
    if not np.array_equal(folds, manifest["fold"].astype(np.int64).to_numpy()):
        raise ValueError("向量fold与清单不一致")
    if set(np.unique(labels)) != set(LABELS.tolist()) or set(np.unique(folds)) != {1, 2, 3, 4, 5}:
        raise ValueError("标签或fold集合不完整")
    if not np.all(np.isfinite(embeddings)):
        raise ValueError("向量包含非有限数值")
    norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-4):
        raise ValueError("输入向量未完成L2归一化")
    return embeddings, manifest, config


def sample_weights(labels: np.ndarray) -> np.ndarray:
    counts = np.bincount(labels, minlength=len(LABELS)).astype(np.float64)
    if np.any(counts <= 0):
        raise ValueError("训练集缺少类别，无法计算类别权重")
    class_weights = np.sqrt(len(labels) / (len(LABELS) * counts))
    class_weights /= class_weights.mean()
    return class_weights[labels].astype(np.float64)


def build_classifier(args: argparse.Namespace, seed: int) -> MLPClassifier:
    return MLPClassifier(
        hidden_layer_sizes=(args.hidden_units,),
        activation="relu",
        solver="adam",
        alpha=args.alpha,
        batch_size=args.batch_size,
        learning_rate_init=args.learning_rate,
        max_iter=1,
        shuffle=True,
        random_state=seed,
        warm_start=True,
    )


def fit_with_early_stopping(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_validation: np.ndarray,
    y_validation: np.ndarray,
    args: argparse.Namespace,
    seed: int,
) -> tuple[MLPClassifier, int, list[dict[str, float | int]]]:
    model = build_classifier(args, seed)
    weights = sample_weights(y_train)
    best_model: MLPClassifier | None = None
    best_epoch = 0
    best_f1 = -1.0
    stale_epochs = 0
    history: list[dict[str, float | int]] = []
    for epoch in range(1, args.max_epochs + 1):
        model.partial_fit(x_train, y_train, classes=LABELS, sample_weight=weights)
        prediction = model.predict(x_validation)
        score = float(f1_score(y_validation, prediction, labels=LABELS, average="macro", zero_division=0))
        history.append({"epoch": epoch, "validation_macro_f1": score, "loss": float(model.loss_)})
        if score > best_f1 + 1e-8:
            best_f1 = score
            best_epoch = epoch
            best_model = copy.deepcopy(model)
            stale_epochs = 0
        else:
            stale_epochs += 1
        if stale_epochs >= args.patience:
            break
    if best_model is None:
        raise RuntimeError("训练未产生有效模型")
    return best_model, best_epoch, history


def probability_matrix(model: MLPClassifier, features: np.ndarray) -> np.ndarray:
    raw = model.predict_proba(features)
    classes = model.classes_.astype(int).tolist()
    return np.column_stack([raw[:, classes.index(label)] for label in LABELS])


def fit_fixed_epochs(
    features: np.ndarray,
    labels: np.ndarray,
    args: argparse.Namespace,
    seed: int,
    epochs: int,
) -> MLPClassifier:
    model = build_classifier(args, seed)
    weights = sample_weights(labels)
    for _ in range(max(1, epochs)):
        model.partial_fit(features, labels, classes=LABELS, sample_weight=weights)
    return model


def fold_metrics(y_true: np.ndarray, y_pred: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_precision": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
        "cross_entropy": float(log_loss(y_true, probabilities, labels=LABELS)),
        "macro_auc_ovr": float(roc_auc_score(y_true, probabilities, labels=LABELS, multi_class="ovr", average="macro")),
        "weighted_auc_ovr": float(roc_auc_score(y_true, probabilities, labels=LABELS, multi_class="ovr", average="weighted")),
    }


def save_plots(output_dir: Path, y_true: np.ndarray, y_pred: np.ndarray, probabilities: np.ndarray) -> None:
    matrix = confusion_matrix(y_true, y_pred, labels=LABELS)
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    image = ax.imshow(matrix, cmap="Blues")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    ticks = [f"{label}: {LABEL_NAMES[int(label)]}" for label in LABELS]
    ax.set(xticks=np.arange(4), yticks=np.arange(4), xticklabels=ticks, yticklabels=ticks,
           xlabel="Predicted label", ylabel="True label", title="Qwen FC out-of-fold confusion matrix")
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right")
    threshold = matrix.max() / 2
    for row in range(4):
        for column in range(4):
            ax.text(column, row, str(matrix[row, column]), ha="center", va="center",
                    color="white" if matrix[row, column] > threshold else "#172033")
    fig.tight_layout()
    fig.savefig(output_dir / "confusion_matrix.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    y_binary = label_binarize(y_true, classes=LABELS)
    fig, ax = plt.subplots(figsize=(7.5, 6.2))
    for index, label in enumerate(LABELS):
        fpr, tpr, _ = roc_curve(y_binary[:, index], probabilities[:, index])
        area = roc_auc_score(y_binary[:, index], probabilities[:, index])
        ax.plot(fpr, tpr, linewidth=2, label=f"{label}: {LABEL_NAMES[int(label)]} (AUC={area:.3f})")
    ax.plot([0, 1], [0, 1], "--", color="#7A8497", label="Chance")
    ax.set(xlabel="False positive rate", ylabel="True positive rate",
           title="Qwen FC out-of-fold one-vs-rest ROC curves", xlim=(0, 1), ylim=(0, 1.02))
    ax.grid(alpha=0.2)
    ax.legend(loc="lower right", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(output_dir / "roc_curve.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    embeddings, manifest, embedding_config = load_embeddings(args.embedding_dir)
    labels = manifest["label_train"].astype(np.int64).to_numpy()
    folds = manifest["fold"].astype(np.int64).to_numpy()
    accounts = manifest["account_id"].astype(str).to_numpy()
    prediction_parts: list[pd.DataFrame] = []
    metric_rows: list[dict] = []
    history_rows: list[dict] = []
    best_epochs: list[int] = []

    for test_fold in range(1, 6):
        validation_fold = test_fold % 5 + 1
        selection_train_mask = (folds != test_fold) & (folds != validation_fold)
        validation_mask = folds == validation_fold
        test_mask = folds == test_fold
        outer_train_mask = folds != test_fold
        train_accounts = set(accounts[selection_train_mask])
        validation_accounts = set(accounts[validation_mask])
        test_accounts = set(accounts[test_mask])
        if train_accounts & validation_accounts or train_accounts & test_accounts or validation_accounts & test_accounts:
            raise ValueError(f"Fold {test_fold}发现账号泄漏")

        selection_scaler = StandardScaler().fit(embeddings[selection_train_mask])
        x_selection_train = selection_scaler.transform(embeddings[selection_train_mask]).astype(np.float32)
        x_validation = selection_scaler.transform(embeddings[validation_mask]).astype(np.float32)
        _, best_epoch, history = fit_with_early_stopping(
            x_selection_train, labels[selection_train_mask],
            x_validation, labels[validation_mask], args, RANDOM_STATE + test_fold
        )
        # Refit with the selected epoch count on all four non-test folds. The
        # test fold remains untouched while outer-fold training size stays
        # comparable with the TF-IDF baseline.
        scaler = StandardScaler().fit(embeddings[outer_train_mask])
        x_outer_train = scaler.transform(embeddings[outer_train_mask]).astype(np.float32)
        x_test = scaler.transform(embeddings[test_mask]).astype(np.float32)
        model = fit_fixed_epochs(
            x_outer_train, labels[outer_train_mask], args, RANDOM_STATE + 100 + test_fold, best_epoch
        )
        best_epochs.append(best_epoch)
        prediction = model.predict(x_test).astype(int)
        probabilities = probability_matrix(model, x_test)
        metrics = fold_metrics(labels[test_mask], prediction, probabilities)
        metric_rows.append({
            "fold": test_fold,
            "validation_fold": validation_fold,
            "train_samples": int(outer_train_mask.sum()),
            "selection_train_samples": int(selection_train_mask.sum()),
            "validation_samples": int(validation_mask.sum()),
            "test_samples": int(test_mask.sum()),
            "best_epoch": best_epoch,
            **metrics,
        })
        for row in history:
            history_rows.append({"fold": test_fold, **row})
        fold_predictions = manifest.loc[test_mask, [
            "sample_id", "account_id", "label_train", "fold"
        ]].copy().rename(columns={"label_train": "true_label"})
        fold_predictions["predicted_label"] = prediction
        for index, label in enumerate(LABELS):
            fold_predictions[f"probability_{label}"] = probabilities[:, index]
        fold_predictions["is_correct"] = fold_predictions["true_label"] == fold_predictions["predicted_label"]
        prediction_parts.append(fold_predictions)
        joblib.dump(
            {"scaler": scaler, "classifier": model, "embedding_config": embedding_config},
            args.output_dir / f"fold_{test_fold}_best.joblib",
        )
        print(f"Fold {test_fold}: best_epoch={best_epoch}, macro_f1={metrics['macro_f1']:.4f}")

    predictions = pd.concat(prediction_parts, ignore_index=True).sort_values(["fold", "sample_id"])
    if len(predictions) != len(manifest) or predictions["sample_id"].duplicated().any():
        raise ValueError("折外预测未完整覆盖全部样本")
    y_true = predictions["true_label"].to_numpy(dtype=int)
    y_pred = predictions["predicted_label"].to_numpy(dtype=int)
    probabilities = predictions[[f"probability_{label}" for label in LABELS]].to_numpy()
    metrics_by_fold = pd.DataFrame(metric_rows)
    summary = {
        "primary_metric": "macro_f1",
        "fold_count": 5,
        "metrics": {
            column: {
                "mean": float(metrics_by_fold[column].mean()),
                "std": float(metrics_by_fold[column].std(ddof=1)),
            }
            for column in ["accuracy", "macro_precision", "macro_recall", "macro_f1", "weighted_f1",
                           "cross_entropy", "macro_auc_ovr", "weighted_auc_ovr"]
        },
        "oof_overall": fold_metrics(y_true, y_pred, probabilities),
    }
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=LABELS, average=None, zero_division=0
    )
    y_binary = label_binarize(y_true, classes=LABELS)
    class_rows = [
        {
            "label": int(label), "label_name": LABEL_NAMES[int(label)],
            "precision": float(precision[index]), "recall": float(recall[index]),
            "f1": float(f1[index]), "support": int(support[index]),
            "auc_ovr": float(roc_auc_score(y_binary[:, index], probabilities[:, index])),
        }
        for index, label in enumerate(LABELS)
    ]
    predictions.to_csv(args.output_dir / "predictions_all_folds.csv", index=False, encoding="utf-8-sig")
    metrics_by_fold.to_csv(args.output_dir / "metrics_by_fold.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(class_rows).to_csv(args.output_dir / "metrics_by_class_oof.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(history_rows).to_csv(args.output_dir / "training_history.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "metrics_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_plots(args.output_dir, y_true, y_pred, probabilities)

    final_scaler = StandardScaler().fit(embeddings)
    final_features = final_scaler.transform(embeddings).astype(np.float32)
    final_model = build_classifier(args, RANDOM_STATE)
    full_weights = sample_weights(labels)
    final_epochs = max(1, int(np.median(best_epochs)))
    for _ in range(final_epochs):
        final_model.partial_fit(final_features, labels, classes=LABELS, sample_weight=full_weights)
    joblib.dump(
        {"scaler": final_scaler, "classifier": final_model, "embedding_config": embedding_config},
        args.output_dir / "qwen_fc_full_model.joblib",
    )
    metadata = {
        "model_name": "qwen_fc_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "embedding_model": embedding_config["model"],
        "embedding_dimensions": embedding_config["dimensions"],
        "embedding_artifact_sha256": sha256_file(args.embedding_dir / "embeddings.npz"),
        "sample_count": len(manifest),
        "account_count": int(manifest["account_id"].nunique()),
        "architecture": [int(embedding_config["dimensions"]), args.hidden_units, 4],
        "activation": "relu",
        "optimizer": "adam",
        "alpha": args.alpha,
        "learning_rate": args.learning_rate,
        "batch_size": args.batch_size,
        "max_epochs": args.max_epochs,
        "patience": args.patience,
        "final_training_epochs": final_epochs,
        "class_weighting": "sqrt_inverse_frequency_per_training_fold",
        "split": "outer_test_fold + rotating_group_validation_fold + remaining_three_train_folds",
        "versions": {
            "python": platform.python_version(), "numpy": np.__version__,
            "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
        },
    }
    (args.output_dir / "model_config.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Qwen全连接训练失败：{error}", file=sys.stderr)
        raise
