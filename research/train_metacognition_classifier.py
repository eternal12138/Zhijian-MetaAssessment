from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.baseline.data import load_dataset
from research.baseline.training import run_experiments


def main() -> int:
    parser = argparse.ArgumentParser(description="Train one metacognition classifier baseline")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", default=str(SCRIPT_DIR / "baseline_output"))
    parser.add_argument("--feature", choices=("tfidf", "embedding"), required=True)
    parser.add_argument(
        "--classifier", choices=("linear_svc", "logistic", "random_forest"), required=True
    )
    args = parser.parse_args()
    if args.feature == "tfidf" and args.classifier != "linear_svc":
        parser.error("TF-IDF baseline currently supports linear_svc only")
    run_experiments(
        load_dataset(args.dataset),
        output_root=Path(args.output).expanduser(),
        skip_embedding=False,
        feature_filter=args.feature,
        classifier_filter=args.classifier,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
