from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.baseline.benchmark import run_deployment_benchmark


def load_texts(path: Path, limit: int = 100) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        candidates = ("clean_text", "cleaned_text", "text")
        text_column = next((column for column in candidates if column in (reader.fieldnames or [])), None)
        if text_column is None:
            raise ValueError(f"cannot find text column in {reader.fieldnames}")
        texts = [str(row.get(text_column) or "").strip() for row in reader]
    return [text for text in texts if text][:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean-process 2-thread CPU deployment benchmark")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", default=str(SCRIPT_DIR / "baseline_output"))
    args = parser.parse_args()
    rows = run_deployment_benchmark(
        output_root=Path(args.output).expanduser(),
        texts=load_texts(Path(args.dataset).expanduser()),
    )
    for row in rows:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
