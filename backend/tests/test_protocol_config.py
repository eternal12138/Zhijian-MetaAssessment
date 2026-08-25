import unittest

from app.services.protocol_config import (
    DEFAULT_QUESTIONNAIRE_ENABLED,
    _decode,
)


class ProtocolConfigTests(unittest.TestCase):
    def test_default_keeps_questionnaire_disabled(self):
        self.assertFalse(DEFAULT_QUESTIONNAIRE_ENABLED)

    def test_decode_requires_explicit_json_true(self):
        self.assertTrue(_decode('{"questionnaire_enabled":true}'))
        self.assertFalse(_decode('{"questionnaire_enabled":false}'))
        self.assertFalse(_decode("{}"))
        self.assertFalse(_decode("invalid"))


if __name__ == "__main__":
    unittest.main()
