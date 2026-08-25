from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from .constants import LABELS
from .remote import config_from_environment, create_embeddings

BACKEND_ROOT = Path(__file__).parents[2] / "backend"
import sys
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
from app.services.embedding_provider import assert_embedding_identity


@lru_cache(maxsize=8)
def _load_artifact(model_directory: str) -> tuple[Any, dict[str, Any]]:
    directory = Path(model_directory)
    model = joblib.load(directory / "model.joblib")
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    return model, config


def predict_metacognition(
    text: str,
    *,
    model_name: str = "tfidf_linear_svc",
    models_root: str | Path = Path("research") / "baseline_output" / "models",
) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("text must not be empty")
    directory = Path(models_root).expanduser().resolve() / model_name
    model, config = _load_artifact(str(directory))
    if config.get("feature") == "remote_embedding":
        runtime_embedding = config_from_environment()
        assert_embedding_identity(config.get("embedding_config") or {}, runtime_embedding)
        features, _ = create_embeddings(
            [cleaned], config=runtime_embedding,
            cache_path=Path(models_root).expanduser().resolve().parent / "cache" / "remote_embeddings.sqlite3",
        )
    elif config.get("feature") == "TF-IDF":
        features = [cleaned]
    else:
        raise RuntimeError(f"unsupported production feature: {config.get('feature')}")
    label = str(model.predict(features)[0])
    if label not in LABELS:
        raise RuntimeError(f"model returned an unsupported label: {label}")
    confidence: float | None = None
    if hasattr(model, "predict_proba"):
        probabilities = np.asarray(model.predict_proba(features))[0]
        confidence = float(np.max(probabilities))
    return {
        "label": label,
        "confidence": confidence,
        "model_name": model_name,
        "model_version": config.get("model_version"),
        "embedding_model": config.get("embedding_model"),
        "prediction_source": "remote_embedding" if config.get("feature") == "remote_embedding" else "tfidf",
    }
