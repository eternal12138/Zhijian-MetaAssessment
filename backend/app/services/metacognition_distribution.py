"""Privacy-safe aggregation of three-class metacognitive evidence.

The radar divides label hits by final effective dialogues. Only scopes without
reviewed or admin-corrected dialogues fall back to the three-class label total.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


DIMENSIONS = (
    ("monitoring", "监控 (Monitoring)"),
    ("controlDebugging", "调控 (Regulation)"),
    ("evaluation", "评估 (Evaluation)"),
)


def normalize_dimension(value: object) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return {
        "monitoring": "monitoring",
        "regulation": "controlDebugging",
        "control_regulation": "controlDebugging",
        "controldebugging": "controlDebugging",
        "control_debugging": "controlDebugging",
        "evaluation": "evaluation",
    }.get(normalized)


def empty_counts() -> dict[str, int]:
    return {dimension: 0 for dimension, _label in DIMENSIONS}


def resolve_run_distributions(
    expert_rows: Iterable[tuple[str | None, object, int]],
    model_rows: Iterable[tuple[str | None, object, int]],
) -> dict[str, dict[str, Any]]:
    """Resolve one authoritative count set per run without double counting."""
    by_source: dict[str, dict[str, dict[str, int]]] = {
        "expert_consensus": {},
        "production_model": {},
    }
    for source, rows in (
        ("expert_consensus", expert_rows),
        ("production_model", model_rows),
    ):
        for run_id, raw_dimension, count in rows:
            dimension = normalize_dimension(raw_dimension)
            if not run_id or dimension is None:
                continue
            bucket = by_source[source].setdefault(str(run_id), empty_counts())
            bucket[dimension] += int(count)

    resolved: dict[str, dict[str, Any]] = {}
    for run_id in set(by_source["expert_consensus"]) | set(by_source["production_model"]):
        expert = by_source["expert_consensus"].get(run_id, empty_counts())
        model = by_source["production_model"].get(run_id, empty_counts())
        if sum(expert.values()):
            resolved[run_id] = {"counts": expert, "source": "expert_consensus"}
        elif sum(model.values()):
            resolved[run_id] = {"counts": model, "source": "production_model"}
    return resolved


def aggregate_distribution(
    run_ids: Iterable[str],
    resolved_by_run: dict[str, dict[str, Any]],
    *,
    scope: str,
    label: str,
) -> dict[str, Any]:
    counts = empty_counts()
    sources: set[str] = set()
    contributing_runs = 0
    denominator = 0
    denominator_sources: dict[str, int] = {}
    unclassified_count = 0
    for run_id in dict.fromkeys(str(value) for value in run_ids if value):
        row = resolved_by_run.get(run_id)
        if not row or int(row.get("effective_dialogue_count", sum(row["counts"].values()))) <= 0:
            continue
        contributing_runs += 1
        sources.add(str(row["source"]))
        row_denominator = int(row.get("effective_dialogue_count", sum(row["counts"].values())))
        denominator += row_denominator
        unclassified_count += int(row.get("unclassified_count", 0))
        for name, value in row.get("denominator_breakdown", {"label_total_fallback": row_denominator}).items():
            denominator_sources[name] = denominator_sources.get(name, 0) + int(value)
        for dimension, _dimension_label in DIMENSIONS:
            counts[dimension] += int(row["counts"].get(dimension, 0))
    total = sum(counts.values())
    percentages = {
        dimension: round(count / denominator * 100, 1) if denominator else 0.0
        for dimension, count in counts.items()
    }
    source = (
        "none" if not sources else next(iter(sources)) if len(sources) == 1 else "hybrid"
    )
    return {
        "scope": scope,
        "label": label,
        "counts": counts,
        "percentages": percentages,
        "total": total,
        "effective_dialogue_count": denominator,
        "denominator_breakdown": denominator_sources,
        "fallback_dialogue_count": denominator_sources.get("label_total_fallback", 0),
        "unclassified_count": unclassified_count,
        "score_available": denominator > 0 and (total > 0 or unclassified_count == 0),
        "sample_count": contributing_runs,
        "primary_source": source,
        "scores": [
            {
                "dimension": dimension,
                "label": dimension_label,
                "score": percentages[dimension],
                "max": 100,
            }
            for dimension, dimension_label in DIMENSIONS
        ] if denominator > 0 and (total > 0 or unclassified_count == 0) else [],
    }
