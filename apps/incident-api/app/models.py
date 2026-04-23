from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class IncidentResponse(BaseModel):
    incidentId: str
    status: str
    summary: IncidentSummary
    evidenceArtifactPath: str
