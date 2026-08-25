"""Run large research exports outside API request workers."""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import timedelta
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select, update

from app.schemas import research as research_schemas
from app.api import research as research_api
from app.core.time import utc_now_naive
from app.database import AsyncSessionLocal, engine
from app.models.research import ExportJob
from app.services import research_export
from scripts.worker_runtime import IdleModuleReloader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("export-worker")


async def requeue_stale_jobs() -> None:
    cutoff = utc_now_naive() - timedelta(minutes=30)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ExportJob)
            .where(
                ExportJob.export_type == "audio_transcript_zip",
                ExportJob.status.in_(("preparing", "running")),
                ExportJob.created_at < cutoff,
                ExportJob.completed_at.is_(None),
            )
            .values(status="queued", progress=0, error_message="")
        )
        await db.commit()


async def claim_next_job() -> tuple[str, str] | None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            job = await db.scalar(
                select(ExportJob)
                .where(
                    ExportJob.export_type == "audio_transcript_zip",
                    ExportJob.status == "queued",
                )
                .order_by(ExportJob.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            job.status = "preparing"
            job.progress = 1
            return job.id, job.requested_by


async def run(*, once: bool) -> None:
    reloader = IdleModuleReloader(
        paths=(
            BACKEND_ROOT / "app" / "services" / "research_export.py",
            BACKEND_ROOT / "app" / "api" / "research.py",
        ),
        modules=(research_schemas, research_export, research_api),
        name="export-worker",
    )
    await requeue_stale_jobs()
    consecutive_errors = 0
    while True:
        try:
            reloader.reload_if_changed()
            claimed = await claim_next_job()
            if claimed is None:
                consecutive_errors = 0
                if once:
                    return
                await asyncio.sleep(2)
                continue
            job_id, user_id = claimed
            logger.info("Processing export job %s", job_id)
            await research_api._run_audio_transcript_export(job_id, user_id)
            consecutive_errors = 0
            if once:
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_errors += 1
            delay = min(30, 2 ** min(consecutive_errors, 5))
            logger.exception("Export worker loop failed; retrying in %ss", delay)
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
