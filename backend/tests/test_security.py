import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import BigInteger

from app.api.auth import register, skip_password_change
from app.config import Settings
from app.core.security import can_access_user, decode_token, is_password_action_path
from app.models.session import DialogueTurn
from app.models.user import User
from app.schemas.user import UserCreate


def make_user(
    user_id: str,
    role: str,
    class_group: str | None = None,
    managed_classes: str | None = None,
) -> User:
    return User(
        id=user_id,
        username=user_id,
        password_hash="unused",
        name=user_id,
        role=role,
        avatar_text="测",
        class_group=class_group,
        managed_classes=managed_classes,
        is_active=True,
        can_manage_users=False,
    )


class SecurityRulesTest(unittest.IsolatedAsyncioTestCase):
    def test_production_cannot_disable_rate_limiting(self):
        with self.assertRaises(ValueError):
            Settings(
                APP_DEBUG=False,
                RATE_LIMIT_ENABLED=False,
                ENABLE_API_DOCS=False,
                SECRET_KEY="a-secure-production-secret-that-is-long-enough",
                CORS_ORIGINS="https://example.com",
                TRUSTED_HOSTS="example.com",
                DB_USER="metacognition_app",
                DB_PASSWORD="secure-database-password",
                AUDIO_UPLOAD_DIR="/data/audio",
                RESEARCH_EXPORT_DIR="/data/exports",
                MODEL_TRAINING_DIR="/data/models",
            )

    async def test_public_registration_is_disabled_by_default(self):
        payload = UserCreate(
            username="new-admin",
            password="password123",
            name="New Admin",
            role="admin",
        )
        with self.assertRaises(HTTPException) as context:
            await register(payload, db=None)
        self.assertEqual(context.exception.status_code, 403)

    async def test_skipping_password_change_only_defers_current_token(self):
        user = make_user("student-default-password", "student")
        user.must_change_password = True
        user.token_version = 0

        response = await skip_password_change(db=None, current_user=user)
        payload = decode_token(response.access_token)

        self.assertTrue(user.must_change_password)
        self.assertIsNotNone(payload)
        self.assertTrue(payload["password_change_deferred"])

    def test_password_actions_work_with_or_without_api_proxy_prefix(self):
        self.assertTrue(
            is_password_action_path("/api/auth/skip-password-change")
        )
        self.assertTrue(
            is_password_action_path("/auth/skip-password-change")
        )
        self.assertFalse(is_password_action_path("/api/admin/users"))

    def test_teacher_can_only_access_students_in_managed_classes(self):
        teacher = make_user(
            "teacher-1",
            "teacher",
            managed_classes="Class-A,Class-B",
        )
        managed_student = make_user("student-1", "student", class_group="Class-A")
        other_student = make_user("student-2", "student", class_group="Class-C")
        admin = make_user("admin-1", "admin")

        self.assertTrue(can_access_user(teacher, managed_student))
        self.assertFalse(can_access_user(teacher, other_student))
        self.assertFalse(can_access_user(teacher, admin))

    def test_production_rejects_default_secret(self):
        with self.assertRaises(ValidationError):
            Settings(
                APP_DEBUG=False,
                SECRET_KEY="dev-secret-change-in-production",
                _env_file=None,
            )

    def test_production_requires_closed_docs_and_absolute_storage(self):
        common = {
            "APP_DEBUG": False,
            "SECRET_KEY": "a" * 64,
            "DB_USER": "metacognition_app",
            "CORS_ORIGINS": "https://meta.example.com",
            "TRUSTED_HOSTS": "meta.example.com,backend",
            "_env_file": None,
        }
        with self.assertRaises(ValidationError):
            Settings(
                **common,
                ENABLE_API_DOCS=True,
                AUDIO_UPLOAD_DIR="/data/audio",
                RESEARCH_EXPORT_DIR="/data/exports",
            )
        with self.assertRaises(ValidationError):
            Settings(
                **common,
                ENABLE_API_DOCS=False,
                AUDIO_UPLOAD_DIR="relative/audio",
                RESEARCH_EXPORT_DIR="/data/exports",
            )

    def test_production_accepts_explicit_secure_settings(self):
        settings = Settings(
            APP_DEBUG=False,
            ENABLE_API_DOCS=False,
            SECRET_KEY="a" * 64,
            DB_USER="metacognition_app",
            DB_PASSWORD="database-password",
            CORS_ORIGINS="https://www.example.com",
            TRUSTED_HOSTS="www.example.com,backend",
            AUDIO_UPLOAD_DIR="/data/audio",
            RESEARCH_EXPORT_DIR="/data/exports",
            MODEL_TRAINING_DIR="/data/models",
            _env_file=None,
        )
        self.assertFalse(settings.APP_DEBUG)

    def test_production_rejects_placeholder_volcengine_credentials(self):
        with self.assertRaises(ValidationError):
            Settings(
                APP_DEBUG=False,
                ENABLE_API_DOCS=False,
                SECRET_KEY="a" * 64,
                DB_USER="metacognition_app",
                DB_PASSWORD="database-password",
                CORS_ORIGINS="https://www.example.com",
                TRUSTED_HOSTS="www.example.com,backend",
                AUDIO_UPLOAD_DIR="/data/audio",
                RESEARCH_EXPORT_DIR="/data/exports",
                ASR_PROVIDER="volcengine",
                ASR_PUBLIC_BASE_URL="https://www.example.com",
                ASR_AUDIO_SIGNING_SECRET="CHANGE_ME_" + "s" * 64,
                VOLCENGINE_ASR_API_KEY="CHANGE_ME_VOLCENGINE_ASR_API_KEY",
                _env_file=None,
            )

    def test_database_url_encodes_password_metacharacters(self):
        settings = Settings(
            DB_PASSWORD="p@ss:/?# value",
            _env_file=None,
        )
        self.assertIn("p%40ss%3A%2F%3F%23+value", settings.database_url)

    def test_dialogue_timestamp_uses_big_integer(self):
        column_type = DialogueTurn.__table__.c.timestamp.type
        self.assertIsInstance(column_type, BigInteger)


if __name__ == "__main__":
    unittest.main()
