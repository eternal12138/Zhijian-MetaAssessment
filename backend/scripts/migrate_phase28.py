"""Create the canonical expert-labelled dataset without replacing legacy coding data."""
from __future__ import annotations

from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


CODING_UNIT_COLUMNS = (
    ("audio_id", "VARCHAR(36) NULL AFTER task_id"),
    ("participant_id", "VARCHAR(36) NULL AFTER audio_id"),
    # Add text columns as nullable first so strict MySQL installations can
    # upgrade tables that already contain rows. They are made NOT NULL after
    # the deterministic backfill below.
    ("raw_text", "TEXT NULL AFTER segment"),
    ("clean_text", "TEXT NULL AFTER raw_text"),
    ("ai_label", "VARCHAR(32) NULL AFTER ai_dimension"),
)


def _exists(cursor, database: str, kind: str, table: str, name: str) -> bool:
    sources = {
        "column": ("information_schema.COLUMNS", "COLUMN_NAME"),
        "index": ("information_schema.STATISTICS", "INDEX_NAME"),
        "constraint": ("information_schema.TABLE_CONSTRAINTS", "CONSTRAINT_NAME"),
    }
    source, field = sources[kind]
    cursor.execute(
        f"SELECT COUNT(*) FROM {source} WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND {field}=%s",
        (database, table, name),
    )
    return bool(cursor.fetchone()[0])


def main() -> None:
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME,
        charset="utf8mb4", autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            for name, definition in CODING_UNIT_COLUMNS:
                if not _exists(cursor, settings.DB_NAME, "column", "coding_units", name):
                    cursor.execute(f"ALTER TABLE coding_units ADD COLUMN {name} {definition}")

            cursor.execute("""CREATE TABLE IF NOT EXISTS expert_annotations (
                id VARCHAR(36) PRIMARY KEY,
                segment_id VARCHAR(36) NOT NULL,
                expert_id VARCHAR(36) NOT NULL,
                reviewer_slot VARCHAR(1) NOT NULL,
                expert_label VARCHAR(32) NOT NULL,
                note TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_expert_segment_reviewer (segment_id, expert_id),
                UNIQUE KEY uq_expert_segment_slot (segment_id, reviewer_slot),
                INDEX ix_expert_segment_id (segment_id),
                INDEX ix_expert_expert_id (expert_id),
                INDEX ix_expert_label (expert_label),
                CONSTRAINT fk_expert_segment FOREIGN KEY (segment_id) REFERENCES coding_units(id) ON DELETE CASCADE,
                CONSTRAINT fk_expert_user FOREIGN KEY (expert_id) REFERENCES users(id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")

            for name, column in (
                ("ix_coding_units_audio_id", "audio_id"),
                ("ix_coding_units_participant_id", "participant_id"),
            ):
                if not _exists(cursor, settings.DB_NAME, "index", "coding_units", name):
                    cursor.execute(f"ALTER TABLE coding_units ADD INDEX {name} ({column})")
            for name, column, target in (
                ("fk_coding_units_audio", "audio_id", "asr_jobs"),
                ("fk_coding_units_participant", "participant_id", "users"),
            ):
                if not _exists(cursor, settings.DB_NAME, "constraint", "coding_units", name):
                    cursor.execute(
                        f"ALTER TABLE coding_units ADD CONSTRAINT {name} FOREIGN KEY ({column}) "
                        f"REFERENCES {target}(id) ON DELETE SET NULL"
                    )

            cursor.execute("""UPDATE coding_units cu
                LEFT JOIN extraction_candidates ec ON ec.id = cu.candidate_id
                SET cu.participant_id = COALESCE(cu.participant_id, ec.user_id),
                    cu.raw_text = CASE WHEN cu.raw_text IS NULL OR cu.raw_text = '' THEN COALESCE(ec.original_text, cu.segment) ELSE cu.raw_text END,
                    cu.clean_text = CASE WHEN cu.clean_text IS NULL OR cu.clean_text = '' THEN COALESCE(ec.clean_text, cu.segment) ELSE cu.clean_text END,
                    cu.ai_label = COALESCE(cu.ai_label, cu.ai_dimension)""")
            cursor.execute("ALTER TABLE coding_units MODIFY COLUMN raw_text TEXT NOT NULL")
            cursor.execute("ALTER TABLE coding_units MODIFY COLUMN clean_text TEXT NOT NULL")
            cursor.execute("""UPDATE coding_units cu
                SET cu.audio_id = COALESCE(cu.audio_id, (
                    SELECT aj.id FROM asr_jobs aj
                    WHERE aj.session_id = cu.session_id AND aj.canonical_audio_path IS NOT NULL
                    ORDER BY aj.finished_at DESC, aj.created_at DESC, aj.id DESC LIMIT 1
                ))""")
            cursor.execute("""INSERT IGNORE INTO expert_annotations
                (id, segment_id, expert_id, reviewer_slot, expert_label, note, created_at, updated_at)
                SELECT UUID(), legacy.unit_id, legacy.reviewer_id, legacy.reviewer_slot,
                    CASE legacy.dimension
                        WHEN 'NON_META' THEN 'non_metacognitive'
                        WHEN 'non_meta' THEN 'non_metacognitive'
                        WHEN 'MONITORING' THEN 'monitoring'
                        WHEN 'monitoring' THEN 'monitoring'
                        WHEN 'REGULATION' THEN 'regulation'
                        WHEN 'controlDebugging' THEN 'regulation'
                        WHEN 'EVALUATION' THEN 'legacy_evaluation'
                        WHEN 'evaluation' THEN 'legacy_evaluation'
                        ELSE legacy.dimension
                    END,
                    COALESCE(legacy.note, ''), legacy.created_at, legacy.created_at
                FROM coding_unit_annotations legacy
                WHERE legacy.dimension IS NOT NULL""")
            # Preserve historical decisions while normalizing labels that have
            # an exact semantic equivalent. Evaluation is intentionally kept as
            # legacy_evaluation and therefore cannot enter a four-class export
            # before an expert confirms a new label.
            cursor.execute("""UPDATE coding_unit_adjudications
                SET dimension = CASE dimension
                    WHEN 'NON_META' THEN 'non_metacognitive'
                    WHEN 'non_meta' THEN 'non_metacognitive'
                    WHEN 'MONITORING' THEN 'monitoring'
                    WHEN 'REGULATION' THEN 'regulation'
                    WHEN 'controlDebugging' THEN 'regulation'
                    WHEN 'EVALUATION' THEN 'legacy_evaluation'
                    WHEN 'evaluation' THEN 'legacy_evaluation'
                    ELSE dimension
                END""")
            cursor.execute("""UPDATE coding_units cu
                JOIN (
                    SELECT segment_id, COUNT(*) AS label_count,
                           MIN(expert_label) AS first_label,
                           MAX(expert_label) AS last_label
                    FROM expert_annotations
                    GROUP BY segment_id
                ) labels ON labels.segment_id = cu.id
                LEFT JOIN coding_unit_adjudications adj ON adj.unit_id = cu.id
                SET cu.status = CASE
                        WHEN adj.id IS NOT NULL THEN 'adjudicated'
                        WHEN labels.label_count = 1 THEN 'partially_coded'
                        WHEN labels.label_count >= 2 AND labels.first_label = labels.last_label THEN 'agreed'
                        ELSE 'disputed'
                    END,
                    cu.final_dimension = CASE
                        WHEN adj.id IS NOT NULL THEN adj.dimension
                        WHEN labels.label_count >= 2 AND labels.first_label = labels.last_label THEN labels.first_label
                        ELSE NULL
                    END,
                    cu.final_source = CASE
                        WHEN adj.id IS NOT NULL THEN 'third_party_adjudication'
                        WHEN labels.label_count >= 2 AND labels.first_label = labels.last_label THEN 'double_coder_consensus'
                        ELSE NULL
                    END""")
        connection.commit()
        print("Phase 28 expert dataset migration completed.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
