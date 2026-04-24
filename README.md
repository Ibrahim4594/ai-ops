# ai-ops

`ai-ops` is a small local lab for building and testing alert-driven incident workflows on top of an OpenTelemetry stack.

The repo currently includes three phases:

- **Phase 1:** a local LGTM stack plus a FastAPI sample service that emits traces, metrics, and logs over OTLP.
- **Phase 2:** an `incident-api` service that accepts alerts, creates a simple incident record, writes an evidence artifact, and waits for a human approve or reject decision.
- **Phase 3:** a background execution worker that processes approved incidents, records timeline events, and retries failed actions before marking terminal failure.

## What is running

The default `docker compose` setup starts three services:

- `otel-lgtm` for Grafana, Prometheus, Loki, Tempo, Pyroscope, and the embedded OpenTelemetry Collector
- `sample-service` as the telemetry-producing demo app
- `incident-api` as the human-in-the-loop incident workflow API

Both app services export telemetry to the collector with OTLP HTTP/protobuf.

## Architecture

```text
alert payload
    |
    v
incident-api ------------------> SQLite incident state
    |                                  |
    |                                  v
    +--------------------------> JSON evidence artifact
    |
    +--------------------------> OTLP telemetry

sample-service ----------------> OTLP telemetry

OTLP telemetry ----------------> otel-lgtm ----------------> Grafana
```

## Prerequisites

- Docker Desktop with WSL2 integration and Linux containers enabled
- Enough free memory for the LGTM bundle; avoid stacking several heavy Docker environments on a 16 GB machine

## Quick start

From the repository root:

```bash
docker compose up --build
```

The first startup can take a little longer while `otel-lgtm` initializes. If either app logs temporary OTLP connection errors during boot, wait a few seconds and try the requests again.

## Local endpoints

- `http://localhost:3000` - Grafana (`admin` / `admin`)
- `http://localhost:8000/healthz` - sample-service health check
- `http://localhost:8000/work` - sample-service demo work endpoint
- `http://localhost:8001/healthz` - incident-api health check
- `http://localhost:8001/v1/alerts` - incident intake endpoint
- `http://localhost:8001/v1/incidents/{incident_id}` - fetch incident state
- `http://localhost:8001/v1/incidents/{incident_id}/decision` - approve or reject an incident
- OTLP on the host - gRPC `4317`, HTTP `4318`

## Quick verification

After startup, run the following checks:

1. `docker compose ps`
2. Confirm all three containers are up: `otel-lgtm`, `aiops-sample-service`, and `aiops-incident-api`
3. Hit the sample service:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/work
curl http://localhost:8000/work
```

4. Open Grafana and verify:
   - traces for service `aiops-sample-service`
   - logs containing `finished fake work`
   - metrics including `sample_service.work_requests`

## Phase 2 incident flow

`incident-api` runs at `http://localhost:8001` and persists state on the named Docker volume `incident-data`.

- SQLite database: `/data/incidents.db`
- Evidence artifacts: `/data/artifacts`

Typical flow:

1. Post an alert
2. Fetch the incident record and evidence summary
3. Approve or reject it as a human reviewer

Alert dedupe:

- If an incident is still active (`pending_approval`, `approved`, or `executing`) for the same `fingerprint`, repeated alerts return the existing incident instead of creating duplicates.

Example:

```bash
curl -s -X POST http://localhost:8001/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"source":"alertmanager","fingerprint":"demo-alert-1","status":"firing","startsAt":"2026-04-23T12:00:00Z","labels":{"alertname":"HighCPU","service":"aiops-sample-service","severity":"warning"},"annotations":{"summary":"CPU high"}}'

curl -s http://localhost:8001/v1/incidents/<incident_id>

curl -s -X POST http://localhost:8001/v1/incidents/<incident_id>/decision \
  -H "Content-Type: application/json" \
  -d '{"decision":"approve","actor":"human@local","reason":"confirmed"}'
```

## Phase 3 execution model

Approved incidents are executed by a background worker inside `incident-api`.

State progression:

```text
pending_approval -> approved -> executing -> done
                           \-> executing -> approved (retry) -> executing ...
                           \-> executing -> failed
pending_approval -> rejected
```

Execution behavior:

- Worker polls for `approved` incidents and claims one at a time.
- Every transition is written to incident history (`history` array in API response).
- On failed execution, the worker retries until `maxExecutionAttempts` is reached.
- Terminal statuses are `done`, `rejected`, or `failed`.

Operational environment variables:

- `INCIDENT_WORKER_INTERVAL_SECONDS` (default `1.0`)
- `INCIDENT_ACTION_FAIL_ON_SEVERITY` (optional comma-separated severity list for deterministic failure simulation in local testing)

The `GET /v1/incidents/{incident_id}` response now includes:

- `executionAttempts`
- `maxExecutionAttempts`
- `lastError`
- `history` (ordered timeline of state and decision events)

## Telemetry configuration

Both application containers are configured in `docker-compose.yml` with:

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-lgtm:4318`
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`
- `OTEL_RESOURCE_ATTRIBUTES=service.version=0.1.0,deployment.environment=local`

Service names:

- `aiops-sample-service`
- `aiops-incident-api`

## Running tests locally

Use Python 3.12 for parity with the Dockerfiles. A current 3.11-3.13 runtime should also work for local development.

`sample-service`:

```powershell
cd apps/sample-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest -v
```

`incident-api`:

```powershell
cd apps/incident-api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest -v
```

Tests set `DISABLE_OTEL=1`, so you do not need the collector running to execute the unit test suite.

## Repository layout

```text
apps/
  sample-service/   FastAPI demo service that emits telemetry
  incident-api/     Alert intake and human decision API
docs/
  superpowers/
    specs/          Design notes for each phase
    plans/          Implementation plans for each phase
docker-compose.yml  Local stack definition
```

## Troubleshooting

- If Grafana is up but telemetry is missing, confirm both application containers still point to `http://otel-lgtm:4318`. Inside Compose, the hostname must be `otel-lgtm`, not `127.0.0.1`.
- If a port is already in use, update the host side of the matching `ports:` entry in `docker-compose.yml`.
- `depends_on` does not wait for full readiness. If LGTM is still warming up, retry the requests or restart the app container after Grafana settles.

## Design docs

Phase 1:

- `docs/superpowers/specs/2026-04-23-phase1-otel-lgtm-design.md`
- `docs/superpowers/plans/2026-04-23-phase1-otel-lgtm.md`

Phase 2:

- `docs/superpowers/specs/2026-04-23-phase2-small-alert-agent-design.md`
- `docs/superpowers/plans/2026-04-23-phase2-small-alert-agent.md`
