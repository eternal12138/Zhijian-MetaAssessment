"""Versioned, within-person interpretation of a frozen three-axis measurement.

The result is descriptive for one completed run.  It is deliberately separate
from ability scores and leaves a stable slot for a future population norm.
"""
from __future__ import annotations

from typing import Mapping


PATTERN_VERSION = "ipsative-pattern-v1"
PATTERN_TITLE = "本轮元认知模式（仅供参考并非稳定能力或人格类型的体现）"
DIMENSIONS = ("monitoring", "controlDebugging", "evaluation")
DIMENSION_LABELS = {
    "monitoring": "监控",
    "controlDebugging": "控制/调试",
    "evaluation": "评估",
}
PRACTICE_FOCUS = {
    "monitoring": "目标检查、自我提问和过程觉察",
    "controlDebugging": "策略切换、备选方案生成和纠错",
    "evaluation": "结果复核、方法比较和经验迁移",
}

MINIMUM_DIALOGUES = 10
RELIABLE_DIALOGUES = 15
RELATIVE_GAP = 0.10
BALANCED_SPAN = 0.15


def _norm_payload(reference: Mapping | None = None) -> dict:
    """Normalize the optional output of a future class/group norm provider."""
    payload = {
        "status": "not_connected",
        "reference_id": None,
        "reference_label": None,
        "percentiles": None,
    }
    if reference is None:
        return payload
    percentiles = reference.get("percentiles")
    if not isinstance(reference.get("reference_id"), str) or not isinstance(percentiles, Mapping):
        raise ValueError("群体常模接入结果缺少 reference_id 或 percentiles")
    normalized_percentiles = {}
    for dimension in DIMENSIONS:
        value = percentiles.get(dimension)
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 100:
            raise ValueError("群体常模百分位必须覆盖三个维度并位于 0 到 100 之间")
        normalized_percentiles[dimension] = round(float(value), 1)
    return {
        "status": "available",
        "reference_id": reference["reference_id"],
        "reference_label": reference.get("reference_label"),
        "percentiles": normalized_percentiles,
    }


def _base_result(*, effective_dialogue_count: int, is_provisional: bool, group_norm: Mapping | None) -> dict:
    return {
        "title": PATTERN_TITLE,
        "rule_version": PATTERN_VERSION,
        "comparison_basis": "within_person",
        "effective_dialogue_count": effective_dialogue_count,
        "is_provisional": is_provisional,
        "relative_high_dimensions": [],
        "relative_low_dimensions": [],
        "group_norm": _norm_payload(group_norm),
        "rule_parameters": {
            "minimum_dialogues": MINIMUM_DIALOGUES,
            "reliable_dialogues": RELIABLE_DIALOGUES,
            "relative_gap": RELATIVE_GAP,
            "balanced_span": BALANCED_SPAN,
        },
    }


def classify_metacognition_pattern(
    scores: Mapping[str, float | None],
    effective_dialogue_count: int,
    *,
    source_is_provisional: bool = False,
    group_norm: Mapping | None = None,
) -> dict:
    """Classify relative highs/lows against this run's three-axis mean.

    Population norms are intentionally not consulted here.  A later norm
    provider can populate ``group_norm`` while keeping the frozen ipsative
    result and the public report contract unchanged.
    """
    provisional = source_is_provisional or effective_dialogue_count < RELIABLE_DIALOGUES
    result = _base_result(
        effective_dialogue_count=effective_dialogue_count,
        is_provisional=provisional,
        group_norm=group_norm,
    )
    values = {dimension: scores.get(dimension) for dimension in DIMENSIONS}
    if effective_dialogue_count < MINIMUM_DIALOGUES or any(
        not isinstance(value, (int, float)) for value in values.values()
    ):
        return {
            **result,
            "key": "insufficient_evidence",
            "label": "证据不足，暂不判定",
            "status": "insufficient",
            "description": (
                f"本轮最终有效对话为 {effective_dialogue_count} 条，"
                f"少于模式判定所需的 {MINIMUM_DIALOGUES} 条。"
            ),
            "practice_focus": "继续完成规范的出声思维记录后再观察三维相对分布。",
            "scores": values,
            "personal_mean": None,
            "span": None,
        }

    numeric = {dimension: float(value) for dimension, value in values.items()}
    if any(value < 0 or value > 1 for value in numeric.values()):
        raise ValueError("元认知模式输入分数必须位于 0 到 1 之间")
    personal_mean = sum(numeric.values()) / len(DIMENSIONS)
    span = max(numeric.values()) - min(numeric.values())
    high = [
        dimension for dimension, value in numeric.items()
        if value - personal_mean >= RELATIVE_GAP - 1e-9
    ]
    low = [
        dimension for dimension, value in numeric.items()
        if personal_mean - value >= RELATIVE_GAP - 1e-9
    ]

    common = {
        **result,
        "status": "provisional" if provisional else "available",
        "scores": {key: round(value, 4) for key, value in numeric.items()},
        "personal_mean": round(personal_mean, 4),
        "span": round(span, 4),
        "relative_high_dimensions": high,
        "relative_low_dimensions": low,
    }
    if span <= BALANCED_SPAN + 1e-9:
        return {
            **common,
            "key": "relative_balanced",
            "label": "三维相对均衡型",
            "description": "本轮三个维度的证据占比较为接近，未形成明显的相对高低差异。",
            "practice_focus": "结合具体任务表现，选择最需要巩固的环节进行练习。",
            "relative_high_dimensions": [],
            "relative_low_dimensions": [],
        }

    if not high and not low:
        return {
            **common,
            "key": "relative_mixed",
            "label": "混合特征型",
            "description": "本轮三维分布存在差异，但尚未达到稳定的相对高低判定标准。",
            "practice_focus": "继续积累有效对话，并结合下一轮任务观察相对分布。",
        }

    high_labels = "、".join(DIMENSION_LABELS[item] for item in high)
    low_labels = "、".join(DIMENSION_LABELS[item] for item in low)
    label_parts = []
    description_parts = []
    if high:
        label_parts.append(f"{high_labels}相对突出")
        description_parts.append(f"{high_labels}证据占比高于本轮个人三维均值")
    if low:
        label_parts.append(f"{low_labels}证据相对较少")
        description_parts.append(f"{low_labels}证据占比低于本轮个人三维均值")
    focus_dimensions = low or high
    return {
        **common,
        "key": "relative_contrast",
        "label": "－".join(label_parts) + "型",
        "description": "，".join(description_parts) + "。该结果仅描述本轮内部相对分布。",
        "practice_focus": "；".join(PRACTICE_FOCUS[item] for item in focus_dimensions),
    }
