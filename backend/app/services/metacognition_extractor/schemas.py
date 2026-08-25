"""Strict transport schemas for high-recall candidate extraction."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SourceSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    text: str
    started_at_ms: int = 0
    ended_at_ms: int = 0


class ProposedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    original_text: str = Field(min_length=1, max_length=4000)
    clean_text: str = Field(min_length=1, max_length=4000)


class ExtractionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[ProposedCandidate] = Field(default_factory=list, max_length=500)
