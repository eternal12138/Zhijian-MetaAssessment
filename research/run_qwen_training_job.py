"""Run embedding generation and classifier training as a resumable job."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
import re


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_JOB_ROOT = PROJECT_ROOT / "research" / "jobs"
DEFAULT_DATASET = Path.home() / "Desktop" / "training_dataset_v1.csv"
DEFAULT_MANIFEST = SCRIPT_DIR / "datasets" / "split_manifest_v1.csv"
DEFAULT_CACHE_PATH = SCRIPT_DIR / "embeddings" / "qwen_embedding_cache.sqlite3"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_status(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_step(command: list[str], log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8") as log:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"子任务失败，退出码{completed.returncode}：{' '.join(command[1:3])}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行可恢复的Qwen向量与分类器训练任务")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--version", default="", help="训练版本；留空时自动生成时间版本")
    parser.add_argument("--job-root", type=Path, default=DEFAULT_JOB_ROOT)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--embedding-dir", type=Path)
    parser.add_argument("--result-dir", type=Path)
    return parser.parse_args()


def normalized_version(raw: str) -> str:
    version = raw.strip() or datetime.now().strftime("v%Y%m%d_%H%M%S")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version):
        raise ValueError("训练版本只能包含字母、数字、点、下划线和短横线，最长64位")
    return version


def main() -> None:
    args = parse_args()
    version = normalized_version(args.version)
    embedding_dir = args.embedding_dir or SCRIPT_DIR / "embeddings" / version
    result_dir = args.result_dir or SCRIPT_DIR / "results" / f"qwen_fc_{version}"
    if result_dir.exists() and any(result_dir.iterdir()):
        raise FileExistsError(f"训练结果版本已存在，拒绝覆盖：{result_dir}")
    job_id = args.job_id.strip() or str(uuid.uuid4())
    job_dir = args.job_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    status_path = job_dir / "status.json"
    log_path = job_dir / "job.log"
    state = {
        "job_id": job_id,
        "version": version,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "created_at": now(),
        "updated_at": now(),
        "dataset": str(args.dataset),
        "manifest": str(args.manifest),
        "embedding_dir": str(embedding_dir),
        "result_dir": str(result_dir),
        "error": "",
    }
    write_status(status_path, state)
    try:
        state.update(status="running", stage="embedding", progress=10, updated_at=now())
        write_status(status_path, state)
        run_step(
            [
                sys.executable,
                str(SCRIPT_DIR / "generate_qwen_embeddings.py"),
                "--dataset", str(args.dataset),
                "--manifest", str(args.manifest),
                "--output-dir", str(embedding_dir),
                "--cache-path", str(args.cache_path),
            ],
            log_path,
        )
        state.update(stage="training", progress=60, updated_at=now())
        write_status(status_path, state)
        run_step(
            [sys.executable, str(SCRIPT_DIR / "train_qwen_fc.py"), "--embedding-dir", str(embedding_dir),
             "--output-dir", str(result_dir)],
            log_path,
        )
        state.update(status="completed", stage="completed", progress=100, updated_at=now(), completed_at=now())
        write_status(status_path, state)
    except Exception as error:
        state.update(
            status="failed", stage="failed", updated_at=now(),
            error=str(error), traceback=traceback.format_exc(limit=8),
        )
        write_status(status_path, state)
        raise
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
