from __future__ import annotations

import argparse
import unittest

import numpy as np

from train_qwen_fc import fit_with_early_stopping, probability_matrix, sample_weights


class QwenFcTrainingTest(unittest.TestCase):
    def test_weighting_and_manual_early_stopping(self) -> None:
        rng = np.random.default_rng(42)
        labels = np.tile(np.arange(4, dtype=np.int64), 24)
        features = rng.normal(0, 0.25, size=(len(labels), 16)).astype(np.float32)
        for label in range(4):
            features[labels == label, label * 4:(label + 1) * 4] += 2.0
        train_index = np.concatenate([np.arange(label, 72, 4) for label in range(4)])
        validation_index = np.setdiff1d(np.arange(len(labels)), train_index)
        args = argparse.Namespace(
            hidden_units=12,
            max_epochs=20,
            patience=5,
            batch_size=16,
            learning_rate=0.005,
            alpha=0.0001,
        )
        weights = sample_weights(labels[train_index])
        self.assertEqual(weights.shape, (len(train_index),))
        model, best_epoch, history = fit_with_early_stopping(
            features[train_index], labels[train_index],
            features[validation_index], labels[validation_index], args, 42,
        )
        probabilities = probability_matrix(model, features[validation_index])
        self.assertGreaterEqual(best_epoch, 1)
        self.assertGreaterEqual(len(history), best_epoch)
        self.assertEqual(probabilities.shape, (len(validation_index), 4))
        np.testing.assert_allclose(probabilities.sum(axis=1), 1.0, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
