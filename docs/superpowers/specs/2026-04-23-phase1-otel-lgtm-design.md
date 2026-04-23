# Phase 1 design: OTel-first local observability foundation (LGTM bundle)

Date: 2026-04-23  
Repo root: `c:\Users\ibrah\Desktop\ai-ops`

## Purpose

Create a **reproducible local observability stack** that will later feed an “evidence-first” incident agent. Phase 1 proves we can generate and observe **metrics, logs, and traces** with minimal moving parts on **Docker Desktop + WSL2**.

This milestone intentionally does **not** include Kubernetes, Alertmanager, or LLM orchestration yet.

## Non-goals (explicit)

- Production-grade HA, auth hardening beyond defaults, long retention tuning
- Full security sandboxing for autonomous remediation
- Cloud vendor integrations

## Constraints / assumptions

- Host: Windows with **Docker Desktop** using **WSL2 integration**
- Machine RAM is finite (16GB). Compose defaults should be conservative; docs will instruct users not to run multiple huge stacks concurrently.
- OTLP defaults follow OpenTelemetry guidance used by `grafana/otel-lgtm`:
  - `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`
  - `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318` (host) / `http://otel-lgtm:4318` (in-compose network)

## Architecture

### Components

1. `otel-lgtm` (single container) from Docker image `grafana/otel-lgtm:<pinned>`
   - Bundles Grafana + Prometheus + Loki + Tempo + Pyroscope + OpenTelemetry Collector (per upstream README)
2. `sample-service` (container)
   - Minimal HTTP API (FastAPI) instrumented with OpenTelemetry SDK
   - Exports OTLP to the collector inside the `otel-lgtm` container over the compose network

### Network boundaries

- Public ports published only for what we need to verify in a browser and to ingest OTLP from the host (if desired):
  - Grafana: `3000`
  - OTLP: `4317` (gRPC) and `4318` (HTTP) as per upstream expectations
  - Optional: `9090` (Prometheus) if we want direct UI access during debugging (can be omitted to reduce surface area)

### Persistence

- Optional named volume mounted to `/data` in `otel-lgtm` to persist Grafana/tempo/loki/prometheus state across restarts (dev convenience).

## Sample service behavior

Endpoints (initial):

- `GET /healthz` → plain OK (uninstrumented minimal liveness)
- `GET /work` → does a small amount of “fake work”:
  - nested span
  - increments a request counter metric
  - emits a structured log line correlated with trace context

Service identity:

- `service.name=aiops-sample-service`
- `service.version=0.1.0`
- `deployment.environment=local`

## Developer workflows

### Primary workflow (recommended)

`docker compose up --build` from repo root:

- builds `sample-service`
- starts `otel-lgtm`

### Verification steps (acceptance)

1. `docker compose ps` shows both services healthy (or running + ports bound)
2. Grafana loads at `http://localhost:3000` with default credentials `admin` / `admin`
3. In Grafana Explore:
   - traces exist for `/work`
   - logs exist and correlate (trace id where applicable)
   - metrics show increased traffic after hitting `/work` repeatedly

### Troubleshooting notes (to include in README)

- If Grafana loads but no signals: confirm OTLP endpoint and protocol env vars on `sample-service`
- If OTLP port conflicts: identify conflicting local services and adjust published ports consistently

## Risks / mitigations

- **Resource pressure**: document expected RAM/CPU footprint; keep only required ports open
- **Image drift**: pin `grafana/otel-lgtm` to a specific semver tag (not `latest`)

## Phase 2 preview (not in this spec)

Add `k3d`, in-cluster Prometheus scraping, Alertmanager → webhook → agent loop using local Ollama via `host.docker.internal`.

## Open decisions (defaults chosen)

- Pin image tag to **`0.25.0`** (observed as a current tag alongside `latest` on Docker Hub API at design time)
- Publish **Grafana + OTLP** ports at minimum; publish Prometheus `9090` optionally for easier debugging
