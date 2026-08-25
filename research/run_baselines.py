from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.baseline.benchmark import run_deployment_benchmark
from research.baseline.data import load_dataset, write_quality_report
from research.baseline.training import run_experiments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Metacognition baseline experiments")
    parser.add_argument("--dataset", required=True, help="Expert-labelled CSV/XLSX")
    parser.add_argument(
        "--output", default=str(SCRIPT_DIR / "baseline_output"),
        help="Models/reports/cache output root",
    )
    parser.add_argument("--quality-only", action="store_true")
    parser.add_argument("--skip-embedding", action="store_true")
    parser.add_argument("--benchmark", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dataset = load_dataset(args.dataset)
    # Keep an explicitly supplied subst/junction path intact. The bundled
    # Windows Python runtime can otherwise mis-decode non-ASCII parent paths
    # when Path.resolve() expands Z: back to the physical project directory.
    output = Path(args.output).expanduser()
    report = write_quality_report(dataset, output / "reports")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.quality_only:
        return 2 if report["training_blocked"] else 0
    run_experiments(dataset, output_root=output, skip_embedding=args.skip_embedding)
    if args.benchmark:
        run_deployment_benchmark(
            output_root=output,
            texts=dataset.frame["_text"].tolist()[:100],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
