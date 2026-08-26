"""Production classification using the manually activated embedding classifier."""
from __future__ import annotations

import time

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.time import utc_now_naive
from app.models.extraction import ExtractionCandidate
from app.models.research import (
    ModelPredictionResult,
    ModelPredictionRun,
    ModelTrainingJob,
    TextEmbeddingCache,
)
from app.services.embedding_provider import (
    EmbeddingProviderError,
    RemoteEmbeddingProvider,
    assert_embedding_identity,
    embedding_cache_key,
    text_hash,
)
from app.services.model_artifacts import load_model_artifact, load_tfidf_fallback
from app.services.model_training import _job_config, _provider_config
from app.services.runtime_model_config import load_runtime_model_settings

DIMENSION_MAP = {
    0: "non_meta",
    1: "monitoring",
    2: "controlDebugging",
    3: "evaluation",
}


def invalidate_candidate_prediction(candidate: ExtractionCandidate) -> None:
    """Discard a prediction after its model input text has changed."""
    candidate.classifier_job_id = None
    candidate.classifier_version = None
    candidate.predicted_label = None
    candidate.predicted_dimension = None
    candidate.prediction_confidence = None
    candidate.prediction_probabilities = None
    candidate.classified_at = None
    candidate.classification_status = "pending_classification"
    candidate.prediction_source = None
    candidate.classification_error = ""


def mark_pending_classification(candidates: list[ExtractionCandidate], error: Exception) -> None:
    message = str(error)[:1000]
    for candidate in candidates:
        candidate.classification_status = "pending_classification"
        candidate.prediction_source = None
        candidate.classification_error = message


def apply_tfidf_fallback(
    candidates: list[ExtractionCandidate], texts: list[str], fallback, active: ModelTrainingJob,
    error: Exception,
) -> None:
    predictions = fallback.predict(texts)
    fallback_labels = {
        "non_metacognitive": 0, "monitoring": 1,
        "regulation": 2, "evaluation": 3,
        0: 0, 1: 1, 2: 2, 3: 3,
    }
    for candidate, raw_label in zip(candidates, predictions, strict=True):
        if raw_label not in fallback_labels:
            raise ValueError(f"TF-IDF fallback 返回未知标签：{raw_label}")
        label = fallback_labels[raw_label]
        candidate.classifier_job_id = active.id
        candidate.classifier_version = active.version
        candidate.predicted_label = label
        candidate.predicted_dimension = DIMENSION_MAP[label]
        candidate.prediction_confidence = None
        candidate.prediction_probabilities = None
        candidate.classified_at = utc_now_naive()
        candidate.classification_status = "classified_with_fallback"
        candidate.prediction_source = "tfidf_fallback"
        candidate.classification_error = str(error)[:1000]


async def _embed_texts(
    texts: list[str], config: dict, db: AsyncSession,
) -> np.ndarray:
    provider_config = _provider_config(config)
    provider_config.validate()
    keys = [embedding_cache_key(provider_config, text) for text in texts]
    indices_by_key: dict[str, list[int]] = {}
    for index, key in enumerate(keys):
        indices_by_key.setdefault(key, []).append(index)
    existing = list((await db.scalars(
        select(TextEmbeddingCache).where(TextEmbeddingCache.cache_key.in_(indices_by_key))
    )).all())
    cached = {item.cache_key: item for item in existing}
    vectors: list[np.ndarray | None] = [None] * len(texts)
    missing_keys: list[str] = []
    for key, indices in indices_by_key.items():
        item = cached.get(key)
        if item and item.dimensions == config["dimensions"]:
            vector = np.frombuffer(item.vector, dtype=np.float32).copy()
            if vector.size == config["dimensions"]:
                for index in indices:
                    vectors[index] = vector
                continue
        missing_keys.append(key)

    async with RemoteEmbeddingProvider(provider_config) as provider:
        for start in range(0, len(missing_keys), config["batch_size"]):
            batch_keys = missing_keys[start:start + config["batch_size"]]
            source_indices = [indices_by_key[key][0] for key in batch_keys]
            result = await provider.embed([texts[index] for index in source_indices])
            for key, source_index, vector in zip(
                batch_keys, source_indices, result.vectors, strict=True,
            ):
                normalized_vector = np.asarray(vector, dtype=np.float32)
                for index in indices_by_key[key]:
                    vectors[index] = normalized_vector
                db.add(TextEmbeddingCache(
                    cache_key=key,
                    text_hash=text_hash(texts[source_index]), provider=config["provider"],
                    model=config["model"], model_version=config["version"],
                    dimensions=config["dimensions"], normalized=config["normalized"],
                    instruction_hash=provider_config.instruction_hash,
                    vector=normalized_vector.tobytes(),
                ))
    if any(vector is None for vector in vectors):
        raise ValueError("部分候选未获得嵌入向量")
    return np.vstack([vector for vector in vectors if vector is not None])


def _redacted_embedding_snapshot(config: dict) -> dict:
    return {key: value for key, value in config.items() if key != "api_key"}


def _probe_embedding_features(vectors: object, expected_dimensions: int) -> np.ndarray:
    """Validate one probe embedding without coercing a NumPy array to bool."""
    try:
        matrix = np.asarray(vectors, dtype=np.float32)
    except (TypeError, ValueError) as error:
        raise ValueError("Embedding 探针返回了无法解析的向量") from error
    expected_shape = (1, int(expected_dimensions))
    if matrix.shape != expected_shape:
        raise ValueError(
            f"Embedding 探针向量形状异常：期望 {expected_shape}，实际 {matrix.shape}"
        )
    if not np.isfinite(matrix).all():
        raise ValueError("Embedding 探针返回了非有限数值")
    return matrix


def _prediction_quality(probs: dict[int, float] | None, label: int) -> tuple[float | None, str, bool]:
    if not probs:
        return None, "", False
    ordered = sorted(probs.values(), reverse=True)
    gap = round(float(ordered[0] - ordered[1]), 6) if len(ordered) >= 2 else None
    confidence = probs.get(label)
    reasons: list[str] = []
    if confidence is not None and confidence < 0.6:
        reasons.append("top1 置信度低于 0.6")
    if gap is not None and gap < 0.15:
        reasons.append("top1 与 top2 概率差距过小")
    return gap, "；".join(reasons), bool(reasons)


async def probe_model_activation(job: ModelTrainingJob, runtime) -> None:
    """Run one real end-to-end inference to prove the artifact is production-safe."""
    artifact = load_model_artifact(job, runtime)
    config = _job_config(job, runtime)
    feature_type = str(
        artifact.get("feature_type")
        or (job.config_snapshot or {}).get("feature")
        or "remote_embedding"
    )
    probe_text = "我发现刚才的方法可能不对，准备换一种方法再验证一次结果。"
    if feature_type == "remote_embedding":
        provider_config = _provider_config(config)
        trained_identity = artifact.get("embedding_config") or {
            "embedding_provider": config["provider"],
            "embedding_model": artifact["embedding_model"],
            "embedding_version": config["version"],
            "embedding_dimension": int(artifact["dimensions"]),
            "embedding_normalized": config["normalized"],
            "embedding_instruction": config["instruction"],
        }
        assert_embedding_identity(trained_identity, provider_config)
        async with RemoteEmbeddingProvider(provider_config) as provider:
            result = await provider.embed([probe_text])
        features = _probe_embedding_features(result.vectors, config["dimensions"])
    else:
        features = [probe_text]
    transformed = (
        artifact["scaler"].transform(features)
        if artifact.get("scaler") is not None else features
    )
    classifier = artifact["classifier"]
    predictions = classifier.predict(transformed)
    if len(predictions) != 1:
        raise ValueError("模型推理探针未返回唯一预测结果")
    label = int(predictions[0])
    if label not in DIMENSION_MAP:
        raise ValueError(f"模型探针输出非法类别标签：{label}")
    if hasattr(classifier, "predict_proba"):
        raw = classifier.predict_proba(transformed)
        if raw.shape[0] != 1 or not np.isfinite(raw).all() or (raw < 0).any():
            raise ValueError("模型探针输出非法概率")
        class_labels = classifier.classes_.astype(int).tolist()
        if label not in class_labels:
            raise ValueError("模型探针预测标签不在分类器类别列表中")


async def classify_candidates(
    db: AsyncSession, candidates: list[ExtractionCandidate],
) -> ModelTrainingJob | None:
    if not candidates:
        return None
    active = await db.scalar(
        select(ModelTrainingJob)
        .where(ModelTrainingJob.is_active.is_(True), ModelTrainingJob.status == "completed")
        .order_by(ModelTrainingJob.activated_at.desc())
        .limit(1)
    )
    if active is None:
        for candidate in candidates:
            candidate.classification_status = "not_active"
            candidate.prediction_source = None
        return None
    runtime = await load_runtime_model_settings(db, get_settings())
    config = _job_config(active, runtime)
    artifact = load_model_artifact(active, runtime)
    feature_type = str(
        artifact.get("feature_type")
        or (active.config_snapshot or {}).get("feature")
        or "remote_embedding"
    )
    if feature_type == "remote_embedding":
        trained_identity = artifact.get("embedding_config") or {
            "embedding_provider": config["provider"],
            "embedding_model": artifact["embedding_model"],
            "embedding_version": config["version"],
            "embedding_dimension": int(artifact["dimensions"]),
            "embedding_normalized": config["normalized"],
            "embedding_instruction": config["instruction"],
        }
        assert_embedding_identity(trained_identity, _provider_config(config))
    texts = [candidate.clean_text.strip() for candidate in candidates]
    started_at = utc_now_naive()
    started_monotonic = time.perf_counter()
    run = ModelPredictionRun(
        model_job_id=active.id,
        model_version=active.version,
        engine="remote_embedding" if feature_type == "remote_embedding" else "tfidf_production",
        embedding_config_snapshot=(
            _redacted_embedding_snapshot(config)
            if feature_type == "remote_embedding" else None
        ),
        status="running",
        started_at=started_at,
    )
    db.add(run)
    await db.flush()
    try:
        features = await _embed_texts(texts, config, db) if feature_type == "remote_embedding" else texts
        transformed = artifact["scaler"].transform(features) if artifact.get("scaler") is not None else features
        classifier = artifact["classifier"]
        predictions = classifier.predict(transformed)
        probabilities: list[dict[int, float]] | None = None
        if hasattr(classifier, "predict_proba"):
            raw = classifier.predict_proba(transformed)
            class_labels = classifier.classes_.astype(int).tolist()
            probabilities = [
                {int(label): float(row[column]) for column, label in enumerate(class_labels)}
                for row in raw
            ]
        duration_ms = int((time.perf_counter() - started_monotonic) * 1000)
        for index, candidate in enumerate(candidates):
            label = int(predictions[index])
            probs = probabilities[index] if probabilities is not None else None
            gap, low_reason, needs_review = _prediction_quality(probs, label)
            candidate.classifier_job_id = active.id
            candidate.classifier_version = active.version
            candidate.predicted_label = label
            candidate.predicted_dimension = DIMENSION_MAP[label]
            candidate.prediction_confidence = probs.get(label) if probs is not None else None
            candidate.prediction_probabilities = (
                {str(item): value for item, value in probs.items()}
                if probs is not None else None
            )
            candidate.classified_at = utc_now_naive()
            candidate.classification_status = "classified"
            candidate.prediction_source = (
                "remote_embedding" if feature_type == "remote_embedding" else "tfidf_production"
            )
            candidate.classification_error = ""
            db.add(ModelPredictionResult(
                run_id=run.id,
                candidate_id=candidate.id,
                input_text_hash=text_hash(candidate.clean_text.strip()),
                predicted_label=label,
                predicted_dimension=DIMENSION_MAP[label],
                prediction_confidence=candidate.prediction_confidence,
                prediction_probabilities=candidate.prediction_probabilities,
                top1_top2_gap=gap,
                low_confidence_reason=low_reason,
                needs_review=needs_review,
                inference_duration_ms=duration_ms,
            ))
        run.status = "completed"
        run.completed_at = utc_now_naive()
    except (EmbeddingProviderError, ValueError) as error:
        settings = get_settings()
        duration_ms = int((time.perf_counter() - started_monotonic) * 1000)
        if feature_type == "remote_embedding" and settings.EMBEDDING_FALLBACK_ENABLED:
            fallback = load_tfidf_fallback(settings)
            apply_tfidf_fallback(candidates, texts, fallback, active, error)
            run.engine = "tfidf_fallback"
            run.error_message = str(error)[:1000]
            run.status = "completed"
            run.completed_at = utc_now_naive()
            for candidate in candidates:
                db.add(ModelPredictionResult(
                    run_id=run.id,
                    candidate_id=candidate.id,
                    input_text_hash=text_hash(candidate.clean_text.strip()),
                    predicted_label=candidate.predicted_label,
                    predicted_dimension=candidate.predicted_dimension,
                    prediction_confidence=None,
                    prediction_probabilities=None,
                    top1_top2_gap=None,
                    low_confidence_reason="TF-IDF 降级分类",
                    needs_review=True,
                    inference_duration_ms=duration_ms,
                ))
        else:
            mark_pending_classification(candidates, error)
            run.status = "failed"
            run.error_message = str(error)[:1000]
            run.completed_at = utc_now_naive()
            raise
    await db.flush()
    return active
