"""Create versioned model-training jobs and reusable embedding cache."""
from __future__ import annotations

from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    connection = pymysql.connect(host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER, password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4", autocommit=False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("""CREATE TABLE IF NOT EXISTS model_training_jobs (
                id VARCHAR(36) PRIMARY KEY, version VARCHAR(64) NOT NULL UNIQUE,
                status VARCHAR(24) NOT NULL DEFAULT 'queued', stage VARCHAR(32) NOT NULL DEFAULT 'queued', progress INT NOT NULL DEFAULT 0,
                requested_by VARCHAR(36) NOT NULL, sample_count INT NOT NULL DEFAULT 0,
                label_distribution JSON NULL, dataset_fingerprint VARCHAR(64) NULL,
                config_snapshot JSON NULL, metrics JSON NULL, artifact_path VARCHAR(512) NULL,
                is_active BOOLEAN NOT NULL DEFAULT FALSE, activated_by VARCHAR(36) NULL, activated_at DATETIME NULL,
                error_message TEXT NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at DATETIME NULL, completed_at DATETIME NULL,
                INDEX ix_training_status (status), INDEX ix_training_created (created_at), INDEX ix_training_active (is_active),
                CONSTRAINT fk_training_requested_by FOREIGN KEY (requested_by) REFERENCES users(id),
                CONSTRAINT fk_training_activated_by FOREIGN KEY (activated_by) REFERENCES users(id) ON DELETE SET NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS text_embedding_cache (
                cache_key VARCHAR(64) PRIMARY KEY, text_hash VARCHAR(64) NOT NULL,
                model VARCHAR(200) NOT NULL, dimensions INT NOT NULL, vector LONGBLOB NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX ix_embedding_text_hash (text_hash)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")
        connection.commit()
        print("Phase 26 model training schema is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
