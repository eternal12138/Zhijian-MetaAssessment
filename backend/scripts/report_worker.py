"""One lightweight report worker; no embedding/ASR model is loaded."""
import argparse
import asyncio
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import engine
from app.services.report_jobs import claim_report_job, process_report_job

async def run(once=False):
    while True:
        try:
            job_id = await claim_report_job()
            if job_id:
                await process_report_job(job_id)
            elif not once:
                await asyncio.sleep(3)
            if once:
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Report queue failed; retrying")
            if once:
                raise
            await asyncio.sleep(10)

async def main(once):
    try:
        await run(once)
    finally:
        await engine.dispose()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(parser.parse_args().once))
