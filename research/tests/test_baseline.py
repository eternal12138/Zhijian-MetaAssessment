from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.linear_model import LogisticRegression

from research.baseline.constants import LABELS
from research.baseline.data import LoadedDataset, DatasetSchema, assert_trainable
from research.baseline.inference import _load_artifact, predict_metacognition
from research.baseline.remote import create_embeddings
from research.baseline.split import split_dataset
from research.baseline.training import build_tfidf_pipeline
from app.services.embedding_provider import EmbeddingCall, EmbeddingConfig, EmbeddingProvider


class FakeRemoteProvider(EmbeddingProvider):
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.calls = 0

    async def embed(self, texts: list[str]) -> EmbeddingCall:
        self.calls += 1
        vectors = np.asarray([[len(text), text.count("我")] for text in texts], dtype=np.float32)
        return EmbeddingCall(vectors, (1.0,), 1, 0, (len(texts),))

    async def close(self) -> None:
        return None


def embedding_config() -> EmbeddingConfig:
    return EmbeddingConfig(
        provider="mock", model="embedding-v1", version="test-1", dimensions=2,
        base_url="https://embedding.example/v1", api_key="secret", normalized=False,
    )


def synthetic_frame() -> pd.DataFrame:
    rows = []
    for group in range(10):
        for index, label in enumerate(LABELS):
            rows.append({
                "_segment_id": f"s-{group}-{index}",
                "_group_id": f"u-{group}",
                "_audio_id": f"a-{group}",
                "_text": f"我正在处理第{group}组的{label}想法 {index}",
                "_label": label,
                "_raw_label": label,
            })
    return pd.DataFrame(rows)


class BaselineTests(unittest.TestCase):
    def test_labels_are_legal_and_complete(self):
        frame = synthetic_frame()
        dataset = LoadedDataset(
            frame, DatasetSchema("_text", "_raw_label", "_segment_id", "_group_id", "_audio_id"),
            Path("synthetic.csv"), "synthetic-v1",
        )
        assert_trainable(dataset)
        self.assertEqual(set(frame["_label"]), set(LABELS))

    def test_group_split_has_no_subject_overlap(self):
        frame = synthetic_frame()
        split = split_dataset(frame)
        train_groups = set(frame.iloc[split.train_indices]["_group_id"])
        test_groups = set(frame.iloc[split.test_indices]["_group_id"])
        self.assertFalse(train_groups & test_groups)

    def test_tfidf_pipeline_trains(self):
        frame = synthetic_frame()
        model = build_tfidf_pipeline().fit(frame["_text"], frame["_label"])
        self.assertIn(model.predict(["我检查现在的理解"])[0], LABELS)

    def test_remote_encoder_produces_dense_embeddings(self):
        config = embedding_config()
        provider = FakeRemoteProvider(config)
        with tempfile.TemporaryDirectory() as temporary:
            embeddings, metrics = create_embeddings(
                ["一", "两个"], config=config,
                cache_path=Path(temporary) / "embeddings.sqlite3", provider=provider,
            )
        self.assertEqual(embeddings.shape, (2, 2))
        self.assertEqual(metrics["api_generated"], 2)

    def test_embedding_cache_reloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = embedding_config()
            provider = FakeRemoteProvider(config)
            cache_path = Path(temporary) / "embeddings.sqlite3"
            first, first_metrics = create_embeddings(
                ["一", "二"], config=config, cache_path=cache_path, provider=provider,
            )
            second, second_metrics = create_embeddings(
                ["一", "二"], config=config, cache_path=cache_path, provider=provider,
            )
            self.assertEqual(first_metrics["api_generated"], 2)
            self.assertEqual(second_metrics["cache_hits"], 2)
            self.assertEqual(provider.calls, 1)
            np.testing.assert_array_equal(first, second)

    def test_model_saves_and_reloads(self):
        frame = synthetic_frame()
        model = build_tfidf_pipeline().fit(frame["_text"], frame["_label"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.joblib"
            joblib.dump(model, path)
            loaded = joblib.load(path)
            self.assertIn(loaded.predict(["我在检查"])[0], LABELS)

    def test_unified_inference_returns_legal_label(self):
        frame = synthetic_frame()
        model = build_tfidf_pipeline().fit(frame["_text"], frame["_label"])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "tfidf_linear_svc"
            directory.mkdir()
            joblib.dump(model, directory / "model.joblib")
            (directory / "config.json").write_text(json.dumps({
                "feature": "TF-IDF", "model_version": "test-v1",
            }), encoding="utf-8")
            _load_artifact.cache_clear()
            result = predict_metacognition("我检查了自己的步骤", models_root=temporary)
            self.assertIn(result["label"], LABELS)
            self.assertIsNone(result["confidence"])

    def test_classification_report_has_all_four_classes(self):
        report = classification_report(LABELS, LABELS, labels=list(LABELS), output_dict=True)
        self.assertTrue(set(LABELS).issubset(report))

    def test_confusion_matrix_order_is_fixed(self):
        matrix = confusion_matrix(LABELS, LABELS, labels=list(LABELS))
        np.testing.assert_array_equal(matrix, np.eye(4, dtype=int))

    def test_numeric_gold_labels_map_to_project_taxonomy(self):
        from research.baseline.constants import LABEL_ALIASES

        self.assertEqual(
            [LABEL_ALIASES[str(index)] for index in range(4)],
            ["non_metacognitive", "monitoring", "regulation", "evaluation"],
        )

    def test_logistic_regression_saves_and_reloads(self):
        frame = synthetic_frame()
        features = np.asarray([[len(text), text.count("我")] for text in frame["_text"]])
        model = LogisticRegression(max_iter=1000).fit(features, frame["_label"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "logistic.joblib"
            joblib.dump(model, path)
            loaded = joblib.load(path)
            self.assertIn(loaded.predict([[10, 1]])[0], LABELS)


if __name__ == "__main__":
    unittest.main()
