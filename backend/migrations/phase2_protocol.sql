USE metacognition_db;

ALTER TABLE assessment_tasks
    ADD COLUMN protocol_order INT NOT NULL DEFAULT 0 AFTER requires_voice,
    ADD COLUMN stimulus_data JSON NULL AFTER protocol_order;

ALTER TABLE scale_items
    ADD COLUMN display_order INT NOT NULL DEFAULT 0 AFTER reversed;

CREATE TABLE assessment_runs (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    status ENUM('in_progress', 'completed', 'abandoned') NOT NULL DEFAULT 'in_progress',
    current_stage VARCHAR(32) NOT NULL DEFAULT 'device_check',
    protocol_version VARCHAR(32) NOT NULL DEFAULT '2026.1',
    consented_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    INDEX idx_assessment_runs_user_id (user_id),
    CONSTRAINT fk_assessment_runs_user
        FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE assessment_sessions
    ADD COLUMN run_id VARCHAR(36) NULL AFTER task_id,
    ADD COLUMN sequence_no INT NOT NULL DEFAULT 1 AFTER run_id,
    ADD INDEX idx_assessment_sessions_run_id (run_id),
    ADD CONSTRAINT fk_assessment_sessions_run
        FOREIGN KEY (run_id) REFERENCES assessment_runs(id);

CREATE TABLE questionnaire_responses (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    item_id VARCHAR(36) NOT NULL,
    value INT NOT NULL,
    answered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_questionnaire_run_item (run_id, item_id),
    CONSTRAINT fk_questionnaire_run
        FOREIGN KEY (run_id) REFERENCES assessment_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_questionnaire_user
        FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_questionnaire_item
        FOREIGN KEY (item_id) REFERENCES scale_items(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
