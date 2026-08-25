"""Leakage-safe metacognition classification baselines."""

from .constants import LABELS
from .inference import predict_metacognition

__all__ = ["LABELS", "predict_metacognition"]
