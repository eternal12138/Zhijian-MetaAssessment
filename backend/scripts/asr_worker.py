"""Run the database-backed ASR worker."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.database import engine
from app.services import asr_provider, asr_service, audio_processor
from scripts.worker_runtime import IdleModuleReloader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("asr-worker")


async def run(*, once: bool) -> None:
    settings = get_settings()
    reloader = IdleModuleReloader(
        paths=(
            BACKEND_ROOT / "app" / "services" / "asr_provider.py",
            BACKEND_ROOT / "app" / "services" / "audio_processor.py",
            BACKEND_ROOT / "app" / "services" / "asr_service.py",
        ),
        modules=(asr_provider, audio_processor, asr_service),
        name="asr-worker",
    )
    consecutive_errors = 0
    loop = asyncio.get_running_loop()
    last_recovery_scan = loop.time()
    try:
        recovered = await asr_service.requeue_stale_jobs()
        missing = await asr_service.recover_missing_asr_jobs()
        if recovered:
            logger.warning("Recovered %s interrupted ASR job(s)", recovered)
        if missing:
            logger.warning("Created %s missing ASR job(s)", missing)
    except Exception:
        logger.exception("Failed to recover interrupted ASR jobs; worker will continue")
    while True:
        try:
            reloader.reload_if_changed()
            if loop.time() - last_recovery_scan >= 60:
                recovered = await asr_service.requeue_stale_jobs()
                missing = await asr_service.recover_missing_asr_jobs()
                last_recovery_scan = loop.time()
                if recovered:
                    logger.warning("Recovered %s stale ASR job(s)", recovered)
                if missing:
                    logger.warning("Created %s missing ASR job(s)", missing)
            job_id = await asr_service.claim_next_asr_job()
            if job_id is None:
                consecutive_errors = 0
                if once:
                    return
                await asyncio.sleep(settings.ASR_POLL_INTERVAL_SECONDS)
                continue
            logger.info("Processing ASR job %s", job_id)
            await asr_service.process_asr_job(job_id)
            consecutive_errors = 0
            if once:
                return
            await asyncio.sleep(settings.ASR_POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_errors += 1
            delay = min(30.0, max(
                settings.ASR_POLL_INTERVAL_SECONDS,
                2 ** min(consecutive_errors, 5),
            ))
            logger.exception(
                "ASR worker loop failed; retrying in %.1f seconds (attempt %s)",
                delay,
                consecutive_errors,
            )
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
