import unittest

from pydantic import ValidationError

from app.config import Settings
from app.schemas.model_services_config import ModelServicesConfigUpdate
from app.services.runtime_model_config import (
    load_runtime_model_settings,
    save_runtime_model_settings,
)


class FakeSession:
    def __init__(self):
        self.row = None

    async def get(self, model, key):
        del model, key
        return self.row

    def add(self, row):
        self.row = row

    async def flush(self):
        return None


def update_payload(**overrides):
    values = {
        "report_use_llm": True,
        "llm_base_url": "https://ark.example/api/v3",
        "llm_model": "ep-test",
        "llm_api_key": "ark-secret-value",
        "llm_temperature": 0.2,
        "llm_top_p": 0.9,
        "llm_max_tokens": 2048,
        "report_llm_timeout_seconds": 20,
        "qwen_embedding_base_url": "https://workspace.example/compatible-mode/v1",
        "qwen_embedding_model": "qwen3.7-text-embedding",
        "qwen_embedding_api_key": "qwen-secret-value",
        "qwen_embedding_dimensions": 1024,
        "qwen_embedding_batch_size": 20,
        "qwen_embedding_timeout_seconds": 60,
        "asr_provider": "volcengine",
        "volcengine_asr_api_key": "speech-secret-value",
        "volcengine_asr_app_id": "",
        "volcengine_asr_resource_id": "volc.seedasr.auc",
        "volcengine_asr_submit_url": "https://speech.example/submit",
        "volcengine_asr_query_url": "https://speech.example/query",
        "asr_public_base_url": "https://assessment.example",
        "asr_timeout_seconds": 180,
        "volcengine_asr_query_interval_seconds": 3,
        "volcengine_asr_max_wait_seconds": 600,
        "asr_audio_url_ttl_seconds": 600,
    }
    values.update(overrides)
    return ModelServicesConfigUpdate(**values)


class RuntimeModelConfigTest(unittest.IsolatedAsyncioTestCase):
    async def test_local_llm_http_url_is_allowed_for_development(self):
        payload = update_payload(llm_base_url="http://localhost:11434/v1")
        self.assertEqual(payload.llm_base_url, "http://localhost:11434/v1")

    async def test_remote_llm_http_url_is_rejected(self):
        with self.assertRaises(ValidationError):
            update_payload(llm_base_url="http://example.com/v1")

    async def test_secrets_are_encrypted_and_restored(self):
        db = FakeSession()
        settings = Settings(SECRET_KEY="runtime-config-test-secret", _env_file=None)

        view = await save_runtime_model_settings(
            update_payload(),
            db,
            settings,
        )

        self.assertTrue(view.llm_api_key_configured)
        self.assertTrue(view.qwen_embedding_api_key_configured)
        self.assertTrue(view.volcengine_asr_api_key_configured)
        self.assertFalse(view.volcengine_asr_access_key_configured)
        self.assertTrue(view.asr_audio_signing_secret_configured)
        self.assertNotIn("ark-secret-value", db.row.config_value)
        self.assertNotIn("speech-secret-value", db.row.config_value)
        self.assertNotIn("qwen-secret-value", db.row.config_value)

        restored = Settings(
            SECRET_KEY="runtime-config-test-secret",
            LLM_API_KEY="",
            VOLCENGINE_ASR_API_KEY="",
            ASR_AUDIO_SIGNING_SECRET="",
            QWEN_EMBEDDING_API_KEY="",
            _env_file=None,
        )
        await load_runtime_model_settings(db, restored)
        self.assertEqual(restored.LLM_API_KEY, "ark-secret-value")
        self.assertEqual(restored.VOLCENGINE_ASR_API_KEY, "speech-secret-value")
        self.assertEqual(restored.QWEN_EMBEDDING_API_KEY, "qwen-secret-value")
        self.assertTrue(restored.ASR_AUDIO_SIGNING_SECRET)

    async def test_legacy_asr_credentials_and_worker_settings_are_persisted(self):
        db = FakeSession()
        settings = Settings(
            SECRET_KEY="runtime-config-test-secret",
            VOLCENGINE_ASR_API_KEY="",
            _env_file=None,
        )

        view = await save_runtime_model_settings(
            update_payload(
                volcengine_asr_api_key=None,
                volcengine_asr_auth_mode="legacy",
                volcengine_asr_app_id="legacy-app-id",
                volcengine_asr_access_key="legacy-access-secret",
                asr_model="bigmodel",
                asr_language="zh-CN",
                asr_max_retries=5,
                asr_config_version="2026.2",
                asr_poll_interval_seconds=1.5,
            ),
            db,
            settings,
        )

        self.assertEqual(view.volcengine_asr_app_id, "legacy-app-id")
        self.assertEqual(view.volcengine_asr_auth_mode, "legacy")
        self.assertTrue(view.volcengine_asr_access_key_configured)
        self.assertNotIn("legacy-access-secret", db.row.config_value)
        self.assertEqual(settings.ASR_MODEL, "bigmodel")
        self.assertEqual(settings.ASR_MAX_RETRIES, 5)
        self.assertEqual(settings.ASR_CONFIG_VERSION, "2026.2")
        self.assertEqual(settings.ASR_POLL_INTERVAL_SECONDS, 1.5)

    async def test_blank_secret_preserves_existing_value(self):
        db = FakeSession()
        settings = Settings(SECRET_KEY="runtime-config-test-secret", _env_file=None)
        await save_runtime_model_settings(update_payload(), db, settings)

        await save_runtime_model_settings(
            update_payload(
                llm_api_key=None,
                volcengine_asr_api_key=None,
            ),
            db,
            settings,
        )

        self.assertEqual(settings.LLM_API_KEY, "ark-secret-value")
        self.assertEqual(
            settings.VOLCENGINE_ASR_API_KEY,
            "speech-secret-value",
        )


if __name__ == "__main__":
    unittest.main()
