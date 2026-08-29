"""Add nullable report provenance/queue columns; never invent historical metadata."""
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from app.config import get_settings
from app.models.report import ReportRevision

COLUMNS = {
    "metacognitive_profiles": {"evidence_snapshot": "JSON NULL", "generation_metadata": "JSON NULL"},
    "analysis_jobs": {"active_run_id": "VARCHAR(36) NULL", "running_slot": "INTEGER NULL",
                      "payload": "JSON NULL", "heartbeat_at": "DATETIME NULL"},
}

def upgrade(engine):
    with engine.begin() as connection:
        for table, columns in COLUMNS.items():
            existing = {c["name"] for c in inspect(connection).get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
        inspector = inspect(connection)
        unique_columns = {tuple(i["column_names"]) for i in inspector.get_indexes("analysis_jobs") if i.get("unique")}
        unique_columns.update(tuple(i["column_names"]) for i in inspector.get_unique_constraints("analysis_jobs"))
        for column in ("active_run_id", "running_slot"):
            if (column,) not in unique_columns:
                connection.execute(text(f"CREATE UNIQUE INDEX uq_analysis_{column} ON analysis_jobs ({column})"))
        # Pre-queue jobs have no recoverable input snapshot; do not silently rerun AI.
        connection.execute(text("""UPDATE analysis_jobs SET status='failed',
            error_message='旧版报告任务未完成，请重新提交；原草稿已保留'
            WHERE status IN ('queued','running') AND payload IS NULL"""))
    ReportRevision.__table__.create(engine, checkfirst=True)
    # Do not replace the administrator's active prompt or edit prior versions.
    if "method_templates" in inspect(engine).get_table_names():
        from app.services.report_prompt_v2 import CONTENT, VERSION
        with engine.begin() as connection:
            exists = connection.scalar(text("SELECT id FROM method_templates WHERE template_key='report_prompt' AND version=:v"), {"v":VERSION})
            if not exists:
                connection.execute(text("""INSERT INTO method_templates
                    (id,template_key,version,kind,content,is_active) VALUES (:id,'report_prompt',:v,'prompt',:content,0)"""),
                    {"id":str(uuid.uuid4()), "v":VERSION, "content":CONTENT})

def main():
    settings = get_settings()
    engine = create_engine(URL.create("mysql+pymysql", username=settings.DB_USER, password=settings.DB_PASSWORD,
        host=settings.DB_HOST, port=settings.DB_PORT, database=settings.DB_NAME, query={"charset":"utf8mb4"}))
    try:
        upgrade(engine)
    finally:
        engine.dispose()
    print("Phase 35 report snapshots and durable generation queue are ready.")

if __name__ == "__main__":
    main()
