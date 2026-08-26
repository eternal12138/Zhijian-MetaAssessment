from pathlib import Path
import unittest

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DeploymentConfigTests(unittest.TestCase):
    def test_backend_image_uses_domestic_debian_mirror(self):
        dockerfile = (PROJECT_ROOT / "backend" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn("https://mirrors.aliyun.com/debian", dockerfile)
        self.assertIn("Acquire::Retries=3", dockerfile)

    def test_backend_image_uses_domestic_python_mirror(self):
        dockerfile = (PROJECT_ROOT / "backend" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn("https://mirrors.aliyun.com/pypi/simple/", dockerfile)
        self.assertIn("PIP_DEFAULT_TIMEOUT=120", dockerfile)
        self.assertIn("python -m pip install --retries 5", dockerfile)
        self.assertNotIn("python -m pip install --upgrade pip", dockerfile)

    @classmethod
    def setUpClass(cls):
        cls.compose = yaml.safe_load(
            (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
        )

    def test_migrations_keep_ddl_privileges_across_redeployments(self):
        database_service = self.compose["services"]["db"]
        environment = self.compose["services"]["migrate"]["environment"]

        self.assertEqual(database_service["environment"]["MYSQL_ROOT_HOST"], "%")
        self.assertNotIn("ports", database_service)
        self.assertEqual(environment["DB_USER"], "root")
        self.assertEqual(environment["DB_PASSWORD"], "${MYSQL_ROOT_PASSWORD}")
        self.assertEqual(environment["APP_DEBUG"], "true")
        setup_script = (
            PROJECT_ROOT / "backend" / "scripts" / "setup_production.py"
        ).read_text(encoding="utf-8")
        self.assertIn('run(scripts_dir / "create_schema.py")', setup_script)

    def test_runtime_backend_keeps_the_least_privileged_database_user(self):
        environment = self.compose["services"]["backend"]["environment"]

        self.assertNotIn("DB_USER", environment)
        self.assertNotIn("DB_PASSWORD", environment)
        self.assertEqual(
            self.compose["services"]["backend"]["env_file"],
            [".env.production"],
        )

    def test_audio_and_exports_are_persistent_for_backend_and_worker(self):
        expected_volumes = {
            "${DATA_DIR}/audio:/data/audio",
            "${DATA_DIR}/exports:/data/exports",
        }
        for service_name in ("backend", "asr-worker"):
            volumes = set(self.compose["services"][service_name]["volumes"])
            self.assertTrue(expected_volumes.issubset(volumes))

    def test_public_container_port_is_bound_to_loopback(self):
        self.assertEqual(
            self.compose["services"]["frontend"]["ports"],
            ["127.0.0.1:8080:80"],
        )

    def test_review_audio_proxy_preserves_seekable_streaming(self):
        nginx = (PROJECT_ROOT / "frontend" / "nginx.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "/api/research/extraction/sessions/[A-Za-z0-9-]+/audio-stream",
            nginx,
        )
        self.assertIn("proxy_set_header Range $http_range", nginx)
        self.assertIn("proxy_set_header If-Range $http_if_range", nginx)
        self.assertIn("proxy_force_ranges on", nginx)
        self.assertIn("proxy_buffering off", nginx)

    def test_optional_questionnaire_migration_runs_locally_and_in_production(self):
        migration_name = "migrate_phase10.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")

        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)

    def test_questionnaire_version_migration_runs_locally_and_in_production(self):
        migration_name = "migrate_phase11.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn("groups_by_dimension", migration)
        self.assertIn("NOT EXISTS", migration)
        self.assertIn("questionnaire_responses", migration)

    def test_blinded_coding_migration_runs_locally_and_in_production(self):
        migration_name = "migrate_phase12.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn("coding_batches", migration)
        self.assertIn("coding_units", migration)
        self.assertIn("coding_unit_annotations", migration)
        self.assertIn("coding_unit_adjudications", migration)

    def test_expert_dataset_migration_runs_locally_and_in_production(self):
        migration_name = "migrate_phase28.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")

        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("expert_annotations", migration)
        self.assertIn("raw_text", migration)
        self.assertIn("clean_text", migration)
        self.assertIn("ai_label", migration)

    def test_coding_scope_migration_runs_locally_and_in_production(self):
        migration_name = "migrate_phase13.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn("scope_filter", migration)
        self.assertIn("scope_summary", migration)

    def test_embedding_runtime_migration_runs_locally_and_in_production(self):
        migration_name = "migrate_phase29.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")

        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("classification_status", migration)
        self.assertIn("prediction_source", migration)
        self.assertIn("model_version", migration)
        self.assertIn("information_schema.COLUMNS", migration)

    def test_human_narration_migration_runs_locally_and_in_production(self):
        migration_name = "migrate_phase14.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn("narration_assets", migration)
        self.assertIn("narration_snapshot", migration)

    def test_narration_recordings_use_the_persistent_audio_volume(self):
        narration_api = (
            PROJECT_ROOT / "backend" / "app" / "api" / "narrations.py"
        ).read_text(encoding="utf-8")
        self.assertIn("settings.audio_upload_path", narration_api)
        self.assertIn('relative_path = f"narrations/', narration_api)

    def test_task_wording_migration_runs_locally_and_in_production(self):
        migration_name = "migrate_phase15.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("哪台投球机表现最优", migration)
        self.assertIn("设计并说明一种合理的数学程序", migration)
        self.assertIn("脑海中实时产生的所有想法", migration)
        self.assertIn("四台投球机落点与距离分布图", migration)
        self.assertIn("QUESTIONNAIRE_NARRATION", migration)
        self.assertIn("disabled_stale_narrations", migration)
        self.assertIn("哪位运动员表现最优", migration)
        self.assertIn("表2给出了2000年跳高和跳远最佳成绩", migration)
        self.assertNotIn("表 A1", migration)
        self.assertIn("narration_assets", migration)
        self.assertIn("task-001-default", migration)
        self.assertIn("task-pitching-2026-2", migration)

    def test_questionnaire_participant_name_migration_runs_everywhere(self):
        migration_name = "migrate_phase18.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        research_api = (
            PROJECT_ROOT / "backend" / "app" / "api" / "research.py"
        ).read_text(encoding="utf-8")

        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("questionnaire_participant_name", migration)
        self.assertIn("AFTER questionnaire_source", migration)
        self.assertIn(
            '"姓名", "问卷填写姓名（实验路径/微信名）", "账号"',
            research_api,
        )

    def test_candidate_extraction_worker_and_migration_are_deployable(self):
        migration_name = "migrate_phase20.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("extraction-worker:", compose)
        self.assertIn('scripts/extraction_worker.py', compose)
        self.assertIn("COLLATE=utf8mb4_unicode_ci", migration)

    def test_candidate_review_lease_migration_runs_locally_and_in_production(self):
        migration_name = "migrate_phase21.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("review_lock_expires_at", migration)
        self.assertIn("fk_extraction_job_review_lock_user", migration)

    def test_extraction_provenance_migration_runs_locally_and_in_production(self):
        migration_name = "migrate_phase22.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("generation_no", migration)
        self.assertIn("extraction_candidate_revisions", migration)
        self.assertIn("ON DELETE CASCADE", migration)

    def test_performance_indexes_run_locally_and_in_production(self):
        migration_name = "migrate_phase23.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("ix_transcript_authoritative_latest", migration)
        self.assertIn("ix_candidate_job_status", migration)

    def test_report_notification_repair_runs_locally_and_in_production(self):
        migration_name = "migrate_phase24.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("现在可以生成个人报告", migration)
        self.assertIn("报告复核处理中", migration)

    def test_export_acceleration_migration_and_worker_are_deployable(self):
        migration_name = "migrate_phase25.py"
        migrate_all = (
            PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py"
        ).read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
        migration = (
            PROJECT_ROOT / "backend" / "scripts" / migration_name
        ).read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("export-worker:", compose)
        self.assertIn('scripts/export_worker.py', compose)
        self.assertIn("audio_sha256", migration)
        self.assertIn("dataset_fingerprint", migration)

    def test_observable_model_lifecycle_migration_runs_everywhere(self):
        migration_name = "migrate_phase27.py"
        migrate_all = (PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py").read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (PROJECT_ROOT / "backend" / "scripts" / migration_name).read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("artifact_sha256", migration)
        self.assertIn("prediction_probabilities", migration)

    def test_training_fold_progress_migration_runs_everywhere(self):
        migration_name = "migrate_phase30.py"
        migrate_all = (PROJECT_ROOT / "backend" / "scripts" / "migrate_all.py").read_text(encoding="utf-8")
        dev_script = (PROJECT_ROOT / "dev.ps1").read_text(encoding="utf-8")
        migration = (PROJECT_ROOT / "backend" / "scripts" / migration_name).read_text(encoding="utf-8")
        self.assertIn(migration_name, migrate_all)
        self.assertIn(migration_name, dev_script)
        self.assertIn("current_fold", migration)
        self.assertIn("total_folds", migration)
        self.assertIn("heartbeat_at", migration)
        self.assertIn("estimated_remaining_seconds", migration)

    def test_model_storage_is_persistent_and_writable_before_migrations(self):
        compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
        deploy = (PROJECT_ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        dockerignore = (PROJECT_ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("storage-permissions:", compose)
        self.assertIn("${DATA_DIR}/models:/data/models", compose)
        self.assertIn("/data/models/datasets", compose)
        self.assertIn('${DATA_DIR}/models/datasets', deploy)
        self.assertIn("models", dockerignore.splitlines())

    def test_macro_analytics_never_falls_back_to_demo_research_results(self):
        backend = (PROJECT_ROOT / "backend" / "app" / "api" / "research.py").read_text(
            encoding="utf-8"
        )
        frontend = (
            PROJECT_ROOT / "frontend" / "src" / "components" / "dashboard"
            / "MacroAnalyticsDashboard.vue"
        ).read_text(encoding="utf-8")
        macro_endpoint = backend.split('@router.get("/macro-analytics")', 1)[1]
        for fabricated_value in ("75.0", "71.2", "68.5", "248, 194, 162", "99.85%", "t = 0.428"):
            self.assertNotIn(fabricated_value, macro_endpoint)
        self.assertIn("profile.dimension_details", macro_endpoint)
        self.assertIn("can_access_user(user, owner)", macro_endpoint)
        self.assertNotIn("实验1班", frontend)
        self.assertNotIn("全校常模", frontend)
        self.assertIn("缺失数据不会使用演示值填充", frontend)


if __name__ == "__main__":
    unittest.main()
