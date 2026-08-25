"""Administrator-facing model service diagnostic schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import ApiModel as BaseModel

DiagnosticStatus = Literal[
    "ready",
    "warning",
    "error",
    "disabled",
    "unconfigured",
    "unknown",
]


class ServiceDiagnosticOut(BaseModel):
    status: DiagnosticStatus
    configured: bool
    label: str
    provider: str
    endpoint: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    message: str


class QuotaDiagnosticOut(BaseModel):
    status: Literal["console_required", "unavailable"]
    exact_remaining_available: bool = False
    remaining: float | None = None
    unit: str
    local_usage: float | None = None
    period: str | None = None
    console_url: str
    message: str


class ModelServicesDiagnosticsOut(BaseModel):
    overall_status: Literal["ready", "degraded", "unavailable"]
    checked_at: datetime
    llm: ServiceDiagnosticOut
    embedding: ServiceDiagnosticOut
    asr: ServiceDiagnosticOut
    audio_public_url: ServiceDiagnosticOut
    llm_quota: QuotaDiagnosticOut
    asr_quota: QuotaDiagnosticOut
