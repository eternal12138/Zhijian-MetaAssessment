from __future__ import annotations

LABELS = (
    "non_metacognitive",
    "monitoring",
    "regulation",
    "evaluation",
)

# The reviewed gold file stores integer codes. This mapping is explicit and
# project-owned; raw labels are retained separately in quality reports.
LABEL_ALIASES = {
    "0": "non_metacognitive",
    "1": "monitoring",
    "2": "regulation",
    "3": "evaluation",
    "non_metacognitive": "non_metacognitive",
    "non_metacognitive_or_uncertain": "non_metacognitive",
    "非元认知": "non_metacognitive",
    "不确定/不算元认知": "non_metacognitive",
    "monitoring": "monitoring",
    "监控": "monitoring",
    "regulation": "regulation",
    "control_regulation": "regulation",
    "控制/调控": "regulation",
    "调控": "regulation",
    "evaluation": "evaluation",
    "评估": "evaluation",
}

TEXT_COLUMNS = ("clean_text", "cleaned_text", "text")
LABEL_COLUMNS = ("label", "expert_label", "resolved_label", "label_train")
SEGMENT_COLUMNS = ("segment_id", "sample_id")
GROUP_COLUMNS = ("user_id", "participant_id", "account_id")
AUDIO_COLUMNS = ("audio_id",)

RANDOM_STATE = 42
MODEL_VERSION = "baseline-v1"
