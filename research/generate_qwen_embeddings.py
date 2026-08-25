"""Generate and cache qwen3.7 embeddings for the reviewed training dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from qwen_embedding_client import (
    EmbeddingCache,
    QwenEmbeddingClient,
    QwenEmbeddingConfig,
    cache_key,
    text_hash,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path.home() / "Desktop" / "training_dataset_v1.csv"
DEFAULT_MANIFEST = PROJECT_ROOT / "research" / "datasets" / "split_manifest_v1.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "research" / "embeddings" / "qwen3_7_text_embedding_v1"
DEFAULT_CACHE_PATH = PROJECT_ROOT / "research" / "embeddings" / "qwen_embedding_cache.sqlite3"


def load_local_env(path: Path) -> None:
    """Load simple KEY=VALUE settings without overriding server environment."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


load_local_env(Path(__file__).resolve().parent / ".env.qwen")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成Qwen3.7文本向量并持久化缓存")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--model", default=os.getenv("QWEN_EMBEDDING_MODEL", "qwen3.7-text-embedding"))
    parser.add_argument("--dimensions", type=int, default=int(os.getenv("QWEN_EMBEDDING_DIMENSIONS", "1024")))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("QWEN_EMBEDDING_BATCH_SIZE", "20")))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("QWEN_EMBEDDING_TIMEOUT_SECONDS", "60")))
    parser.add_argument("--max-retries", type=int, default=int(os.getenv("QWEN_EMBEDDING_MAX_RETRIES", "5")))
    parser.add_argument("--dry-run", action="store_true", help="只检查配置和缓存缺口，不调用API")
    parser.add_argument("--limit", type=int, default=0, help="仅调试前N条；0表示全部")
    return parser.parse_args()


def load_dataset(dataset_path: Path, manifest_path: Path, limit: int = 0) -> pd.DataFrame:
    dataset = pd.read_csv(dataset_path, encoding="utf-8-sig", dtype={"account_id": str})
    manifest = pd.read_csv(manifest_path, encoding="utf-8-sig", dtype={"account_id": str})
    required = {"sample_id", "account_id", "cleaned_text", "label_train"}
    if missing := required - set(dataset.columns):
        raise ValueError(f"训练数据缺少字段：{sorted(missing)}")
    if missing := {"sample_id", "fold"} - set(manifest.columns):
        raise ValueError(f"划分清单缺少字段：{sorted(missing)}")
    if dataset["sample_id"].duplicated().any() or manifest["sample_id"].duplicated().any():
        raise ValueError("sample_id必须唯一")
    data = dataset.merge(manifest[["sample_id", "fold"]], on="sample_id", how="left", validate="one_to_one")
    if data["fold"].isna().any():
        raise ValueError("部分训练样本缺少fold")
    data["cleaned_text"] = data["cleaned_text"].fillna("").astype(str).str.strip()
    if (data["cleaned_text"] == "").any():
        raise ValueError("训练数据存在空文本")
    data["label_train"] = data["label_train"].astype(int)
    data["fold"] = data["fold"].astype(int)
    return data.head(limit).copy() if limit > 0 else data


def build_config(args: argparse.Namespace, *, require_api_key: bool) -> QwenEmbeddingConfig:
    config = QwenEmbeddingConfig(
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
        base_url=os.getenv("QWEN_EMBEDDING_BASE_URL", ""),
        model=args.model,
        dimensions=args.dimensions,
        batch_size=args.batch_size,
        timeout_seconds=args.timeout,
        max_retries=args.max_retries,
    )
    config.validate(require_api_key=require_api_key)
    return config


def atomic_save_npz(path: Path, **arrays: np.ndarray) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    temporary.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def export_artifacts(
    *,
    data: pd.DataFrame,
    vectors: np.ndarray,
    config: QwenEmbeddingConfig,
    output_dir: Path,
    dataset_path: Path,
    manifest_path: Path,
    cached_count: int,
    api_count: int,
    total_tokens: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    npz_path = output_dir / "embeddings.npz"
    atomic_save_npz(
        npz_path,
        embeddings=vectors.astype(np.float32),
        sample_ids=data["sample_id"].astype(str).to_numpy(),
        account_ids=data["account_id"].astype(str).to_numpy(),
        labels=data["label_train"].astype(np.int64).to_numpy(),
        folds=data["fold"].astype(np.int64).to_numpy(),
        text_hashes=data["cleaned_text"].map(text_hash).to_numpy(),
    )

    manifest_rows = []
    for index, row in data.reset_index(drop=True).iterrows():
        manifest_rows.append(
            {
                "embedding_row": index,
                "sample_id": row["sample_id"],
                "account_id": row["account_id"],
                "label_train": int(row["label_train"]),
                "fold": int(row["fold"]),
                "text_sha256": text_hash(row["cleaned_text"]),
                "cache_key": cache_key(config.model, config.dimensions, row["cleaned_text"]),
                "embedding_model": config.model,
                "dimensions": config.dimensions,
                "normalized": True,
            }
        )
    manifest_path_out = output_dir / "embedding_manifest.csv"
    with manifest_path_out.with_suffix(".csv.part").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)
    manifest_path_out.with_suffix(".csv.part").replace(manifest_path_out)

    metadata = {
        "artifact_version": "qwen3_7_text_embedding_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "aliyun_model_studio",
        "model": config.model,
        "dimensions": config.dimensions,
        "normalized": True,
        "sample_count": len(data),
        "dataset_sha256": sha256_file(dataset_path),
        "split_manifest_sha256": sha256_file(manifest_path),
        "cache_hits": cached_count,
        "api_generated": api_count,
        "reported_total_tokens": total_tokens,
        "base_url_host": config.base_url.split("//", 1)[-1].split("/", 1)[0],
        "api_key_stored": False,
    }
    atomic_write_text(
        output_dir / "embedding_config.json",
        json.dumps(metadata, ensure_ascii=False, indent=2),
    )


def main() -> None:
    args = parse_args()
    data = load_dataset(args.dataset, args.manifest, args.limit)
    # Dry-run still validates the endpoint/model/dimension, but does not require
    # a secret because it never performs a remote request.
    config = build_config(args, require_api_key=not args.dry_run)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path = args.cache_path
    keys = [cache_key(config.model, config.dimensions, text) for text in data["cleaned_text"]]
    vectors: list[np.ndarray | None] = [None] * len(data)
    missing_indices: list[int] = []

    with EmbeddingCache(cache_path) as cache:
        for index, key in enumerate(keys):
            vector = cache.get(key, config.dimensions)
            if vector is None:
                missing_indices.append(index)
            else:
                vectors[index] = vector

        print(json.dumps({
            "samples": len(data),
            "cached": len(data) - len(missing_indices),
            "missing": len(missing_indices),
            "model": config.model,
            "dimensions": config.dimensions,
            "dry_run": args.dry_run,
        }, ensure_ascii=False, indent=2))
        if args.dry_run:
            return

        generated = 0
        total_tokens = 0
        with QwenEmbeddingClient(config) as client:
            for start in range(0, len(missing_indices), config.batch_size):
                batch_indices = missing_indices[start:start + config.batch_size]
                texts = [str(data.iloc[index]["cleaned_text"]) for index in batch_indices]
                batch_keys = [keys[index] for index in batch_indices]
                result = client.embed(texts)
                cache.put_many(
                    keys=batch_keys,
                    texts=texts,
                    model=config.model,
                    dimensions=config.dimensions,
                    vectors=result.vectors,
                    request_id=result.request_id,
                    total_tokens=result.total_tokens,
                )
                for index, vector in zip(batch_indices, result.vectors, strict=True):
                    vectors[index] = vector
                generated += len(batch_indices)
                total_tokens += result.total_tokens
                print(f"向量生成进度：{generated}/{len(missing_indices)}")

    if any(vector is None for vector in vectors):
        raise RuntimeError("仍有样本缺少向量")
    matrix = np.vstack([vector for vector in vectors if vector is not None]).astype(np.float32)
    export_artifacts(
        data=data,
        vectors=matrix,
        config=config,
        output_dir=args.output_dir,
        dataset_path=args.dataset,
        manifest_path=args.manifest,
        cached_count=len(data) - len(missing_indices),
        api_count=len(missing_indices),
        total_tokens=total_tokens,
    )
    print(f"向量文件已生成：{args.output_dir / 'embeddings.npz'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"向量生成失败：{error}", file=sys.stderr)
        raise
