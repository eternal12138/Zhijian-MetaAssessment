"""元认知文本三分类的七组可比较训练方法。

本文件集中保存研究管理页面可创建的四种训练方案：

1. TF-IDF + LinearSVC
2. 远程 Embedding + LinearSVC
3. 远程 Embedding + LogisticRegression
4. 远程 Embedding + RandomForest

职责边界：
- 本文件接收已经清洗、冻结并完成标签过滤的数据或向量；
- 本文件执行五折交叉验证、生成折外预测、计算真实评估指标，并在全部
  数据上重新拟合最终分类器；
- 远程 Embedding 的 API 调用、向量缓存、训练任务状态和模型产物保存不在
  本文件中处理，仍由上层训练服务负责。

评估原则：每条样本只在其未参与训练的测试折中产生一次预测。最终在全部
数据上拟合的分类器仅用于部署，不参与页面显示的交叉验证指标，避免把训练
集自测结果误当作泛化性能。
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
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
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import label_binarize
from sklearn.svm import LinearSVC


TrainingProgressCallback = Callable[[str, int, int], None]


def _report_training_progress(
    callback: TrainingProgressCallback | None,
    event: str,
    fold: int,
    total_folds: int = 5,
) -> None:
    """Report coarse training milestones without coupling model code to the DB."""
    if callback is not None:
        callback(event, fold, total_folds)
from sklearn.utils.class_weight import compute_sample_weight

from app.training.hyperparameters import default_hyperparameters


# 新模型只训练三种元认知类别；标签 0（非元认知）在数据准备阶段被排除。
TRAINING_LABELS = (1, 2, 3)
TRAINING_LABEL_NAMES = {1: "监控", 2: "控制/调控", 3: "评估"}
TRAINING_LABEL_INDEX = {label: index for index, label in enumerate(TRAINING_LABELS)}


def _validation_splitter(labels: np.ndarray, groups: np.ndarray):
    """根据被试 ID 的完整性选择更严格的五折划分方式。"""
    if set(labels.tolist()) != set(TRAINING_LABELS):
        raise ValueError("训练数据必须同时包含标签1监控、2调控、3评估")
    has_participant_ids = all(str(value).strip() for value in groups.tolist())
    if has_participant_ids:
        if len(set(groups.tolist())) < 5:
            raise ValueError("至少需要 5 名不同被试才能进行分组五折评估")
        return StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42), True
    class_counts = {label: int((labels == label).sum()) for label in TRAINING_LABELS}
    sparse = [label for label, count in class_counts.items() if count < 5]
    if sparse:
        raise ValueError(f"每类至少需要 5 条样本才能进行分层五折评估，当前不足的标签：{sparse}")
    return StratifiedKFold(n_splits=5, shuffle=True, random_state=42), False


def _validation_splits(splitter, values, labels: np.ndarray, groups: np.ndarray, grouped: bool):
    if grouped:
        return splitter.split(values, labels, groups)
    return splitter.split(values, labels)


def _label_distribution(labels: np.ndarray, indexes: np.ndarray) -> dict[str, int]:
    selected = labels[indexes]
    return {str(label): int((selected == label).sum()) for label in TRAINING_LABELS}


def _specificities(labels: np.ndarray, predictions: np.ndarray) -> list[float]:
    """按 one-vs-rest 方式计算每一类的特异性。"""
    matrix = confusion_matrix(labels, predictions, labels=list(TRAINING_LABELS))
    total = int(matrix.sum())
    values: list[float] = []
    for index in range(len(TRAINING_LABELS)):
        true_positive = int(matrix[index, index])
        false_positive = int(matrix[:, index].sum()) - true_positive
        false_negative = int(matrix[index, :].sum()) - true_positive
        true_negative = total - true_positive - false_positive - false_negative
        denominator = true_negative + false_positive
        values.append(float(true_negative / denominator) if denominator else 0.0)
    return values


def _classification_metrics(
    labels: np.ndarray,
    predictions: np.ndarray,
    fold_metrics: list[dict],
    probabilities: np.ndarray | None = None,
    scores: np.ndarray | None = None,
    score_type: str | None = None,
) -> dict[str, Any]:
    """使用全部折外预测计算统一指标、混淆矩阵和 ROC 数据。"""
    per_precision, per_recall, per_f1, per_support = precision_recall_fscore_support(
        labels, predictions, labels=list(TRAINING_LABELS), zero_division=0
    )
    per_specificity = _specificities(labels, predictions)
    metrics: dict[str, Any] = {
        "accuracy": float(accuracy_score(labels, predictions)),
        "macro_precision": float(precision_score(labels, predictions, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(labels, predictions, average="macro", zero_division=0)),
        "weighted_precision": float(precision_score(labels, predictions, average="weighted", zero_division=0)),
        "weighted_recall": float(recall_score(labels, predictions, average="weighted", zero_division=0)),
        "macro_specificity": float(np.mean(per_specificity)),
        "macro_f1": float(f1_score(labels, predictions, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(labels, predictions, average="weighted", zero_division=0)),
        # This private field is consumed by the training service to create a
        # bounded error-analysis snapshot, then removed before metrics.json is
        # written.  It keeps text/participant metadata out of model code.
        "_oof_predictions": [int(value) for value in predictions.tolist()],
        "folds": fold_metrics,
        "confusion_matrix": confusion_matrix(
            labels, predictions, labels=list(TRAINING_LABELS)
        ).astype(int).tolist(),
        "per_class": {
            str(label): {
                "precision": float(per_precision[index]),
                "recall": float(per_recall[index]),
                "specificity": per_specificity[index],
                "f1": float(per_f1[index]),
                "support": int(per_support[index]),
            }
            for index, label in enumerate(TRAINING_LABELS)
        },
    }

    # LinearSVC 使用 decision_function，概率模型使用 predict_proba；两者都可
    # 用于 ROC 排序，但只有真实概率才能计算交叉熵。
    if scores is not None:
        binary = label_binarize(labels, classes=list(TRAINING_LABELS))
        per_class_curves: dict[str, dict[str, Any]] = {}
        all_fpr: list[np.ndarray] = []
        interpolated_tpr: list[np.ndarray] = []
        for index, label in enumerate(TRAINING_LABELS):
            fpr, tpr, _ = roc_curve(binary[:, index], scores[:, index])
            if len(fpr) > 201:
                indexes = np.unique(np.linspace(0, len(fpr) - 1, 201, dtype=int))
                fpr = fpr[indexes]
                tpr = tpr[indexes]
            per_class_curves[str(label)] = {
                "fpr": [float(value) for value in fpr],
                "tpr": [float(value) for value in tpr],
                "auc": float(roc_auc_score(binary[:, index], scores[:, index])),
            }
            all_fpr.append(fpr)
        macro_fpr = np.unique(np.concatenate(all_fpr))
        for label in TRAINING_LABELS:
            curve = per_class_curves[str(label)]
            interpolated_tpr.append(np.interp(macro_fpr, curve["fpr"], curve["tpr"]))
        macro_tpr = np.mean(interpolated_tpr, axis=0)
        if len(macro_fpr) > 201:
            indexes = np.unique(np.linspace(0, len(macro_fpr) - 1, 201, dtype=int))
            macro_fpr = macro_fpr[indexes]
            macro_tpr = macro_tpr[indexes]
        macro_auc = float(np.mean([
            per_class_curves[str(label)]["auc"] for label in TRAINING_LABELS
        ]))
        metrics["macro_auc_ovr"] = macro_auc
        metrics["roc_curves"] = {
            "macro": {
                "fpr": [float(value) for value in macro_fpr],
                "tpr": [float(value) for value in macro_tpr],
                "auc": macro_auc,
            },
            **per_class_curves,
        }
        metrics["roc_evaluation"] = {
            "source": "cross_validated_out_of_fold",
            "aggregation": "pooled_out_of_fold_predictions",
            "strategy": "one_vs_rest",
            "score_type": score_type or ("predict_proba" if probabilities is not None else "model_score"),
            "sample_count": int(len(labels)),
            "every_sample_evaluated_once": True,
            "external_holdout": False,
        }
    if probabilities is not None:
        metrics["cross_entropy"] = float(log_loss(
            labels, probabilities, labels=list(TRAINING_LABELS)
        ))
    return metrics


def _fold_row(
    fold: int,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    labels: np.ndarray,
    predictions: np.ndarray,
    train_predictions: np.ndarray,
    scores: np.ndarray | None = None,
    probabilities: np.ndarray | None = None,
    groups: np.ndarray | None = None,
    grouped: bool = False,
) -> dict:
    """记录一折中真实训练集、测试集规模、分布和性能。"""
    weighted_precision = float(precision_score(
        labels[test_idx], predictions, average="weighted", zero_division=0
    ))
    weighted_recall = float(recall_score(
        labels[test_idx], predictions, average="weighted", zero_division=0
    ))
    row: dict[str, Any] = {
        "fold": fold,
        "train_sample_count": int(len(train_idx)),
        "sample_count": int(len(test_idx)),
        "train_label_distribution": _label_distribution(labels, train_idx),
        "test_label_distribution": _label_distribution(labels, test_idx),
        "train_accuracy": float(accuracy_score(labels[train_idx], train_predictions)),
        "train_macro_f1": float(f1_score(
            labels[train_idx], train_predictions, average="macro", zero_division=0
        )),
        "macro_f1": float(f1_score(labels[test_idx], predictions, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(labels[test_idx], predictions, average="weighted", zero_division=0)),
        "macro_precision": float(precision_score(
            labels[test_idx], predictions, average="macro", zero_division=0
        )),
        "macro_recall": float(recall_score(
            labels[test_idx], predictions, average="macro", zero_division=0
        )),
        "weighted_precision": weighted_precision,
        "weighted_recall": weighted_recall,
        "macro_specificity": float(np.mean(_specificities(labels[test_idx], predictions))),
        "accuracy": float(accuracy_score(labels[test_idx], predictions)),
    }
    if grouped and groups is not None:
        train_groups = {str(value) for value in groups[train_idx]}
        test_groups = {str(value) for value in groups[test_idx]}
        overlap = train_groups & test_groups
        row.update({
            "train_participant_count": len(train_groups),
            "test_participant_count": len(test_groups),
            "participant_overlap_count": len(overlap),
            "subject_disjoint_verified": not overlap,
        })
    else:
        row.update({
            "train_participant_count": None,
            "test_participant_count": None,
            "participant_overlap_count": None,
            "subject_disjoint_verified": None,
        })
    if scores is not None:
        binary = label_binarize(labels[test_idx], classes=list(TRAINING_LABELS))
        per_class_auc: dict[str, float | None] = {}
        for index, label in enumerate(TRAINING_LABELS):
            target = binary[:, index]
            per_class_auc[str(label)] = (
                float(roc_auc_score(target, scores[:, index]))
                if len(np.unique(target)) == 2 else None
            )
        valid_auc = [value for value in per_class_auc.values() if value is not None]
        row["per_class_auc"] = per_class_auc
        row["macro_auc_ovr"] = float(np.mean(valid_auc)) if len(valid_auc) == len(TRAINING_LABELS) else None
    if probabilities is not None:
        row["cross_entropy"] = float(log_loss(
            labels[test_idx], probabilities, labels=list(TRAINING_LABELS)
        ))
    return row


# ---------------------------------------------------------------------------
# 方案一：TF-IDF + LinearSVC
# ---------------------------------------------------------------------------

def build_tfidf_linear_svc(
    random_state: int = 42, hyperparameters: dict[str, Any] | None = None,
) -> Pipeline:
    """构建适合中文短文本和 2C4G 生产环境的轻量分类管线。"""
    params = {**default_hyperparameters("tfidf_linear_svc"), **(hyperparameters or {})}
    class_weight = None if params["class_weight"] == "none" else params["class_weight"]
    return Pipeline([
        ("vectorizer", TfidfVectorizer(
            # 字符 n-gram 对中文无需额外分词器，也能覆盖局部表达模式。
            analyzer="char",
            ngram_range=(2, 5),
            min_df=2,
            max_features=30_000,
            sublinear_tf=True,
            norm="l2",
        )),
        ("classifier", LinearSVC(
            C=float(params["C"]), max_iter=int(params["max_iter"]),
            class_weight=class_weight, random_state=random_state,
        )),
    ])


def train_tfidf_linear_svc(
    samples: list[tuple[str, str, int]], labels: np.ndarray, groups: np.ndarray,
    hyperparameters: dict[str, Any] | None = None,
    progress_callback: TrainingProgressCallback | None = None,
):
    """五折训练 TF-IDF + LinearSVC，并返回全量重拟合的最终管线。"""
    splitter, grouped = _validation_splitter(labels, groups)
    texts = np.asarray([item[1] for item in samples], dtype=object)
    predictions = np.zeros(len(labels), dtype=np.int64)
    scores = np.zeros((len(labels), len(TRAINING_LABELS)), dtype=np.float64)
    folds: list[dict] = []
    for fold, (train_idx, test_idx) in enumerate(
        _validation_splits(splitter, texts, labels, groups, grouped), start=1
    ):
        _report_training_progress(progress_callback, "fold_started", fold)
        if grouped:
            assert set(groups[train_idx]).isdisjoint(set(groups[test_idx])), "subject leakage detected"
        pipeline = build_tfidf_linear_svc(42 + fold, hyperparameters)
        pipeline.fit(texts[train_idx].tolist(), labels[train_idx])
        train_predictions = pipeline.predict(texts[train_idx].tolist())
        fold_predictions = pipeline.predict(texts[test_idx].tolist())
        predictions[test_idx] = fold_predictions
        fold_scores = pipeline.decision_function(texts[test_idx].tolist())
        scores[test_idx] = fold_scores
        folds.append(_fold_row(
            fold, train_idx, test_idx, labels, fold_predictions, train_predictions,
            scores=fold_scores, groups=groups, grouped=grouped,
        ))
        _report_training_progress(progress_callback, "fold_completed", fold)
    _report_training_progress(progress_callback, "refit_started", 5)
    final_pipeline = build_tfidf_linear_svc(hyperparameters=hyperparameters)
    final_pipeline.fit(texts.tolist(), labels)
    _report_training_progress(progress_callback, "refit_completed", 5)
    metrics = _classification_metrics(
        labels, predictions, folds, scores=scores, score_type="decision_function",
    )
    return None, final_pipeline, metrics


# ---------------------------------------------------------------------------
# 方案二至七：远程 Embedding + 六种分类器
# ---------------------------------------------------------------------------

def build_remote_embedding_linear_svc(
    random_state: int = 42, hyperparameters: dict[str, Any] | None = None,
) -> LinearSVC:
    """方案二：语义向量后接带类别平衡权重的线性 SVM。"""
    params = {**default_hyperparameters("embedding_linear_svc"), **(hyperparameters or {})}
    class_weight = None if params["class_weight"] == "none" else params["class_weight"]
    return LinearSVC(
        C=float(params["C"]), max_iter=int(params["max_iter"]),
        class_weight=class_weight, random_state=random_state,
    )


def build_remote_embedding_logistic(
    random_state: int = 42, hyperparameters: dict[str, Any] | None = None,
) -> LogisticRegression:
    """方案三：语义向量后接可输出分类概率的逻辑回归。"""
    params = {**default_hyperparameters("embedding_logistic"), **(hyperparameters or {})}
    class_weight = None if params["class_weight"] == "none" else params["class_weight"]
    return LogisticRegression(
        C=float(params["C"]), class_weight=class_weight,
        max_iter=int(params["max_iter"]), random_state=random_state,
    )


def build_remote_embedding_random_forest(
    random_state: int = 42, hyperparameters: dict[str, Any] | None = None,
) -> RandomForestClassifier:
    """方案四：语义向量后接随机森林，作为非线性分类器对照。"""
    params = {**default_hyperparameters("embedding_random_forest"), **(hyperparameters or {})}
    return RandomForestClassifier(
        n_estimators=int(params["n_estimators"]),
        max_depth=None if int(params["max_depth"]) == 0 else int(params["max_depth"]),
        min_samples_leaf=int(params["min_samples_leaf"]),
        max_features=None if params["max_features"] == "all" else params["max_features"],
        class_weight="balanced_subsample",
        n_jobs=2,
        random_state=random_state,
    )


class OffsetLabelClassifier(ClassifierMixin, BaseEstimator):
    """Adapt estimators requiring zero-based multiclass labels to labels 1/2/3."""

    def __init__(self, estimator, balanced_sample_weight: bool = True):
        self.estimator = estimator
        self.balanced_sample_weight = balanced_sample_weight

    def fit(self, features, labels):
        labels_array = np.asarray(labels, dtype=np.int64)
        if set(labels_array.tolist()) - set(TRAINING_LABELS):
            raise ValueError("提升树分类器仅支持标签1/2/3")
        weights = compute_sample_weight("balanced", labels_array) if self.balanced_sample_weight else None
        self.estimator.fit(features, labels_array - 1, sample_weight=weights)
        self.classes_ = np.asarray(TRAINING_LABELS, dtype=np.int64)
        return self

    def predict(self, features):
        return np.asarray(self.estimator.predict(features), dtype=np.int64).reshape(-1) + 1

    def predict_proba(self, features):
        return np.asarray(self.estimator.predict_proba(features), dtype=np.float64)


def build_remote_embedding_xgboost(
    random_state: int = 42, hyperparameters: dict[str, Any] | None = None,
):
    """方案五：远程 Embedding + XGBoost，多分类标签在包装器内安全偏移。"""
    try:
        from xgboost import XGBClassifier
    except ImportError as error:
        raise RuntimeError("训练环境缺少 xgboost，请安装 requirements.txt 中的训练依赖") from error
    params = {**default_hyperparameters("embedding_xgboost"), **(hyperparameters or {})}
    estimator = XGBClassifier(
        **params, objective="multi:softprob", num_class=3,
        eval_metric="mlogloss", tree_method="hist", n_jobs=2,
        random_state=random_state, verbosity=0,
    )
    return OffsetLabelClassifier(estimator)


def build_remote_embedding_lightgbm(
    random_state: int = 42, hyperparameters: dict[str, Any] | None = None,
):
    """方案六：远程 Embedding + LightGBM。"""
    try:
        from lightgbm import LGBMClassifier
    except ImportError as error:
        raise RuntimeError("训练环境缺少 lightgbm，请安装 requirements.txt 中的训练依赖") from error
    params = {**default_hyperparameters("embedding_lightgbm"), **(hyperparameters or {})}
    return LGBMClassifier(
        **params, objective="multiclass", class_weight="balanced",
        subsample_freq=1, n_jobs=2, random_state=random_state, verbosity=-1,
    )


def build_remote_embedding_catboost(
    random_state: int = 42, hyperparameters: dict[str, Any] | None = None,
):
    """方案七：远程 Embedding + CatBoost。"""
    try:
        from catboost import CatBoostClassifier
    except ImportError as error:
        raise RuntimeError("训练环境缺少 catboost，请安装 requirements.txt 中的训练依赖") from error
    params = {**default_hyperparameters("embedding_catboost"), **(hyperparameters or {})}
    estimator = CatBoostClassifier(
        **params, loss_function="MultiClass", auto_class_weights="Balanced",
        thread_count=2, random_seed=random_state, verbose=False,
        allow_writing_files=False,
    )
    return OffsetLabelClassifier(estimator, balanced_sample_weight=False)


def _build_embedding_classifier(
    classifier_type: str, random_state: int,
    hyperparameters: dict[str, Any] | None = None,
):
    builders = {
        "linear_svc": build_remote_embedding_linear_svc,
        "logistic": build_remote_embedding_logistic,
        "random_forest": build_remote_embedding_random_forest,
        "xgboost": build_remote_embedding_xgboost,
        "lightgbm": build_remote_embedding_lightgbm,
        "catboost": build_remote_embedding_catboost,
    }
    builder = builders.get(classifier_type)
    if builder is None:
        raise ValueError(f"不支持的分类器：{classifier_type}")
    return builder(random_state, hyperparameters)


def train_remote_embedding_classifier(
    features: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    classifier_type: str,
    hyperparameters: dict[str, Any] | None = None,
    progress_callback: TrainingProgressCallback | None = None,
):
    """训练远程 Embedding + 指定分类器的统一五折流程。

    ``features`` 必须是上层服务一次性取得并缓存的 Dense Embedding，函数内
    不发起网络请求，也不会重复加载或生成向量。
    """
    splitter, grouped = _validation_splitter(labels, groups)
    predictions = np.zeros(len(labels), dtype=np.int64)
    is_probability_model = classifier_type != "linear_svc"
    probabilities = (
        np.zeros((len(labels), len(TRAINING_LABELS)), dtype=np.float64)
        if is_probability_model else None
    )
    scores = np.zeros((len(labels), len(TRAINING_LABELS)), dtype=np.float64)
    folds: list[dict] = []
    for fold, (train_idx, test_idx) in enumerate(
        _validation_splits(splitter, features, labels, groups, grouped), start=1
    ):
        _report_training_progress(progress_callback, "fold_started", fold)
        if grouped:
            assert set(groups[train_idx]).isdisjoint(set(groups[test_idx])), "subject leakage detected"
        classifier = _build_embedding_classifier(classifier_type, 42 + fold, hyperparameters)
        classifier.fit(features[train_idx], labels[train_idx])
        train_predictions = np.asarray(classifier.predict(features[train_idx]), dtype=np.int64).reshape(-1)
        fold_predictions = np.asarray(classifier.predict(features[test_idx]), dtype=np.int64).reshape(-1)
        predictions[test_idx] = fold_predictions
        if probabilities is not None:
            raw = classifier.predict_proba(features[test_idx])
            for column, label in enumerate(classifier.classes_.astype(int)):
                probabilities[test_idx, TRAINING_LABEL_INDEX[label]] = raw[:, column]
            fold_sums = probabilities[test_idx].sum(axis=1, keepdims=True)
            if np.any(fold_sums <= 0):
                raise ValueError(f"第 {fold} 折未能生成有效分类概率")
            probabilities[test_idx] = probabilities[test_idx] / fold_sums
            scores[test_idx] = probabilities[test_idx]
            fold_scores = probabilities[test_idx].copy()
            fold_probabilities = probabilities[test_idx].copy()
        else:
            fold_scores = classifier.decision_function(features[test_idx])
            scores[test_idx] = fold_scores
            fold_probabilities = None
        folds.append(_fold_row(
            fold, train_idx, test_idx, labels, fold_predictions, train_predictions,
            scores=fold_scores, probabilities=fold_probabilities,
            groups=groups, grouped=grouped,
        ))
        _report_training_progress(progress_callback, "fold_completed", fold)

    # 交叉验证只负责评估；部署产物必须在同一冻结数据集的全部样本上重拟合。
    _report_training_progress(progress_callback, "refit_started", 5)
    final_classifier = _build_embedding_classifier(classifier_type, 42, hyperparameters)
    final_classifier.fit(features, labels)
    _report_training_progress(progress_callback, "refit_completed", 5)
    if probabilities is not None:
        row_sums = probabilities.sum(axis=1, keepdims=True)
        if np.any(row_sums <= 0):
            raise ValueError("概率分类器未能为全部样本生成有效概率")
        probabilities = probabilities / row_sums
    metrics = _classification_metrics(
        labels,
        predictions,
        folds,
        probabilities,
        scores,
        score_type="predict_proba" if probabilities is not None else "decision_function",
    )
    return None, final_classifier, metrics


def train_remote_embedding_linear_svc(
    features: np.ndarray, labels: np.ndarray, groups: np.ndarray,
    hyperparameters: dict[str, Any] | None = None,
):
    """显式入口：远程 Embedding + LinearSVC。"""
    return train_remote_embedding_classifier(features, labels, groups, "linear_svc", hyperparameters)


def train_remote_embedding_logistic_regression(
    features: np.ndarray, labels: np.ndarray, groups: np.ndarray,
    hyperparameters: dict[str, Any] | None = None,
):
    """显式入口：远程 Embedding + LogisticRegression。"""
    return train_remote_embedding_classifier(features, labels, groups, "logistic", hyperparameters)


def train_remote_embedding_random_forest(
    features: np.ndarray, labels: np.ndarray, groups: np.ndarray,
    hyperparameters: dict[str, Any] | None = None,
):
    """显式入口：远程 Embedding + RandomForest。"""
    return train_remote_embedding_classifier(features, labels, groups, "random_forest", hyperparameters)


__all__ = [
    "TRAINING_LABELS",
    "TRAINING_LABEL_NAMES",
    "TRAINING_LABEL_INDEX",
    "build_tfidf_linear_svc",
    "build_remote_embedding_linear_svc",
    "build_remote_embedding_logistic",
    "build_remote_embedding_random_forest",
    "build_remote_embedding_xgboost",
    "build_remote_embedding_lightgbm",
    "build_remote_embedding_catboost",
    "train_tfidf_linear_svc",
    "train_remote_embedding_classifier",
    "train_remote_embedding_linear_svc",
    "train_remote_embedding_logistic_regression",
    "train_remote_embedding_random_forest",
]
