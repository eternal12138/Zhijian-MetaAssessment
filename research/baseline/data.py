from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .constants import (
    AUDIO_COLUMNS,
    GROUP_COLUMNS,
    LABEL_ALIASES,
    LABEL_COLUMNS,
    LABELS,
    SEGMENT_COLUMNS,
    TEXT_COLUMNS,
)


def _first(columns: tuple[str, ...], available: set[str]) -> str | None:
    return next((item for item in columns if item in available), None)


@dataclass(frozen=True)
class DatasetSchema:
    text: str
    label: str
    segment: str | None
    group: str | None
    audio: str | None


@dataclass
class LoadedDataset:
    frame: pd.DataFrame
    schema: DatasetSchema
    source_path: Path
    dataset_version: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path: str | Path) -> LoadedDataset:
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.suffix.lower() == ".csv":
        frame = pd.read_csv(source, encoding="utf-8-sig", dtype=str)
    elif source.suffix.lower() in {".xlsx", ".xls"}:
        frame = pd.read_excel(source, dtype=str)
    else:
        raise ValueError("训练数据只支持 CSV/XLSX")

    available = set(frame.columns)
    text = _first(TEXT_COLUMNS, available)
    label = _first(LABEL_COLUMNS, available)
    if text is None or label is None:
        raise ValueError(
            f"无法识别文本/标签字段；当前字段={list(frame.columns)}，"
            f"文本候选={TEXT_COLUMNS}，标签候选={LABEL_COLUMNS}"
        )
    schema = DatasetSchema(
        text=text,
        label=label,
        segment=_first(SEGMENT_COLUMNS, available),
        group=_first(GROUP_COLUMNS, available),
        audio=_first(AUDIO_COLUMNS, available),
    )
    frame = frame.copy()
    frame["_text"] = frame[text].fillna("").astype(str).str.strip()
    frame["_raw_label"] = frame[label].fillna("").astype(str).str.strip()
    frame["_label"] = frame["_raw_label"].map(LABEL_ALIASES).fillna(frame["_raw_label"])
    frame["_segment_id"] = (
        frame[schema.segment].fillna("").astype(str).str.strip()
        if schema.segment else pd.Series([f"row-{index + 1}" for index in range(len(frame))])
    )
    frame["_group_id"] = (
        frame[schema.group].fillna("").astype(str).str.strip() if schema.group else ""
    )
    frame["_audio_id"] = (
        frame[schema.audio].fillna("").astype(str).str.strip() if schema.audio else ""
    )
    return LoadedDataset(frame, schema, source, sha256_file(source))


def build_quality_report(dataset: LoadedDataset) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    frame = dataset.frame
    labels = frame["_label"]
    raw_labels = frame["_raw_label"]
    texts = frame["_text"]
    counts = Counter(labels.tolist())
    valid_counts = {label: int(counts.get(label, 0)) for label in LABELS}
    invalid_counts = {
        str(label): int(count)
        for label, count in sorted(counts.items(), key=lambda item: str(item[0]))
        if label not in LABELS
    }
    conflicts: dict[str, set[str]] = defaultdict(set)
    for text, label in zip(texts, labels):
        if text:
            conflicts[text].add(label)
    conflict_groups = {text: values for text, values in conflicts.items() if len(values) > 1}
    missing_text_count = int(frame[dataset.schema.text].isna().sum())
    empty_text_count = int((texts == "").sum())
    duplicate_text_count = int(texts[texts != ""].duplicated(keep=False).sum())
    segment_unique = (
        bool(not frame["_segment_id"].duplicated().any())
        if dataset.schema.segment else None
    )
    group_present = bool(dataset.schema.group and (frame["_group_id"] != "").any())
    report: dict[str, Any] = {
        "source_path": str(dataset.source_path),
        "dataset_version_sha256": dataset.dataset_version,
        "sample_count": int(len(frame)),
        "detected_schema": {
            "text": dataset.schema.text,
            "label": dataset.schema.label,
            "segment_id": dataset.schema.segment,
            "group_id": dataset.schema.group,
            "audio_id": dataset.schema.audio,
        },
        "required_labels": list(LABELS),
        "observed_labels": sorted(str(item) for item in counts),
        "observed_raw_labels": sorted(str(item) for item in set(raw_labels)),
        "applied_label_mapping": {
            raw: LABEL_ALIASES.get(raw, raw) for raw in sorted(set(raw_labels))
        },
        "label_counts": valid_counts,
        "label_ratios": {
            label: (count / len(frame) if len(frame) else 0.0)
            for label, count in valid_counts.items()
        },
        "class_imbalance": bool(
            len(frame)
            and (
                max(valid_counts.values(), default=0)
                > max(1, min(valid_counts.values(), default=0)) * 2
                or min(valid_counts.values(), default=0) / len(frame) < 0.05
            )
        ),
        "minority_class": min(valid_counts, key=valid_counts.get) if valid_counts else None,
        "invalid_label_counts": invalid_counts,
        "missing_text_count": missing_text_count,
        "empty_text_count": empty_text_count,
        "duplicate_text_count": duplicate_text_count,
        "conflicting_text_count": int(len(conflict_groups)),
        "group_id_present": group_present,
        "group_id_column": dataset.schema.group,
        "audio_id_present": bool(dataset.schema.audio and (frame["_audio_id"] != "").any()),
        "segment_id_unique": segment_unique,
        "training_blocked": bool(
            invalid_counts
            or empty_text_count
            or not len(frame)
            or any(valid_counts[label] == 0 for label in LABELS)
        ),
    }
    issues: list[dict[str, Any]] = []
    for label, count in invalid_counts.items():
        issues.append({"issue": "invalid_label", "value": label, "count": count})
    if empty_text_count:
        issues.append({"issue": "empty_text", "value": "", "count": empty_text_count})
    if conflict_groups:
        issues.append({
            "issue": "conflicting_text_labels",
            "value": "same text has multiple labels",
            "count": len(conflict_groups),
        })
    if dataset.schema.group is None:
        issues.append({
            "issue": "subject_id_missing",
            "value": "fallback stratified split carries subject leakage risk",
            "count": len(frame),
        })
    return report, issues


def write_quality_report(dataset: LoadedDataset, reports_dir: Path) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    report, issues = build_quality_report(dataset)
    (reports_dir / "data_quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (reports_dir / "data_quality.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("issue", "value", "count"))
        writer.writeheader()
        writer.writerows(issues)
    return report


def assert_trainable(dataset: LoadedDataset) -> None:
    report, _ = build_quality_report(dataset)
    if report["training_blocked"]:
        raise ValueError(
            "数据质量检查未通过，已阻止训练。请查看 reports/data_quality.json；"
            f"非法标签={report['invalid_label_counts']}，空文本={report['empty_text_count']}，"
            f"四类数量={report['label_counts']}"
        )


def add_context_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "previous_text" in result and "next_text" in result:
        return result
    grouping = [column for column in ("_group_id", "session_id", "task_id") if column in result]
    if not grouping:
        result["previous_text"] = ""
        result["next_text"] = ""
        return result
    order_columns = [column for column in ("start_time", "started_at_ms", "sequence_no") if column in result]
    ordered = result.sort_values(grouping + order_columns, kind="stable") if order_columns else result
    ordered["previous_text"] = ordered.groupby(grouping, dropna=False)["_text"].shift(1).fillna("")
    ordered["next_text"] = ordered.groupby(grouping, dropna=False)["_text"].shift(-1).fillna("")
    return ordered.sort_index()
