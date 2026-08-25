"""Run the database-backed metacognitive candidate extraction worker."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import engine
from app.services import extraction_service, model_inference
from app.services.metacognition_extractor import extractor as extractor_module
from scripts.worker_runtime import IdleModuleReloader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("extraction-worker")


async def run(*, once: bool) -> None:
    reloader = IdleModuleReloader(
        paths=(
            BACKEND_ROOT / "app" / "services" / "metacognition_extractor" / "extractor.py",
            BACKEND_ROOT / "app" / "services" / "extraction_service.py",
            BACKEND_ROOT / "app" / "services" / "model_inference.py",
        ),
        modules=(extractor_module, model_inference, extraction_service),
        name="extraction-worker",
    )
    await extraction_service.requeue_stale_extraction_jobs()
    consecutive_errors = 0
    while True:
        try:
            reloader.reload_if_changed()
            job_id = await extraction_service.claim_next_extraction_job()
            if job_id is None:
                consecutive_errors = 0
                if once:
                    return
                await asyncio.sleep(2)
                continue
            logger.info("Processing extraction job %s", job_id)
            await extraction_service.process_extraction_job(job_id)
            consecutive_errors = 0
            if once:
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_errors += 1
            delay = min(30, 2 ** min(consecutive_errors, 5))
            logger.exception("Extraction worker loop failed; retrying in %ss", delay)
            if once:
                raise
            await asyncio.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    async def runner() -> None:
        try:
            await run(once=args.once)
        finally:
            await engine.dispose()

    asyncio.run(runner())


if __name__ == "__main__":
    main()
