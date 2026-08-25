"""Expert-labelled training dataset contracts and CSV serialization."""
from __future__ import annotations

import csv
from io import StringIO
from typing import Iterable, Mapping, Any


EXPERT_LABELS = (
    "monitoring",
    "regulation",
    "evaluation",
)
TEXT_SOURCES = ("clean_text", "raw_text")
LABEL_MODES = ("resolved", "individual")

CSV_COLUMNS = (
    "segment_id", "user_id", "audio_id", "start_time", "end_time", "text", "label",
    "raw_text", "clean_text", "task_id", "session_id", "run_id",
    "expert_id", "expert_name", "reviewer_slot", "label_source", "note",
    "created_at", "updated_at",
)


def build_training_csv(
    rows: Iterable[Mapping[str, Any]],
    *,
    text_source: str = "clean_text",
) -> tuple[bytes, int]:
    if text_source not in TEXT_SOURCES:
        raise ValueError("text_source must be clean_text or raw_text")
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    count = 0
    for source in rows:
        label = str(source.get("label") or "")
        if label not in EXPERT_LABELS:
            continue
        row = dict(source)
        row["text"] = str(source.get(text_source) or "")
        writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})
        count += 1
    return ("\ufeff" + output.getvalue()).encode("utf-8"), count
