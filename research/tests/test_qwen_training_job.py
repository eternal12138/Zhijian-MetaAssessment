from __future__ import annotations

import unittest

from run_qwen_training_job import normalized_version


class QwenTrainingJobTest(unittest.TestCase):
    def test_accepts_safe_version_names(self) -> None:
        self.assertEqual(normalized_version("gold-v2.1"), "gold-v2.1")

    def test_rejects_unsafe_version_names(self) -> None:
        for value in ("../v2", "v2/next", "版本 2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalized_version(value)


if __name__ == "__main__":
    unittest.main()
