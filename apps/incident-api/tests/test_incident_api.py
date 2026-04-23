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
