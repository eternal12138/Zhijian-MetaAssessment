"""Add immutable administrator dialogue corrections without changing ASR data."""
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from app.config import get_settings
from app.models.report import MeasurementCorrection


def main():
    settings = get_settings()
    engine = create_engine(URL.create(
        "mysql+pymysql", username=settings.DB_USER, password=settings.DB_PASSWORD,
        host=settings.DB_HOST, port=settings.DB_PORT, database=settings.DB_NAME,
        query={"charset": "utf8mb4"},
    ))
    try:
        MeasurementCorrection.__table__.create(engine, checkfirst=True)
    finally:
        engine.dispose()
    print("Phase 34 administrator measurement corrections are ready.")


if __name__ == "__main__":
    main()
