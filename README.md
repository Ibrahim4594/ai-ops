# ai-ops

Phase 1 delivers a **local OpenTelemetry + LGTM** stack on Docker (Grafana, Prometheus, Loki, Tempo, Pyroscope, and an OpenTelemetry Collector inside [`grafana/otel-lgtm`](https://hub.docker.com/r/grafana/otel-lgtm)) plus a small **FastAPI sample** that emits traces, metrics, and logs over **OTLP HTTP/protobuf**.

## Prerequisites

- **Docker Desktop** with **WSL2** integration (Linux containers)
- Enough free RAM for the LGTM bundle (see [Grafana `otel-lgtm` docs](https://grafana.com/docs/grafana-cloud/send-data/alloy/collect/opentelemetry-to-lgtm-stack/)); avoid running several heavy stacks at once on 16GB machines

## Quick start

From the repo root:

```bash
docker compose up --build
```

Wait until `otel-lgtm` has finished starting (first boot can take a short while). If `sample-service` logs OTLP errors, wait a few seconds and hit the endpoints again.

## Endpoints

| URL | Purpose |
|-----|---------|
| http://localhost:8000/healthz | Liveness JSON |
| http://localhost:8000/work | Nested span, counter metric, log line |
| http://localhost:3000 | Grafana (default `admin` / `admin`) |
| OTLP gRPC / HTTP on host | `4317` / `4318` |

## Verification (acceptance)

1. `docker compose ps` — both services up; ports `3000`, `8000`, `4317`, `4318` published
2. `curl http://localhost:8000/healthz` and `curl http://localhost:8000/work` (run `/work` several times)
3. Open Grafana → **Explore** — confirm **traces** for `aiops-sample-service` / route `/work`, **logs** mentioning `finished fake work`, and **metrics** including `sample_service.work_requests` after repeated calls (metric export interval is a few seconds)

## Sample service environment (compose)

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-lgtm:4318`
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`
- `OTEL_SERVICE_NAME=aiops-sample-service`
- `OTEL_RESOURCE_ATTRIBUTES=service.version=0.1.0,deployment.environment=local`

## Tests (local Python)

```bash
cd apps/sample-service
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -v
```

Tests set `DISABLE_OTEL=1` so no collector is required. OTLP/protobuf code loads only when telemetry is enabled (so very new Python versions can still run unit tests).

Use **Python 3.12** (as in the Dockerfile) or a current 3.11–3.13 runtime for parity with production images.

## Troubleshooting

- **Grafana works but no telemetry** — confirm the sample container env matches the table above; from the host, OTLP would use `http://127.0.0.1:4318`, but in Compose the hostname must be `otel-lgtm`
- **Port already in use** — change the left side of a `ports:` mapping in `docker-compose.yml` consistently (Grafana `3000`, OTLP `4317`/`4318`, app `8000`)
- **`depends_on` does not wait for readiness** — LGTM may need extra seconds on first start; retry `curl` to `/work` or restart only `sample-service` with `docker compose restart sample-service`

## Design docs

- Spec: `docs/superpowers/specs/2026-04-23-phase1-otel-lgtm-design.md`
- Plan: `docs/superpowers/plans/2026-04-23-phase1-otel-lgtm.md`
