import unittest

from app.models.notification import Notification
from app.services.notifications import create_notification


class NotificationRulesTest(unittest.IsolatedAsyncioTestCase):
    async def test_notification_rejects_external_target(self):
        with self.assertRaises(ValueError):
            await create_notification(
                None,
                user_id="user-1",
                type="system",
                title="Unsafe",
                content="Unsafe target",
                target_url="https://example.com",
            )

    def test_notification_metadata_uses_non_reserved_attribute(self):
        self.assertIn("metadata", Notification.__table__.c)
        self.assertTrue(hasattr(Notification, "extra_data"))


if __name__ == "__main__":
    unittest.main()
