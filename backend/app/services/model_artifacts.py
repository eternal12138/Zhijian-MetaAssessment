"""Safe loading and integrity validation for trained classifier artifacts."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import joblib

from app.config import Settings
from app.models.research import ModelTrainingJob

_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_FALLBACK_CACHE: dict[str, Any] = {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_model_artifact(job: ModelTrainingJob, settings: Settings) -> Path:
    if not job.artifact_path:
        raise ValueError("模型产物路径为空")
    root = settings.model_training_path.resolve()
    path = Path(job.artifact_path).resolve()
    if path != root and root not in path.parents:
        raise ValueError("模型产物路径超出允许的存储目录")
    if not path.is_file():
        raise ValueError("模型产物文件不存在")
    actual_hash = sha256_file(path)
    if not job.artifact_sha256 or actual_hash != job.artifact_sha256:
        raise ValueError("模型产物完整性校验失败")
    return path


def load_model_artifact(job: ModelTrainingJob, settings: Settings) -> dict[str, Any]:
    path = resolve_model_artifact(job, settings)
    cache_key = (str(path), job.artifact_sha256 or "")
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached
    payload = joblib.load(path)
    if not isinstance(payload, dict) or not {"scaler", "classifier", "embedding_model", "dimensions"}.issubset(payload):
        raise ValueError("模型产物结构不完整")
    if int(payload["dimensions"]) <= 0:
        raise ValueError("模型向量维度无效")
    _CACHE.clear()
    _CACHE[cache_key] = payload
    return payload


def load_tfidf_fallback(settings: Settings) -> Any:
    configured = settings.TFIDF_FALLBACK_MODEL_PATH.strip()
    if not configured:
        raise ValueError("TF-IDF fallback 模型路径未配置")
    root = settings.model_training_path.resolve()
    path = Path(configured)
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if path != root and root not in path.parents:
        raise ValueError("TF-IDF fallback 模型路径超出模型目录")
    if not path.is_file():
        raise ValueError("TF-IDF fallback 模型文件不存在")
    cache_key = str(path)
    cached = _FALLBACK_CACHE.get(cache_key)
    if cached is None:
        cached = joblib.load(path)
        if not hasattr(cached, "predict"):
            raise ValueError("TF-IDF fallback 产物不支持 predict")
        _FALLBACK_CACHE.clear()
        _FALLBACK_CACHE[cache_key] = cached
    return cached
