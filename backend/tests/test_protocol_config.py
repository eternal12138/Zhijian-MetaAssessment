import unittest

from app.services.protocol_config import (
    DEFAULT_QUESTIONNAIRE_ENABLED,
    _decode,
)


class ProtocolConfigTests(unittest.TestCase):
    def test_default_keeps_questionnaire_disabled(self):
        self.assertFalse(DEFAULT_QUESTIONNAIRE_ENABLED)

    def test_decode_requires_explicit_json_true(self):
        self.assertEqual(_decode('{"questionnaire_enabled":true}'), (True, 0.6, 0.4))
        self.assertEqual(_decode('{"questionnaire_enabled":false}'), (False, 0.6, 0.4))
        self.assertEqual(_decode('{"questionnaire_enabled":true,"behavior_weight":0.7,"questionnaire_weight":0.3}'), (True, 0.7, 0.3))
        self.assertEqual(_decode("{}"), (False, 0.6, 0.4))
        self.assertEqual(_decode("invalid"), (False, 0.6, 0.4))


if __name__ == "__main__":
    unittest.main()
