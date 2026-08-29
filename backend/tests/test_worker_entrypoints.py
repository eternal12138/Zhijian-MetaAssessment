from __future__ import annotations

import unittest

from scripts import asr_worker, export_worker, extraction_worker, model_training_worker, report_worker


class WorkerEntrypointTests(unittest.TestCase):
    def test_all_background_workers_expose_runnable_entrypoints(self):
        for worker in (asr_worker, extraction_worker, export_worker, model_training_worker, report_worker):
            with self.subTest(worker=worker.__name__):
                self.assertTrue(callable(worker.run))


if __name__ == "__main__":
    unittest.main()
