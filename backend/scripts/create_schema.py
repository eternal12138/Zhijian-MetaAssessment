"""Create the current SQLAlchemy schema in the configured database."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.models  # noqa: F401 - registers every model on Base.metadata
from app.database import Base, engine


async def create_schema() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_schema())
    print("Configured database schema is ready.", flush=True)
