from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import engine
from app.services import embedding_provider, model_artifacts, model_metrics_service, model_training, model_training_datasets
from app.training import baseline_models, hyperparameters
from scripts.worker_runtime import IdleModuleReloader, source_revision as _source_revision

logging.basicConfig(level=logging.INFO)

WATCHED_SOURCES = (
    BACKEND_ROOT / "app" / "services" / "model_training.py",
    BACKEND_ROOT / "app" / "services" / "model_metrics_service.py",
    BACKEND_ROOT / "app" / "training" / "baseline_models.py",
    BACKEND_ROOT / "app" / "training" / "hyperparameters.py",
    BACKEND_ROOT / "app" / "services" / "model_training_datasets.py",
    BACKEND_ROOT / "app" / "services" / "embedding_provider.py",
    BACKEND_ROOT / "app" / "services" / "model_artifacts.py",
)


def source_revision(paths: tuple[Path, ...] = WATCHED_SOURCES) -> str:
    return _source_revision(paths)


async def run() -> None:
    reloader = IdleModuleReloader(
        paths=WATCHED_SOURCES,
        modules=(model_training_datasets, embedding_provider, model_artifacts, model_metrics_service, hyperparameters, baseline_models, model_training),
        name="model-training-worker",
    )
    recovered = await model_training.recover_stale_training_jobs()
    if recovered:
        logging.warning("Recovered %s stale model training jobs", recovered)
    while True:
        reloader.reload_if_changed()
        job_id = await model_training.claim_next_training_job()
        if not job_id:
            await asyncio.sleep(3)
            continue
        try:
            await model_training.process_training_job(job_id)
        except Exception:
            logging.exception("Model training job failed: %s", job_id)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    finally:
        asyncio.run(engine.dispose())
