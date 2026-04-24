import os
import time

from fastapi.testclient import TestClient

from app.main import app


def _wait_for_status(client: TestClient, incident_id: str, status: str, timeout_seconds: float = 3.0) -> dict:
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        response = client.get(f"/v1/incidents/{incident_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] == status:
            return last
        time.sleep(0.05)
    raise AssertionError(f"incident {incident_id} did not reach status={status}; last={last}")


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
    assert body["executionAttempts"] == 0
    assert body["maxExecutionAttempts"] == 3
    assert body["history"][0]["eventType"] == "incident_created"


def test_duplicate_alert_while_active_returns_same_incident() -> None:
    payload = {
        "source": "alertmanager",
        "fingerprint": "duplicate-fingerprint-a",
        "status": "firing",
        "startsAt": "2026-04-23T12:01:00Z",
        "labels": {"alertname": "HighCPU", "service": "aiops-sample-service", "severity": "warning"},
        "annotations": {"summary": "CPU over threshold"},
    }

    with TestClient(app) as client:
        first = client.post("/v1/alerts", json=payload)
        second = client.post("/v1/alerts", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["incidentId"] == first.json()["incidentId"]


def test_approve_runs_execution_to_done() -> None:
    payload = {
        "source": "alertmanager",
        "fingerprint": "latency-service-a",
        "status": "firing",
        "startsAt": "2026-04-23T12:05:00Z",
        "labels": {"alertname": "HighLatency", "service": "aiops-sample-service", "severity": "warning"},
        "annotations": {"summary": "p95 latency high"},
    }

    with TestClient(app) as client:
        created = client.post("/v1/alerts", json=payload).json()
        incident_id = created["incidentId"]

        fetched = client.get(f"/v1/incidents/{incident_id}")
        assert fetched.status_code == 200
        assert fetched.json()["incidentId"] == incident_id

        decision = client.post(
            f"/v1/incidents/{incident_id}/decision",
            json={"decision": "approve", "actor": "human@local", "reason": "confirmed impact"},
        )
        assert decision.status_code == 200

        done = _wait_for_status(client, incident_id, "done")

    assert done["executionAttempts"] == 0
    assert done["lastError"] is None
    history_types = [entry["eventType"] for entry in done["history"]]
    assert "decision_recorded" in history_types
    assert "execution_started" in history_types
    assert "execution_succeeded" in history_types


def test_reject_keeps_incident_out_of_execution() -> None:
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

        decision = client.post(
            f"/v1/incidents/{incident_id}/decision",
            json={"decision": "reject", "actor": "human@local", "reason": "false positive"},
        )
        assert decision.status_code == 200

        time.sleep(0.2)
        fetched = client.get(f"/v1/incidents/{incident_id}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "rejected"
    history_types = [entry["eventType"] for entry in body["history"]]
    assert "execution_started" not in history_types


def test_execution_failure_retries_then_fails() -> None:
    payload = {
        "source": "alertmanager",
        "fingerprint": "critical-will-fail",
        "status": "firing",
        "startsAt": "2026-04-23T12:15:00Z",
        "labels": {"alertname": "CoreSystemDown", "service": "aiops-sample-service", "severity": "critical"},
        "annotations": {"summary": "action should fail"},
    }

    previous = os.environ.get("INCIDENT_ACTION_FAIL_ON_SEVERITY")
    os.environ["INCIDENT_ACTION_FAIL_ON_SEVERITY"] = "critical"
    try:
        with TestClient(app) as client:
            created = client.post("/v1/alerts", json=payload).json()
            incident_id = created["incidentId"]

            approved = client.post(
                f"/v1/incidents/{incident_id}/decision",
                json={"decision": "approve", "actor": "human@local", "reason": "start execution"},
            )
            assert approved.status_code == 200

            failed = _wait_for_status(client, incident_id, "failed")
    finally:
        if previous is None:
            os.environ.pop("INCIDENT_ACTION_FAIL_ON_SEVERITY", None)
        else:
            os.environ["INCIDENT_ACTION_FAIL_ON_SEVERITY"] = previous

    assert failed["executionAttempts"] == failed["maxExecutionAttempts"]
    assert failed["lastError"] is not None
    history_types = [entry["eventType"] for entry in failed["history"]]
    assert history_types.count("execution_started") >= 1
    assert "execution_retry_scheduled" in history_types
    assert history_types[-1] == "execution_failed"


def test_decision_unknown_incident_returns_404() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/incidents/inc_does_not_exist/decision",
            json={"decision": "approve", "actor": "human@local", "reason": "n/a"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "incident not found"


def test_recover_stuck_executing_incident() -> None:
    payload = {
        "source": "alertmanager",
        "fingerprint": "recover-stuck-executing",
        "status": "firing",
        "startsAt": "2026-04-23T12:20:00Z",
        "labels": {"alertname": "HighCPU", "service": "aiops-sample-service", "severity": "warning"},
        "annotations": {"summary": "simulate crash recovery"},
    }

    with TestClient(app) as client:
        created = client.post("/v1/alerts", json=payload).json()
        incident_id = created["incidentId"]

        # Force a stuck state as if the process crashed mid-execution.
        with app.state.store._tx(immediate=True) as conn:  # noqa: SLF001 - explicit test hook
            conn.execute(
                "UPDATE incidents SET status = 'executing' WHERE id = ?",
                (incident_id,),
            )

        recovered = app.state.store.recover_stuck_executions()
        assert recovered == 1

        fetched = client.get(f"/v1/incidents/{incident_id}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "approved"
    history_types = [entry["eventType"] for entry in body["history"]]
    assert "execution_recovered" in history_types
