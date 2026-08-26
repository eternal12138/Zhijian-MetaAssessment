from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sqlalchemy import or_, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.research import AuditLog, CodingUnit, ModelTrainingJob, TextEmbeddingCache
from app.models.session import AssessmentSession
from app.services.runtime_model_config import load_runtime_model_settings
from app.services.model_artifacts import sha256_file
from app.services.embedding_provider import (
    EmbeddingConfig,
    RemoteEmbeddingProvider,
    embedding_cache_key,
    text_hash,
)
from app.services.notifications import create_notification
from app.services.model_training_datasets import load_dataset_samples
from app.services.model_metrics_service import write_evaluation_bundle
from app.training import baseline_models
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, log_loss, precision_recall_fscore_support, precision_score, recall_score, roc_auc_score, roc_curve
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler, label_binarize

LABEL_MAP = {
    "monitoring": 1,
    "monitor": 1,
    "control": 2,
    "regulation": 2,
    "control_regulation": 2,
    "control-debugging": 2,
    "controldebugging": 2,
    "evaluation": 3,
}
TRAINING_LABEL_INDEX = baseline_models.TRAINING_LABEL_INDEX
TRAINING_LABEL_NAMES = baseline_models.TRAINING_LABEL_NAMES
TRAINING_LABELS = baseline_models.TRAINING_LABELS
TRAINING_PIPELINE_VERSION = 6
# The dedicated worker reloads this module between jobs when its source changes.
logger = logging.getLogger(__name__)


class TrainingCancelled(RuntimeError):
    pass


def _train_tfidf(
    samples: list[tuple[str, str, int]], labels: np.ndarray, groups: np.ndarray,
    hyperparameters: dict[str, Any] | None = None,
    progress_callback=None,
):
    """Resolve the trainer at call time so an idle worker reload cannot retain a stale function."""
    return baseline_models.train_tfidf_linear_svc(
        samples, labels, groups, hyperparameters=hyperparameters,
        progress_callback=progress_callback,
    )


def _train_embedding_classifier(
    features: np.ndarray, labels: np.ndarray, groups: np.ndarray,
    classifier_type: str, hyperparameters: dict[str, Any] | None = None,
    progress_callback=None,
):
    """Resolve the trainer at call time; baseline_models is reloaded in place by the worker."""
    return baseline_models.train_remote_embedding_classifier(
        features, labels, groups, classifier_type,
        hyperparameters=hyperparameters,
        progress_callback=progress_callback,
    )


class _TrainingProgressState:
    """Thread-safe fold progress shared by the trainer and async heartbeat."""

    def __init__(self, base_progress: int, target_progress: int = 89, total_folds: int = 5):
        self.base_progress = base_progress
        self.target_progress = target_progress
        self.total_folds = total_folds
        self.stage = "training_fold_1"
        self.progress = base_progress
        self.current_fold: int | None = 1
        self.estimated_remaining_seconds: int | None = None
        self._started_at = time.monotonic()
        self._unit_started_at = self._started_at
        self._unit_durations: list[float] = []
        self._lock = threading.Lock()

    def callback(self, event: str, fold: int, total_folds: int) -> None:
        now = time.monotonic()
        with self._lock:
            self.total_folds = total_folds
            if event == "fold_started":
                self.stage = f"training_fold_{fold}"
                self.current_fold = fold
                self._unit_started_at = now
            elif event == "fold_completed":
                self._unit_durations.append(max(.001, now - self._unit_started_at))
                self.progress = self.base_progress + round(
                    (self.target_progress - self.base_progress) * fold / (total_folds + 1)
                )
            elif event == "refit_started":
                self.stage = "refitting"
                self.current_fold = None
                self._unit_started_at = now
            elif event == "refit_completed":
                self.stage = "evaluating"
                self.current_fold = None
                self.progress = self.target_progress
            self._refresh_eta(now)

    def _refresh_eta(self, now: float) -> None:
        if not self._unit_durations:
            self.estimated_remaining_seconds = None
            return
        average = sum(self._unit_durations) / len(self._unit_durations)
        if self.stage.startswith("training_fold_") and self.current_fold is not None:
            # Current fold + later folds + one final full-data refit.
            remaining_units = self.total_folds - self.current_fold + 2
            remaining = average * remaining_units - (now - self._unit_started_at)
        elif self.stage == "refitting":
            remaining = average - (now - self._unit_started_at)
        else:
            remaining = 0
        self.estimated_remaining_seconds = max(0, round(remaining))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_eta(time.monotonic())
            return {
                "stage": self.stage,
                "progress": self.progress,
                "current_fold": self.current_fold,
                "total_folds": self.total_folds,
                "estimated_remaining_seconds": self.estimated_remaining_seconds,
            }


async def _training_heartbeat(
    job_id: str, state: _TrainingProgressState, stop: asyncio.Event,
) -> None:
    """Persist liveness even while a CPU-bound estimator is fitting in a worker thread."""
    from app.core.time import utc_now_naive

    while True:
        await _set_job(job_id, heartbeat_at=utc_now_naive(), **state.snapshot())
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
            return
        except TimeoutError:
            continue


async def _run_with_training_progress(job_id: str, base_progress: int, trainer):
    state = _TrainingProgressState(base_progress)
    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_training_heartbeat(job_id, state, stop))
    try:
        result = await asyncio.to_thread(trainer, state.callback)
        await _set_job(job_id, heartbeat_at=None, **state.snapshot())
        return result
    finally:
        stop.set()
        await heartbeat


def _positive_int(value: object, *, name: str, default: int | None = None, allow_zero: bool = False) -> int:
    candidate = default if value is None or value == "" else value
    try:
        parsed = int(candidate)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name}必须是整数") from error
    minimum = 0 if allow_zero else 1
    if parsed < minimum:
        raise ValueError(f"{name}不能小于 {minimum}")
    return parsed


def _positive_float(value: object, *, name: str, default: float) -> float:
    candidate = default if value is None or value == "" else value
    try:
        parsed = float(candidate)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name}必须是数字") from error
    if parsed <= 0:
        raise ValueError(f"{name}必须大于 0")
    return parsed


def _job_config(job: ModelTrainingJob, runtime) -> dict[str, Any]:
    snapshot = dict(job.config_snapshot or {})
    base_url = str(
        snapshot.get("embedding_base_url")
        or getattr(runtime, "EMBEDDING_API_BASE", "")
        or getattr(runtime, "QWEN_EMBEDDING_BASE_URL", "")
        or ""
    ).rstrip("/")
    model = str(
        snapshot.get("embedding_model")
        or getattr(runtime, "EMBEDDING_MODEL", "")
        or getattr(runtime, "QWEN_EMBEDDING_MODEL", "")
        or ""
    )
    dimensions = _positive_int(
        snapshot.get("embedding_dimension")
        or snapshot.get("dimensions")
        or (
            getattr(runtime, "EMBEDDING_DIMENSION", None)
            if getattr(runtime, "EMBEDDING_MODEL", "")
            else getattr(runtime, "QWEN_EMBEDDING_DIMENSIONS", None)
        ),
        name="Embedding 向量维度",
    )
    return {
        "provider": str(snapshot.get("embedding_provider") or getattr(runtime, "EMBEDDING_PROVIDER", "openai_compatible")),
        "base_url": base_url,
        "model": model,
        "version": str(snapshot.get("embedding_version") or getattr(runtime, "EMBEDDING_VERSION", "default")),
        "dimensions": dimensions,
        "normalized": bool(snapshot.get("embedding_normalized", getattr(runtime, "EMBEDDING_NORMALIZED", True))),
        "instruction": snapshot.get("embedding_instruction", getattr(runtime, "EMBEDDING_INSTRUCTION", "")) or None,
        "batch_size": _positive_int(
            snapshot.get("batch_size") or getattr(runtime, "EMBEDDING_BATCH_SIZE", None)
            or getattr(runtime, "QWEN_EMBEDDING_BATCH_SIZE", None),
            name="Embedding 批大小", default=32,
        ),
        "timeout": _positive_float(
            snapshot.get("timeout_seconds") or getattr(runtime, "EMBEDDING_TIMEOUT", None)
            or getattr(runtime, "QWEN_EMBEDDING_TIMEOUT_SECONDS", None),
            name="Embedding 超时时间", default=60.0,
        ),
        "max_retries": _positive_int(
            snapshot.get("max_retries") if snapshot.get("max_retries") is not None
            else getattr(runtime, "EMBEDDING_MAX_RETRIES", None),
            name="Embedding 重试次数", default=4, allow_zero=True,
        ),
        "api_key": getattr(runtime, "EMBEDDING_API_KEY", "") or getattr(runtime, "QWEN_EMBEDDING_API_KEY", ""),
    }


def _job_embedding_config(job: ModelTrainingJob, runtime) -> dict[str, Any] | None:
    if str((job.config_snapshot or {}).get("feature") or "remote_embedding") == "tfidf":
        return None
    return _job_config(job, runtime)


def _provider_config(config: dict[str, Any]) -> EmbeddingConfig:
    return EmbeddingConfig(
        provider=config["provider"], model=config["model"], version=config["version"],
        dimensions=config["dimensions"], base_url=config["base_url"], api_key=config["api_key"],
        normalized=config["normalized"], instruction=config["instruction"],
        batch_size=config["batch_size"], timeout_seconds=config["timeout"],
        max_retries=config["max_retries"],
    )


def _cache_key(model: str, dimensions: int, text: str) -> str:
    """Backward-compatible helper retained for existing imports/tests."""
    return hashlib.sha256(f"{model}\0{dimensions}\0{text.strip()}".encode("utf-8")).hexdigest()


async def _set_job(job_id: str, **values) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(ModelTrainingJob, job_id)
        if job:
            for key, value in values.items():
                setattr(job, key, value)
            await db.commit()


async def _check_cancelled(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(ModelTrainingJob, job_id)
        if job is None or job.cancel_requested or job.status == "cancelled":
            raise TrainingCancelled("训练任务已由管理员取消")


async def _finish_job(job_id: str, *, status: str, message: str = "") -> None:
    from datetime import datetime, timezone
    async with AsyncSessionLocal() as db:
        job = await db.get(ModelTrainingJob, job_id)
        if not job:
            return
        job.status = status
        job.stage = status
        job.current_fold = None
        job.heartbeat_at = None
        job.estimated_remaining_seconds = None
        job.error_message = message[:2000]
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        action = f"model_training.{status}"
        db.add(AuditLog(
            actor_id=None, action=action, target_type="model_training_job", target_id=job.id,
            detail={"version": job.version, "message": job.error_message},
        ))
        notification = {
            "user_id": job.requested_by,
            "title": f"模型训练 {job.version} {'已完成' if status == 'completed' else '已取消' if status == 'cancelled' else '失败'}",
            "content": (
                "训练产物和评估指标已生成，请进入研究管理进行人工验收。"
                if status == "completed" else job.error_message or "训练任务未完成。"
            ),
            "event_key": f"model-training:{job.id}:{status}",
            "metadata": {"job_id": job.id, "version": job.version, "status": status},
        }
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            await create_notification(
                db, type="system", target_url="/prompt-manage", priority="important",
                **notification,
            )
            await db.commit()
    except Exception:
        logger.exception("Training job %s reached %s but notification delivery failed", job_id, status)


async def claim_next_training_job() -> str | None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await db.execute(
                select(ModelTrainingJob).where(ModelTrainingJob.status == "queued")
                .order_by(ModelTrainingJob.created_at).with_for_update(skip_locked=True).limit(25)
            )
            jobs = list(result.scalars())
            job = None
            for candidate in jobs:
                required_version = int(
                    (candidate.config_snapshot or {}).get("training_pipeline_version") or 1
                )
                if required_version > TRAINING_PIPELINE_VERSION:
                    candidate.stage = "waiting_worker_upgrade"
                    continue
                job = candidate
                break
            if job is None:
                return None
            from datetime import datetime, timezone
            job.status = "running"
            job.stage = "preparing_dataset"
            job.progress = 5
            job.current_fold = None
            job.total_folds = 5
            job.estimated_remaining_seconds = None
            job.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            job.heartbeat_at = job.started_at
            return job.id


async def recover_stale_training_jobs(max_age_minutes: int = 30) -> int:
    from datetime import timedelta
    from app.core.time import utc_now_naive
    cutoff = utc_now_naive() - timedelta(minutes=max_age_minutes)
    async with AsyncSessionLocal() as db:
        jobs = list((await db.scalars(select(ModelTrainingJob).where(
            ModelTrainingJob.status == "running",
            or_(ModelTrainingJob.updated_at.is_(None), ModelTrainingJob.updated_at < cutoff),
        ))).all())
        for job in jobs:
            job.status = "failed"
            job.stage = "failed"
            job.error_message = "训练 Worker 中断，任务已由系统恢复为失败状态，可重新运行"
            job.completed_at = utc_now_naive()
            db.add(AuditLog(actor_id=None, action="model_training.recovered_failed", target_type="model_training_job", target_id=job.id, detail={"version": job.version}))
        await db.commit()
        return len(jobs)


async def _reviewed_samples(db) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    legacy_dimensions: dict[str, int] = {}
    coded = await db.execute(
        select(CodingUnit.segment, CodingUnit.final_dimension, AssessmentSession.user_id)
        .join(AssessmentSession, AssessmentSession.id == CodingUnit.session_id)
        .where(CodingUnit.status.in_(["agreed", "adjudicated"]), CodingUnit.final_dimension.is_not(None))
    )
    for text, dimension, user_id in coded:
        normalized = str(dimension).strip().lower()
        label = LABEL_MAP.get(normalized)
        if label is not None and str(text).strip():
            rows.append((str(user_id), str(text).strip(), label))
        elif normalized:
            legacy_dimensions[normalized] = legacy_dimensions.get(normalized, 0) + 1
    if legacy_dimensions:
        listing = "、".join(
            f"{label}（{count} 条）"
            for label, count in sorted(legacy_dimensions.items())
        )
        raise ValueError(
            "系统专家数据包含无法直接映射到 1监控/2调控/3评估 的历史标签，"
            f"请先生成迁移清单并人工确认归类，不能自动猜测：{listing}"
        )
    # Same participant/text/label is one gold sample; conflicting labels are never
    # silently collapsed because they require expert arbitration.
    unique = sorted(set(rows), key=lambda row: (row[0], row[2], row[1]))
    labels_by_text: dict[tuple[str, str], set[int]] = {}
    for user_id, text, label in unique:
        labels_by_text.setdefault((user_id, text), set()).add(label)
    conflicts = [key for key, labels in labels_by_text.items() if len(labels) > 1]
    if conflicts:
        raise ValueError(f"检测到 {len(conflicts)} 条同一被试同一文本的冲突标签，请先完成仲裁")
    return unique


async def _embeddings(samples, config: dict[str, Any], job_id: str) -> np.ndarray:
    provider_config = _provider_config(config)
    provider_config.validate()
    vectors: list[np.ndarray | None] = [None] * len(samples)
    keys = [embedding_cache_key(provider_config, text) for _, text, _ in samples]
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(TextEmbeddingCache).where(TextEmbeddingCache.cache_key.in_(keys)))
        cached = {item.cache_key: item for item in existing.scalars()}
    missing = []
    for index, key in enumerate(keys):
        item = cached.get(key)
        if item and item.dimensions == config["dimensions"]:
            vectors[index] = np.frombuffer(item.vector, dtype=np.float32).copy()
        else:
            missing.append(index)
    async with RemoteEmbeddingProvider(provider_config) as provider:
        for start in range(0, len(missing), config["batch_size"]):
            await _check_cancelled(job_id)
            indices = missing[start:start + config["batch_size"]]
            texts = [samples[i][1] for i in indices]
            result = await provider.embed(texts)
            async with AsyncSessionLocal() as db:
                for index, vector in zip(indices, result.vectors, strict=True):
                    vectors[index] = vector
                    db.add(TextEmbeddingCache(
                        cache_key=keys[index], text_hash=text_hash(samples[index][1]),
                        provider=config["provider"], model=config["model"],
                        model_version=config["version"], dimensions=config["dimensions"],
                        normalized=config["normalized"],
                        instruction_hash=provider_config.instruction_hash,
                        vector=np.asarray(vector, dtype=np.float32).tobytes(),
                    ))
                await db.commit()
            completed = min(start + len(indices), len(missing))
            await _set_job(job_id, stage="embedding", progress=15 + round(40 * completed / max(1, len(missing))))
    if any(item is None for item in vectors):
        raise RuntimeError("部分训练文本未获得嵌入向量")
    return np.vstack([item for item in vectors if item is not None])


def _validation_splitter(labels: np.ndarray, groups: np.ndarray):
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
    return {
        str(label): int((selected == label).sum())
        for label in TRAINING_LABELS
    }


def _specificities(labels: np.ndarray, predictions: np.ndarray) -> list[float]:
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


def _train(features: np.ndarray, labels: np.ndarray, groups: np.ndarray):
    splitter, grouped = _validation_splitter(labels, groups)
    probabilities = np.zeros((len(labels), len(TRAINING_LABELS)), dtype=np.float64)
    predictions = np.zeros(len(labels), dtype=np.int64)
    fold_metrics = []
    for fold, (train_idx, test_idx) in enumerate(
        _validation_splits(splitter, features, labels, groups, grouped), start=1
    ):
        scaler = StandardScaler().fit(features[train_idx])
        classifier = MLPClassifier(hidden_layer_sizes=(128,), activation="relu", solver="adam", max_iter=250, early_stopping=True, validation_fraction=.15, n_iter_no_change=15, random_state=42 + fold)
        classifier.fit(scaler.transform(features[train_idx]), labels[train_idx])
        train_predictions = classifier.predict(scaler.transform(features[train_idx]))
        raw = classifier.predict_proba(scaler.transform(features[test_idx]))
        probs = np.zeros((len(test_idx), len(TRAINING_LABELS)))
        for column, label in enumerate(classifier.classes_.astype(int)):
            probs[:, TRAINING_LABEL_INDEX[label]] = raw[:, column]
        probabilities[test_idx] = probs
        predictions[test_idx] = np.asarray(TRAINING_LABELS)[probs.argmax(axis=1)]
        fold_metrics.append({
            "fold": fold,
            "train_sample_count": int(len(train_idx)),
            "sample_count": int(len(test_idx)),
            "train_label_distribution": _label_distribution(labels, train_idx),
            "test_label_distribution": _label_distribution(labels, test_idx),
            "train_accuracy": float(accuracy_score(labels[train_idx], train_predictions)),
            "train_macro_f1": float(f1_score(labels[train_idx], train_predictions, average="macro", zero_division=0)),
            "macro_f1": float(f1_score(labels[test_idx], predictions[test_idx], average="macro", zero_division=0)),
            "macro_precision": float(precision_score(labels[test_idx], predictions[test_idx], average="macro", zero_division=0)),
            "macro_recall": float(recall_score(labels[test_idx], predictions[test_idx], average="macro", zero_division=0)),
            "weighted_precision": float(precision_score(labels[test_idx], predictions[test_idx], average="weighted", zero_division=0)),
            "weighted_recall": float(recall_score(labels[test_idx], predictions[test_idx], average="weighted", zero_division=0)),
            "accuracy": float(accuracy_score(labels[test_idx], predictions[test_idx])),
        })
    binary = label_binarize(labels, classes=list(TRAINING_LABELS))
    per_precision, per_recall, per_f1, per_support = precision_recall_fscore_support(
        labels, predictions, labels=list(TRAINING_LABELS), zero_division=0
    )
    metrics = {
        "accuracy": float(accuracy_score(labels, predictions)),
        "macro_precision": float(precision_score(labels, predictions, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(labels, predictions, average="macro", zero_division=0)),
        "weighted_precision": float(precision_score(labels, predictions, average="weighted", zero_division=0)),
        "weighted_recall": float(recall_score(labels, predictions, average="weighted", zero_division=0)),
        "macro_f1": float(f1_score(labels, predictions, average="macro", zero_division=0)),
        "cross_entropy": float(log_loss(labels, probabilities, labels=list(TRAINING_LABELS))),
        "macro_auc_ovr": float(roc_auc_score(binary, probabilities, average="macro", multi_class="ovr")),
        "folds": fold_metrics,
        "confusion_matrix": confusion_matrix(labels, predictions, labels=list(TRAINING_LABELS)).astype(int).tolist(),
        "per_class": {
            str(label): {
                "precision": float(per_precision[index]),
                "recall": float(per_recall[index]),
                "f1": float(per_f1[index]),
                "support": int(per_support[index]),
            }
            for index, label in enumerate(TRAINING_LABELS)
        },
    }
    metrics.update(_classification_metrics(
        labels, predictions, fold_metrics,
        probabilities=probabilities, scores=probabilities,
    ))
    scaler = StandardScaler().fit(features)
    classifier = MLPClassifier(hidden_layer_sizes=(128,), activation="relu", solver="adam", max_iter=250, early_stopping=True, validation_fraction=.15, n_iter_no_change=15, random_state=42)
    classifier.fit(scaler.transform(features), labels)
    return scaler, classifier, metrics


def _classification_metrics(
    labels: np.ndarray, predictions: np.ndarray, fold_metrics: list[dict],
    probabilities: np.ndarray | None = None,
    scores: np.ndarray | None = None,
    score_type: str | None = None,
) -> dict[str, Any]:
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
        "macro_f1": float(f1_score(labels, predictions, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(labels, predictions, average="weighted", zero_division=0)),
        "macro_specificity": float(np.mean(per_specificity)),
        "folds": fold_metrics,
        "confusion_matrix": confusion_matrix(labels, predictions, labels=list(TRAINING_LABELS)).astype(int).tolist(),
        "per_class": {
            str(label): {
                "precision": float(per_precision[index]), "recall": float(per_recall[index]),
                "specificity": per_specificity[index],
                "f1": float(per_f1[index]), "support": int(per_support[index]),
            }
            for index, label in enumerate(TRAINING_LABELS)
        },
    }
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
        metrics["cross_entropy"] = float(log_loss(labels, probabilities, labels=list(TRAINING_LABELS)))
    return metrics


async def process_training_job(job_id: str) -> None:
    from datetime import datetime, timezone
    try:
        settings = get_settings()
        async with AsyncSessionLocal() as db:
            await load_runtime_model_settings(db, settings)
            job = await db.get(ModelTrainingJob, job_id)
            if not job:
                return
            snapshot = dict(job.config_snapshot or {})
            pipeline_version = int(snapshot.get("training_pipeline_version") or 1)
            if pipeline_version > TRAINING_PIPELINE_VERSION:
                raise ValueError(
                    f"训练任务需要管线版本 {pipeline_version}，当前 Worker 仅支持版本 {TRAINING_PIPELINE_VERSION}"
                )
            dataset_id = str(snapshot.get("dataset_id") or "")
            if snapshot.get("dataset_source") == "uploaded" and not dataset_id:
                raise ValueError("上传训练任务没有绑定不可变数据快照，请重新创建任务")
            samples = (
                load_dataset_samples(settings.model_training_path, dataset_id)
                if dataset_id else await _reviewed_samples(db)
            )
            if pipeline_version >= 5:
                samples = [item for item in samples if item[2] in TRAINING_LABELS]
            config = _job_embedding_config(job, settings)
        await _check_cancelled(job_id)
        if len(samples) < 30:
            raise ValueError("标签1/2/3的人工复核金标准样本少于 30 条，暂不建议训练")
        labels = np.asarray([item[2] for item in samples], dtype=np.int64)
        distribution = {str(label): int((labels == label).sum()) for label in TRAINING_LABELS}
        fingerprint = hashlib.sha256(json.dumps(samples, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        groups = np.asarray([item[0] for item in samples])
        has_participant_ids = all(str(value).strip() for value in groups.tolist())
        snapshot = dict(job.config_snapshot or {})
        feature_type = str(snapshot.get("feature") or "remote_embedding")
        classifier_type = str((job.config_snapshot or {}).get("classifier") or "linear_svc")
        classifier_parameters = dict(snapshot.get("classifier_parameters") or {})
        initial_stage = "preparing_features" if feature_type == "tfidf" else "embedding"
        await _set_job(
            job_id, sample_count=len(samples), label_distribution=distribution,
            dataset_fingerprint=fingerprint, stage=initial_stage, progress=15,
        )
        if feature_type == "tfidf":
            scaler, classifier, metrics = await _run_with_training_progress(
                job_id, 40, lambda callback: _train_tfidf(
                    samples, labels, groups, classifier_parameters, callback,
                ),
            )
        else:
            if config is None:
                raise ValueError("Embedding 训练任务缺少嵌入配置")
            features = await _embeddings(samples, config, job_id)
            await _check_cancelled(job_id)
            if classifier_type in {
                "linear_svc", "logistic", "random_forest",
                "xgboost", "lightgbm", "catboost",
            }:
                scaler, classifier, metrics = await _run_with_training_progress(
                    job_id, 60, lambda callback: _train_embedding_classifier(
                        features, labels, groups, classifier_type,
                        classifier_parameters, callback,
                    ),
                )
            else:
                # Retain support for historical MLP jobs created before the
                # four-baseline experiment suite was introduced.
                scaler, classifier, metrics = _train(features, labels, groups)
        metrics["split_strategy"] = (
            "subject_grouped_stratified_5fold"
            if has_participant_ids else "sentence_stratified_5fold"
        )
        metrics["subject_leakage_risk"] = not has_participant_ids
        metrics["evaluation_warning"] = (
            ""
            if has_participant_ids
            else "训练数据未提供被试标识，当前指标采用句子级分层五折，可能存在被试信息泄漏风险。"
        )
        metrics["evaluation_summary"] = {
            "method": "five_fold_cross_validation",
            "split_strategy": metrics["split_strategy"],
            "sample_count": int(len(samples)),
            "participant_count": int(len(set(groups.tolist()))) if has_participant_ids else None,
            "label_distribution": distribution,
            "fold_count": 5,
            "out_of_fold_sample_count": int(sum(
                int(fold.get("sample_count") or 0) for fold in metrics.get("folds", [])
            )),
            "every_sample_evaluated_once": True,
            "final_model_refit_on_all_data": True,
            "external_holdout": False,
        }
        oof_predictions = metrics.pop("_oof_predictions", None)
        if isinstance(oof_predictions, list) and len(oof_predictions) == len(samples):
            error_rows = []
            for (participant_id, text, true_label), predicted_label in zip(
                samples, oof_predictions, strict=True,
            ):
                if int(true_label) == int(predicted_label):
                    continue
                error_rows.append({
                    "participant_id": str(participant_id) or None,
                    "text": str(text),
                    "true_label": int(true_label),
                    "predicted_label": int(predicted_label),
                })
            metrics["error_analysis"] = {
                "total_error_count": len(error_rows),
                "displayed_error_count": len(error_rows),
                "cases": error_rows,
                "metadata_availability": {
                    "participant_id": has_participant_ids,
                    "task_id": False,
                    "audio_id": False,
                    "segment_id": False,
                },
                "note": (
                    "当前冻结训练快照仅含被试标识、清洗后文本和专家标签；"
                    "任务、音频及片段字段未进入该训练版本，无法按任务或音频回听分析。"
                ),
            }
        metrics["classifier_parameters"] = classifier_parameters
        metrics["hyperparameters_tuned"] = bool(snapshot.get("hyperparameters_tuned"))
        metrics["hyperparameter_source"] = str(snapshot.get("hyperparameter_source") or "default")
        await _check_cancelled(job_id)
        await _set_job(
            job_id, stage="saving", progress=92, current_fold=None,
            heartbeat_at=None, estimated_remaining_seconds=None,
        )
        artifact_dir = settings.model_training_path / job.version
        artifact_dir.mkdir(parents=True, exist_ok=False)
        artifact = artifact_dir / "model.joblib"
        artifact_part = artifact_dir / "model.joblib.part"
        embedding_identity = (
            _provider_config(config).identity()
            if feature_type == "remote_embedding" and config is not None else None
        )
        joblib.dump({
            "scaler": scaler, "classifier": classifier,
            "classifier_type": classifier_type,
            "feature_type": feature_type,
            "embedding_model": config["model"] if config is not None else None,
            "dimensions": config["dimensions"] if config is not None else 1,
            "embedding_config": embedding_identity,
            "labels": TRAINING_LABEL_NAMES,
            "training_pipeline_version": TRAINING_PIPELINE_VERSION,
            "dataset_id": snapshot.get("dataset_id"),
            "dataset_fingerprint": fingerprint,
            "classifier_parameters": classifier_parameters,
            "hyperparameters_tuned": bool(snapshot.get("hyperparameters_tuned")),
        }, artifact_part)
        artifact_part.replace(artifact)
        metrics_path = artifact_dir / "metrics.json"
        metrics_part = artifact_dir / "metrics.json.part"
        metrics_part.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        metrics_part.replace(metrics_path)
        artifact_digest = sha256_file(artifact)
        job.artifact_path = str(artifact)
        job.artifact_sha256 = artifact_digest
        write_evaluation_bundle(job, artifact_dir, metrics, datetime.now(timezone.utc))
        await _set_job(
            job_id, progress=100, metrics=metrics, artifact_path=str(artifact),
            artifact_sha256=artifact_digest,
        )
        await _finish_job(job_id, status="completed")
    except TrainingCancelled as error:
        await _finish_job(job_id, status="cancelled", message=str(error))
    except Exception as error:
        await _finish_job(job_id, status="failed", message=str(error))
        raise
