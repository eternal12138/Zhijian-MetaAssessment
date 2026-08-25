from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from .constants import EMBEDDING_MODEL


def configure_cpu_threads(threads: int = 2) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", str(threads))
    os.environ.setdefault("MKL_NUM_THREADS", str(threads))
    try:
        import torch

        torch.set_num_threads(threads)
        if hasattr(torch, "set_num_interop_threads"):
            try:
                torch.set_num_interop_threads(1)
            except RuntimeError:
                pass
    except ImportError:
        pass


def embedding_cache_key(
    texts: Sequence[str], dataset_version: str, model_name: str = EMBEDDING_MODEL
) -> str:
    digest = hashlib.sha256()
    digest.update(dataset_version.encode("utf-8"))
    digest.update(b"\0")
    digest.update(model_name.encode("utf-8"))
    for text in texts:
        digest.update(b"\0")
        digest.update(hashlib.sha256(text.encode("utf-8")).digest())
    return digest.hexdigest()


class BgeM3Encoder:
    """Lazy, reusable dense-only BGE-M3 encoder."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        *,
        device: str = "cpu",
        cpu_threads: int = 2,
        batch_size: int = 16,
        max_length: int = 512,
        backend_factory: Callable[[], object] | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.cpu_threads = cpu_threads
        self.batch_size = batch_size
        self.max_length = max_length
        self._backend_factory = backend_factory
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is not None:
            return self._model
        if self.device == "cpu":
            configure_cpu_threads(self.cpu_threads)
        if self._backend_factory is not None:
            self._model = self._backend_factory()
            return self._model
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise RuntimeError(
                "缺少 FlagEmbedding；请使用 requirements-training.txt 创建训练环境"
            ) from exc
        self._model = BGEM3FlagModel(
            self.model_name,
            use_fp16=self.device.startswith("cuda"),
            device=self.device,
        )
        return self._model

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        model = self._load()
        output = model.encode(
            list(texts),
            batch_size=self.batch_size,
            max_length=self.max_length,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        if isinstance(output, dict):
            output = output.get("dense_vecs")
        embeddings = np.asarray(output, dtype=np.float32)
        if embeddings.ndim != 2 or embeddings.shape[0] != len(texts):
            raise RuntimeError(f"BGE embedding shape invalid: {embeddings.shape}")
        return embeddings


def load_or_create_embeddings(
    texts: Sequence[str],
    *,
    dataset_version: str,
    cache_dir: Path,
    encoder: BgeM3Encoder,
) -> tuple[np.ndarray, bool, Path]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = embedding_cache_key(texts, dataset_version, encoder.model_name)
    cache_path = cache_dir / "bge_m3_embeddings.npz"
    metadata_path = cache_dir / "bge_m3_embeddings.metadata.json"
    if cache_path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("cache_key") == key:
            with np.load(cache_path) as payload:
                embeddings = np.asarray(payload["embeddings"], dtype=np.float32)
            if embeddings.shape[0] == len(texts):
                return embeddings, True, cache_path

    embeddings = encoder.encode(texts)
    np.savez_compressed(cache_path, embeddings=embeddings)
    metadata_path.write_text(
        json.dumps(
            {
                "cache_key": key,
                "dataset_version": dataset_version,
                "embedding_model": encoder.model_name,
                "text_count": len(texts),
                "dimension": int(embeddings.shape[1]),
                "dense_only": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return embeddings, False, cache_path
