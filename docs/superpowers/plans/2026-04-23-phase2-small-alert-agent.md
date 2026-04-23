# Phase 2 Small Incident Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `incident-api` service that handles alert intake, creates incident summaries and evidence artifacts, and supports human approve/reject decisions with persistent local storage.

**Architecture:** Keep existing compose stack and add a third service (`incident-api`) in `apps/incident-api`. The service stores incidents in SQLite at `/data/incidents.db`, writes evidence JSON files in `/data/artifacts`, and exports telemetry to `otel-lgtm` using the same OTLP protocol as Phase 1. Existing `sample-service` behavior remains unchanged.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, sqlite3, pytest, httpx, OpenTelemetry (same versions/pattern as sample-service), Docker Compose.

---

## File structure map

- **Create:** `apps/incident-api/requirements.txt` (runtime deps)
- **Create:** `apps/incident-api/requirements-dev.txt` (test deps)
- **Create:** `apps/incident-api/Dockerfile` (container build)
- **Create:** `apps/incident-api/pytest.ini` (test import path)
- **Create:** `apps/incident-api/app/__init__.py`
- **Create:** `apps/incident-api/app/models.py` (request/response schemas)
- **Create:** `apps/incident-api/app/store.py` (SQLite schema + CRUD)
- **Create:** `apps/incident-api/app/evidence.py` (artifact writer)
- **Create:** `apps/incident-api/app/main.py` (FastAPI routes + telemetry)
- **Create:** `apps/incident-api/tests/conftest.py`
- **Create:** `apps/incident-api/tests/test_incident_api.py`
- **Modify:** `docker-compose.yml` (add `incident-api` service + volume)
- **Modify:** `README.md` (Phase 2 quick start + validation)

---

### Task 1: Scaffold `incident-api` project and dependencies

**Files:**
- Create: `apps/incident-api/requirements.txt`
- Create: `apps/incident-api/requirements-dev.txt`
- Create: `apps/incident-api/Dockerfile`
- Create: `apps/incident-api/pytest.ini`
- Create: `apps/incident-api/app/__init__.py`

- [ ] **Step 1: Add runtime requirements**

```txt
fastapi==0.115.6
uvicorn[standard]==0.32.1
setuptools>=69.5.1,<81
opentelemetry-api==1.27.0
opentelemetry-sdk==1.27.0
opentelemetry-exporter-otlp-proto-http==1.27.0
opentelemetry-instrumentation-fastapi==0.48b0
opentelemetry-instrumentation-logging==0.48b0
```

- [ ] **Step 2: Add dev requirements**

```txt
-r requirements.txt
pytest==8.3.4
httpx==0.28.1
```

- [ ] **Step 3: Add Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

- [ ] **Step 4: Add test config + package init**

`pytest.ini`:

```ini
[pytest]
pythonpath = .
```

`app/__init__.py`:

```python
# incident-api package
```

- [ ] **Step 5: Commit scaffold**

```bash
git add apps/incident-api/requirements.txt apps/incident-api/requirements-dev.txt apps/incident-api/Dockerfile apps/incident-api/pytest.ini apps/incident-api/app/__init__.py
git commit --trailer "Made-with: Cursor" -m "chore: scaffold incident-api service"
```

---

### Task 2: Write failing tests first for incident flow

**Files:**
- Create: `apps/incident-api/tests/conftest.py`
- Create: `apps/incident-api/tests/test_incident_api.py`

- [ ] **Step 1: Add test setup with isolated DB/artifacts**

```python
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def test_env(tmp_path: Path):
    os.environ["DISABLE_OTEL"] = "1"
    os.environ["INCIDENT_DB_PATH"] = str(tmp_path / "incidents.db")
    os.environ["INCIDENT_ARTIFACT_DIR"] = str(tmp_path / "artifacts")
    yield
```

- [ ] **Step 2: Add failing tests for core API contract**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_create_incident_from_alert() -> None:
    payload = {
        "source": "alertmanager",
        "fingerprint": "cpu-high-service-a",
        "status": "firing",
        "startsAt": "2026-04-23T12:00:00Z",
        "labels": {"alertname": "HighCPU", "service": "aiops-sample-service", "severity": "warning"},
        "annotations": {"summary": "CPU over threshold"},
    }

    with TestClient(app) as client:
        response = client.post("/v1/alerts", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["incidentId"].startswith("inc_")
    assert body["summary"]["severity"] == "warning"


def test_fetch_and_decide_incident() -> None:
    payload = {
        "source": "alertmanager",
        "fingerprint": "latency-service-a",
        "status": "firing",
        "startsAt": "2026-04-23T12:05:00Z",
        "labels": {"alertname": "HighLatency", "service": "aiops-sample-service", "severity": "critical"},
        "annotations": {"summary": "p95 latency high"},
    }

    with TestClient(app) as client:
        created = client.post("/v1/alerts", json=payload).json()
        incident_id = created["incidentId"]

        get_resp = client.get(f"/v1/incidents/{incident_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["incidentId"] == incident_id

        decision = client.post(
            f"/v1/incidents/{incident_id}/decision",
            json={"decision": "approve", "actor": "human@local", "reason": "confirmed impact"},
        )

    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"


def test_reject_invalid_decision_value() -> None:
    payload = {
        "source": "alertmanager",
        "fingerprint": "err-rate-service-a",
        "status": "firing",
        "startsAt": "2026-04-23T12:10:00Z",
        "labels": {"alertname": "HighErrorRate", "service": "aiops-sample-service", "severity": "warning"},
        "annotations": {"summary": "5xx rate above threshold"},
    }

    with TestClient(app) as client:
        created = client.post("/v1/alerts", json=payload).json()
        incident_id = created["incidentId"]

        bad = client.post(
            f"/v1/incidents/{incident_id}/decision",
            json={"decision": "later", "actor": "human@local", "reason": "invalid"},
        )

    assert bad.status_code == 422
```

- [ ] **Step 3: Run tests to confirm failure**

Run:

```bash
cd apps/incident-api
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_incident_api.py -v
```

Expected: FAIL because `app.main` and API routes are not implemented yet.

- [ ] **Step 4: Commit failing tests**

```bash
git add apps/incident-api/tests/conftest.py apps/incident-api/tests/test_incident_api.py
git commit --trailer "Made-with: Cursor" -m "test: add failing tests for incident intake and decision flow"
```

---

### Task 3: Implement incident-api models, storage, artifacts, and routes

**Files:**
- Create: `apps/incident-api/app/models.py`
- Create: `apps/incident-api/app/store.py`
- Create: `apps/incident-api/app/evidence.py`
- Create: `apps/incident-api/app/main.py`

- [ ] **Step 1: Add Pydantic models**

```python
# app/models.py
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
```

- [ ] **Step 2: Add SQLite store with lifecycle transitions**

```python
# app/store.py
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncidentStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint ON incidents(fingerprint);

                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    FOREIGN KEY (incident_id) REFERENCES incidents(id)
                );
                """
            )

    def create_incident(self, incident_id: str, fingerprint: str, summary: dict, artifact_path: str) -> dict:
        now = utc_now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO incidents (id, fingerprint, status, summary_json, artifact_path, created_at, updated_at)
                VALUES (?, ?, 'pending_approval', ?, ?, ?, ?)
                """,
                (incident_id, fingerprint, json.dumps(summary), artifact_path, now, now),
            )
        return self.get_incident(incident_id)

    def get_open_by_fingerprint(self, fingerprint: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM incidents
                WHERE fingerprint = ? AND status = 'pending_approval'
                ORDER BY created_at DESC LIMIT 1
                """,
                (fingerprint,),
            ).fetchone()
        return dict(row) if row else None

    def get_incident(self, incident_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if not row:
            raise KeyError(incident_id)
        return dict(row)

    def set_decision(self, incident_id: str, decision: str, actor: str, reason: str) -> dict:
        incident = self.get_incident(incident_id)
        if incident["status"] != "pending_approval":
            raise ValueError("incident is not pending approval")

        now = utc_now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO decisions (incident_id, decision, actor, reason, decided_at) VALUES (?, ?, ?, ?, ?)",
                (incident_id, decision, actor, reason, now),
            )
            conn.execute(
                "UPDATE incidents SET status = ?, updated_at = ? WHERE id = ?",
                ("approved" if decision == "approve" else "rejected", now, incident_id),
            )
        return self.get_incident(incident_id)
```

- [ ] **Step 3: Add evidence writer**

```python
# app/evidence.py
from __future__ import annotations

import json
from pathlib import Path


def write_evidence(artifact_dir: str, incident_id: str, payload: dict, summary: dict) -> str:
    out_dir = Path(artifact_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{incident_id}.json"

    data = {
        "incidentId": incident_id,
        "rawAlert": payload,
        "summary": summary,
    }

    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(out_path)
    return str(out_path)
```

- [ ] **Step 4: Implement main API with deterministic summary and telemetry**

```python
# app/main.py
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from opentelemetry import metrics, trace

from .evidence import write_evidence
from .models import AlertPayload, DecisionRequest, IncidentResponse, IncidentSummary
from .store import IncidentStore

logger = logging.getLogger(__name__)


def _otel_disabled() -> bool:
    return os.getenv("DISABLE_OTEL", "").lower() in ("1", "true", "yes")


def configure_telemetry() -> None:
    if _otel_disabled():
        logging.basicConfig(level=logging.INFO)
        return

    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": "aiops-incident-api",
            "service.version": "0.1.0",
            "deployment.environment": "local",
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=5000)],
    )
    metrics.set_meter_provider(meter_provider)

    logging.basicConfig(level=logging.INFO)
    LoggingInstrumentor().instrument(set_logging_format=True)


def build_summary(payload: AlertPayload) -> IncidentSummary:
    alertname = payload.labels.get("alertname", "Alert")
    service = payload.labels.get("service", "unknown-service")
    severity = payload.labels.get("severity", "unknown")
    what = payload.annotations.get("summary", f"{alertname} triggered")

    return IncidentSummary(
        title=f"{alertname} on {service}",
        severity=severity,
        what_happened=what,
        next_best_action="Review logs/traces around startsAt and confirm impact before any action.",
    )


def new_incident_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"inc_{stamp}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.getenv("INCIDENT_DB_PATH", "/data/incidents.db")
    artifact_dir = os.getenv("INCIDENT_ARTIFACT_DIR", "/data/artifacts")

    app.state.store = IncidentStore(db_path)
    app.state.artifact_dir = artifact_dir

    meter = metrics.get_meter(__name__)
    app.state.alert_counter = meter.create_counter("incident_api.alerts_received", unit="1")
    app.state.decision_counter = meter.create_counter("incident_api.decisions_submitted", unit="1")
    yield


app = FastAPI(title="aiops-incident-api", lifespan=lifespan)
configure_telemetry()
if not _otel_disabled():
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


@app.post("/v1/alerts", response_model=IncidentResponse)
async def create_alert(payload: AlertPayload) -> IncidentResponse:
    app.state.alert_counter.add(1, {"source": payload.source, "status": payload.status})

    store = app.state.store
    summary = build_summary(payload)

    existing = store.get_open_by_fingerprint(payload.fingerprint)
    if existing:
        incident_id = existing["id"]
        artifact_path = existing["artifact_path"]
    else:
        incident_id = new_incident_id()
        artifact_path = write_evidence(
            app.state.artifact_dir,
            incident_id,
            payload.model_dump(),
            summary.model_dump(),
        )
        store.create_incident(
            incident_id=incident_id,
            fingerprint=payload.fingerprint,
            summary=summary.model_dump(),
            artifact_path=artifact_path,
        )

    incident = store.get_incident(incident_id)
    return IncidentResponse(
        incidentId=incident["id"],
        status=incident["status"],
        summary=IncidentSummary(**json.loads(incident["summary_json"])),
        evidenceArtifactPath=incident["artifact_path"],
    )


@app.get("/v1/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: str) -> IncidentResponse:
    store = app.state.store
    try:
        incident = store.get_incident(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="incident not found") from exc

    return IncidentResponse(
        incidentId=incident["id"],
        status=incident["status"],
        summary=IncidentSummary(**json.loads(incident["summary_json"])),
        evidenceArtifactPath=incident["artifact_path"],
    )


@app.post("/v1/incidents/{incident_id}/decision", response_model=IncidentResponse)
async def set_decision(incident_id: str, request: DecisionRequest) -> IncidentResponse:
    app.state.decision_counter.add(1, {"decision": request.decision})

    store = app.state.store
    try:
        incident = store.set_decision(
            incident_id=incident_id,
            decision=request.decision,
            actor=request.actor,
            reason=request.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="incident not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return IncidentResponse(
        incidentId=incident["id"],
        status=incident["status"],
        summary=IncidentSummary(**json.loads(incident["summary_json"])),
        evidenceArtifactPath=incident["artifact_path"],
    )
```

- [ ] **Step 5: Run targeted tests and make them pass**

Run:

```bash
cd apps/incident-api
python -m pytest tests/test_incident_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit implementation**

```bash
git add apps/incident-api/app/models.py apps/incident-api/app/store.py apps/incident-api/app/evidence.py apps/incident-api/app/main.py
git commit --trailer "Made-with: Cursor" -m "feat: implement incident-api alert intake and approval workflow"
```

---

### Task 4: Compose wiring and README updates

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`

- [ ] **Step 1: Add `incident-api` service to compose**

Add service block:

```yaml
  incident-api:
    build:
      context: ./apps/incident-api
      dockerfile: Dockerfile
    container_name: aiops-incident-api
    ports:
      - "8001:8001"
    environment:
      OTEL_SERVICE_NAME: aiops-incident-api
      OTEL_RESOURCE_ATTRIBUTES: service.version=0.1.0,deployment.environment=local
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-lgtm:4318
      OTEL_EXPORTER_OTLP_PROTOCOL: http/protobuf
      INCIDENT_DB_PATH: /data/incidents.db
      INCIDENT_ARTIFACT_DIR: /data/artifacts
    volumes:
      - incident-data:/data
    depends_on:
      - otel-lgtm
```

Add bottom volume:

```yaml
volumes:
  otel-lgtm-data:
  incident-data:
```

- [ ] **Step 2: Validate compose file**

Run:

```bash
docker compose config
```

Expected: valid config with three services and two named volumes.

- [ ] **Step 3: Update README with Phase 2 small flow**

Add:
- endpoint `http://localhost:8001`
- quick test payloads for:
  - `POST /v1/alerts`
  - `GET /v1/incidents/{id}`
  - `POST /v1/incidents/{id}/decision`
- note where artifacts are persisted (`/data/artifacts` inside container)

Example commands to include:

```bash
curl -s -X POST http://localhost:8001/v1/alerts -H "Content-Type: application/json" -d '{"source":"alertmanager","fingerprint":"demo-alert-1","status":"firing","startsAt":"2026-04-23T12:00:00Z","labels":{"alertname":"HighCPU","service":"aiops-sample-service","severity":"warning"},"annotations":{"summary":"CPU high"}}'

curl -s http://localhost:8001/v1/incidents/<incident_id>

curl -s -X POST http://localhost:8001/v1/incidents/<incident_id>/decision -H "Content-Type: application/json" -d '{"decision":"approve","actor":"human@local","reason":"confirmed"}'
```

- [ ] **Step 4: Commit compose/docs updates**

```bash
git add docker-compose.yml README.md
git commit --trailer "Made-with: Cursor" -m "docs: add phase2 incident-api runbook and compose wiring"
```

---

### Task 5: End-to-end validation

**Files:**
- Test only (no new files)

- [ ] **Step 1: Build and run full stack**

```bash
docker compose up --build -d
```

Expected: `otel-lgtm`, `sample-service`, and `incident-api` running.

- [ ] **Step 2: Validate API flow end-to-end**

1) create incident with `POST /v1/alerts`  
2) fetch with `GET /v1/incidents/{id}`  
3) approve/reject with `/decision`

Expected:
- initial `pending_approval`
- final `approved` or `rejected`
- evidence file path returned in API response

- [ ] **Step 3: Verify telemetry exists for incident-api**

Manual check in Grafana Explore:
- service name `aiops-incident-api`
- logs/traces from alert and decision requests

- [ ] **Step 4: Final commit for validation fixes (if any)**

```bash
git add -A
git commit --trailer "Made-with: Cursor" -m "test: validate phase2 small incident loop end-to-end"
```

---

## Spec coverage (self-review)

| Phase 2 spec requirement | Plan coverage |
|---|---|
| Alert intake endpoint | Task 2 + Task 3 |
| Incident summary + evidence artifact | Task 3 |
| Human approve/reject endpoint | Task 2 + Task 3 |
| Local persistence | Task 3 + Task 4 |
| Compose-first small scope | Task 4 |
| Acceptance checks and docs | Task 4 + Task 5 |
| Preserve Phase 1 behavior | Task 4 + Task 5 |

No placeholders, no deferred TODOs, and all new routes/components have exact file targets.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-23-phase2-small-alert-agent.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - fresh subagent per task with review between tasks.  
2. **Inline Execution** - execute all tasks in this session directly.

The user explicitly requested subagents, so proceed with **Subagent-Driven** execution for this plan.
