"""Create leakage-safe, deterministic group folds for metacognition text training.

The unit of splitting is account_id. All text fragments from one account stay
in the same fold, preventing fragments from the same participant appearing in
both train and test data.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path.home() / "Desktop"
INPUT_CSV = DESKTOP / "training_dataset_v1.csv"
OUTPUT_DIR = PROJECT_ROOT / "research" / "datasets"
MANIFEST_PATH = OUTPUT_DIR / "split_manifest_v1.csv"
REPORT_PATH = OUTPUT_DIR / "fold_distribution_v1.csv"
SUMMARY_PATH = OUTPUT_DIR / "split_summary_v1.json"
N_FOLDS = 5
LABELS = (0, 1, 2, 3)


def read_rows() -> list[dict[str, str]]:
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "sample_id",
        "account_id",
        "run_id",
        "session_id",
        "task_name",
        "cleaned_text",
        "label_train",
    }
    missing = required - set(rows[0]) if rows else required
    if missing:
        raise ValueError(f"训练CSV缺少字段: {sorted(missing)}")
    if not rows:
        raise ValueError("训练CSV没有数据行")
    for row in rows:
        label = int(row["label_train"])
        if label not in LABELS:
            raise ValueError(f"发现非法训练标签: {label}")
        if not row["account_id"].strip():
            raise ValueError(f"样本缺少账号: {row['sample_id']}")
    return rows


def group_rows(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["account_id"]].append(row)
    return dict(groups)


def group_priority(group: list[dict[str, str]]) -> tuple[int, float, str]:
    counts = Counter(int(row["label_train"]) for row in group)
    # Rare labels and larger groups are placed first to stabilize the greedy
    # assignment. The account ID is a deterministic final tie-breaker.
    rare_weight = sum(1 / max(counts[label], 1) for label in LABELS if label in counts)
    # Place large accounts first so the five initial seed folds are not
    # accidentally filled by a tiny account. Rare-label presence is used as a
    # secondary priority, while the account ID keeps the result reproducible.
    return (-len(group), -rare_weight, group[0]["account_id"])


def assign_folds(groups: dict[str, list[dict[str, str]]]) -> dict[str, int]:
    total_by_label = Counter(int(row["label_train"]) for rows in groups.values() for row in rows)
    total_rows = sum(total_by_label.values())
    target_by_label = {label: total_by_label[label] / N_FOLDS for label in LABELS}
    target_rows = total_rows / N_FOLDS
    fold_counts = [Counter() for _ in range(N_FOLDS)]
    fold_sizes = [0] * N_FOLDS
    assignments: dict[str, int] = {}

    ordered_groups = sorted(groups.values(), key=group_priority)
    for group in ordered_groups:
        group_counts = Counter(int(row["label_train"]) for row in group)

        def score(fold: int) -> tuple[float, float, int]:
            label_error = sum(
                ((fold_counts[fold][label] + group_counts[label]) - target_by_label[label]) ** 2
                for label in LABELS
            )
            size_error = ((fold_sizes[fold] + len(group)) - target_rows) ** 2
            # Assign the next account to the currently smallest fold. Because
            # groups are processed from large to small, this is a stable
            # largest-first bin-packing strategy and avoids stranded folds.
            return (fold_sizes[fold], label_error, fold)

        empty_folds = [fold for fold in range(N_FOLDS) if fold_sizes[fold] == 0]
        # Seed every fold before optimizing balance. This prevents an empty
        # test fold when a few accounts contain many more fragments than the
        # others.
        selected_fold = empty_folds[0] if empty_folds else min(range(N_FOLDS), key=score)
        account_id = group[0]["account_id"]
        assignments[account_id] = selected_fold
        fold_sizes[selected_fold] += len(group)
        fold_counts[selected_fold].update(group_counts)

    return assignments


def write_outputs(rows: list[dict[str, str]], assignments: dict[str, int]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_fields = [
        "sample_id",
        "account_id",
        "run_id",
        "session_id",
        "task_name",
        "label_train",
        "fold",
        "split_rule",
    ]
    with MANIFEST_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=manifest_fields)
        writer.writeheader()
        for row in rows:
            fold = assignments[row["account_id"]] + 1
            writer.writerow(
                {
                    "sample_id": row["sample_id"],
                    "account_id": row["account_id"],
                    "run_id": row["run_id"],
                    "session_id": row["session_id"],
                    "task_name": row["task_name"],
                    "label_train": row["label_train"],
                    "fold": fold,
                    "split_rule": "按账号分组；当前fold为测试集，其余4折为训练集",
                }
            )

    report_fields = ["fold", "split", "sample_count", "account_count", "label_0", "label_1", "label_2", "label_3"]
    with REPORT_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=report_fields)
        writer.writeheader()
        for fold in range(1, N_FOLDS + 1):
            test_rows = [row for row in rows if assignments[row["account_id"]] + 1 == fold]
            train_rows = [row for row in rows if assignments[row["account_id"]] + 1 != fold]
            for split, split_rows in (("test", test_rows), ("train", train_rows)):
                counts = Counter(int(row["label_train"]) for row in split_rows)
                writer.writerow(
                    {
                        "fold": fold,
                        "split": split,
                        "sample_count": len(split_rows),
                        "account_count": len({row["account_id"] for row in split_rows}),
                        **{f"label_{label}": counts[label] for label in LABELS},
                    }
                )

    summary = {
        "dataset": "training_dataset_v1.csv",
        "fold_count": N_FOLDS,
        "group_key": "account_id",
        "sample_count": len(rows),
        "account_count": len(assignments),
        "label_counts": dict(sorted(Counter(int(row["label_train"]) for row in rows).items())),
        "fold_assignments": dict(sorted(assignments.items())),
        "leakage_rule": "同一账号的全部文本片段只进入一个fold；每轮当前fold为测试集，其余fold为训练集。",
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    rows = read_rows()
    assignments = assign_folds(group_rows(rows))
    write_outputs(rows, assignments)
    print(json.dumps({
        "input": str(INPUT_CSV),
        "manifest": str(MANIFEST_PATH),
        "report": str(REPORT_PATH),
        "summary": str(SUMMARY_PATH),
        "samples": len(rows),
        "accounts": len(assignments),
        "folds": N_FOLDS,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
