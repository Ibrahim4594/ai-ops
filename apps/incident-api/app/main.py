from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from opentelemetry import metrics, trace

from .evidence import write_evidence
from .models import AlertPayload, DecisionRequest, IncidentEvent, IncidentResponse, IncidentSummary
from .store import IncidentStore
from .worker import ExecutionActionRunner, IncidentExecutionWorker

logger = logging.getLogger(__name__)


def _otel_disabled() -> bool:
    return os.getenv("DISABLE_OTEL", "").lower() in ("1", "true", "yes")


def configure_telemetry() -> None:
    """Heavy OTLP/protobuf imports are lazy so local tests can run with DISABLE_OTEL."""
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

    trace_exporter = OTLPSpanExporter()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(tracer_provider)

    metric_exporter = OTLPMetricExporter()
    reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=5_000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    logging.basicConfig(level=logging.INFO)
    LoggingInstrumentor().instrument(set_logging_format=True)


def build_summary(payload: AlertPayload) -> IncidentSummary:
    alertname = payload.labels.get("alertname", "Alert")
    service = payload.labels.get("service", "unknown-service")
    severity = payload.labels.get("severity", "unknown")
    what_happened = payload.annotations.get("summary", f"{alertname} triggered")

    return IncidentSummary(
        title=f"{alertname} on {service}",
        severity=severity,
        what_happened=what_happened,
        next_best_action="Review logs/traces around startsAt and confirm impact before any action.",
    )


def new_incident_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"inc_{stamp}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.getenv("INCIDENT_DB_PATH", "/data/incidents.db")
    artifact_dir = os.getenv("INCIDENT_ARTIFACT_DIR", "/data/artifacts")
    worker_interval_seconds = float(os.getenv("INCIDENT_WORKER_INTERVAL_SECONDS", "1.0"))

    app.state.store = IncidentStore(db_path)
    app.state.artifact_dir = artifact_dir
    recovered = app.state.store.recover_stuck_executions()
    if recovered:
        logger.warning("Recovered %s incident(s) stuck in executing", recovered)
    app.state.worker = IncidentExecutionWorker(
        store=app.state.store,
        interval_seconds=worker_interval_seconds,
        runner=ExecutionActionRunner.from_env(),
    )
    app.state.worker.start()

    meter = metrics.get_meter(__name__)
    app.state.alert_counter = meter.create_counter(
        "incident_api.alerts_received",
        unit="1",
        description="Count of alert intake requests",
    )
    app.state.decision_counter = meter.create_counter(
        "incident_api.decisions_submitted",
        unit="1",
        description="Count of incident decision submissions",
    )
    yield
    app.state.worker.stop()


app = FastAPI(title="aiops-incident-api", lifespan=lifespan)
configure_telemetry()
if not _otel_disabled():
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _to_incident_response(incident: dict) -> IncidentResponse:
    history = [
        IncidentEvent(
            eventType=entry["event_type"],
            fromStatus=entry["from_status"],
            toStatus=entry["to_status"],
            message=entry["message"],
            at=entry["created_at"],
        )
        for entry in app.state.store.list_events(incident["id"])
    ]
    return IncidentResponse(
        incidentId=incident["id"],
        status=incident["status"],
        summary=IncidentSummary(**json.loads(incident["summary_json"])),
        evidenceArtifactPath=incident["artifact_path"],
        executionAttempts=incident["execution_attempts"],
        maxExecutionAttempts=incident["max_execution_attempts"],
        lastError=incident["last_error"],
        history=history,
    )


@app.post("/v1/alerts", response_model=IncidentResponse)
async def create_alert(payload: AlertPayload) -> IncidentResponse:
    app.state.alert_counter.add(1, {"source": payload.source, "status": payload.status})

    store = app.state.store
    summary = build_summary(payload)

    existing = store.get_open_by_fingerprint(payload.fingerprint)
    if existing:
        return _to_incident_response(existing)

    incident_id = new_incident_id()
    artifact_path = write_evidence(
        app.state.artifact_dir,
        incident_id,
        payload.model_dump(),
        summary.model_dump(),
    )
    try:
        incident = store.create_incident(
            incident_id=incident_id,
            fingerprint=payload.fingerprint,
            summary=summary.model_dump(),
            artifact_path=artifact_path,
        )
    except sqlite3.IntegrityError:
        try:
            Path(artifact_path).unlink(missing_ok=True)
        except OSError:
            logger.exception("failed to clean orphan evidence file %s", artifact_path)
        existing = store.get_open_by_fingerprint(payload.fingerprint)
        if existing:
            return _to_incident_response(existing)
        raise
    return _to_incident_response(incident)


@app.get("/v1/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: str) -> IncidentResponse:
    store = app.state.store
    try:
        incident = store.get_incident(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="incident not found") from exc
    return _to_incident_response(incident)


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
    return _to_incident_response(incident)
