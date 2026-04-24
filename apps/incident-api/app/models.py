from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


IncidentStatus = Literal[
    "pending_approval",
    "approved",
    "rejected",
    "executing",
    "done",
    "failed",
]


class AlertPayload(BaseModel):
    source: str
    fingerprint: str
    status: str
    startsAt: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    actor: str
    reason: str


class IncidentSummary(BaseModel):
    title: str
    severity: str
    what_happened: str
    next_best_action: str


class IncidentEvent(BaseModel):
    eventType: str
    fromStatus: IncidentStatus | None = None
    toStatus: IncidentStatus | None = None
    message: str
    at: str


class IncidentResponse(BaseModel):
    incidentId: str
    status: IncidentStatus
    summary: IncidentSummary
    evidenceArtifactPath: str
    executionAttempts: int
    maxExecutionAttempts: int
    lastError: str | None = None
    history: list[IncidentEvent] = Field(default_factory=list)
