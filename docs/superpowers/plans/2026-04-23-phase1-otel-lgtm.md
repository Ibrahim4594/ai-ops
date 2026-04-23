# Phase 1 OTel + LGTM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a root `docker-compose.yml` that runs pinned `grafana/otel-lgtm:0.25.0` plus a FastAPI `sample-service` exporting OTLP (HTTP/protobuf) to the bundle, with README verification steps matching the approved spec.

**Architecture:** Two services on one Docker network: `otel-lgtm` receives OTLP on 4318; `sample-service` sets `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-lgtm:4318` and instruments FastAPI plus manual span/metric/log on `/work`. Grafana on host port 3000 for Explore.

**Tech stack:** Docker Compose, `grafana/otel-lgtm:0.25.0`, Python 3.12, FastAPI, Uvicorn, OpenTelemetry SDK + OTLP HTTP exporters + FastAPI/logging auto-instrumentation, pytest + httpx.

---

### Task 1: Repository hygiene

**Files:**

- Create: `.gitignore`
- Create: `docs/superpowers/plans/2026-04-23-phase1-otel-lgtm.md` (this file)

- [ ] **Step 1: Add `.gitignore`** (Python / Docker / venv noise)

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
venv/
.env
*.egg-info/
dist/
build/
.DS_Store
```

- [ ] **Step 2: Initialize git (if missing) and commit spec + plan**

Run from repo root `c:\Users\ibrah\Desktop\ai-ops`:

```bash
git init
git add docs/superpowers/specs/2026-04-23-phase1-otel-lgtm-design.md docs/superpowers/plans/2026-04-23-phase1-otel-lgtm.md .gitignore
git commit -m "docs: Phase 1 OTel LGTM spec and implementation plan"
```

---

### Task 2: Root Docker Compose

**Files:**

- Create: `docker-compose.yml`

- [ ] **Step 1: Add compose** — `otel-lgtm` with image `grafana/otel-lgtm:0.25.0`, publish `3000`, `4317`, `4318`, named volume `otel-lgtm-data:/data`; `sample-service` build `./apps/sample-service`, publish `8000`, env vars per spec, `depends_on: [otel-lgtm]`.

Validate:

```bash
docker compose config
```

Expected: YAML parses with no errors.

---

### Task 3: Sample service application code

**Files:**

- Create: `apps/sample-service/requirements.txt`
- Create: `apps/sample-service/app/__init__.py` (empty)
- Create: `apps/sample-service/app/main.py`

- [ ] **Step 1: Pin dependencies** — `apps/sample-service/requirements.txt` (runtime: FastAPI, Uvicorn, OTel API/SDK, OTLP HTTP exporter, FastAPI + logging instrumentations, aligned **1.27.0 / 0.48b0**); `apps/sample-service/requirements-dev.txt` includes `-r requirements.txt` plus `pytest` and `httpx`.

- [ ] **Step 2: Implement `app/main.py`** — `GET /healthz`, `GET /work` with nested span, counter `sample_service.work_requests`, structured log line; `configure_telemetry()` sets `TracerProvider` + `BatchSpanProcessor(OTLPSpanExporter())`, `MeterProvider` + `PeriodicExportingMetricReader(OTLPMetricExporter())`, `LoggingInstrumentor`; `FastAPIInstrumentor.instrument_app(app)` after configuration; respect `DISABLE_OTEL=1` for pytest (skip exporters).

---

### Task 4: Sample service container

**Files:**

- Create: `apps/sample-service/Dockerfile`

- [ ] **Step 1: Dockerfile** — `python:3.12-slim`, `WORKDIR /app`, copy `requirements.txt`, `pip install`, copy `app/`, `EXPOSE 8000`, `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000`.

---

### Task 5: Tests

**Files:**

- Create: `apps/sample-service/tests/conftest.py`
- Create: `apps/sample-service/tests/test_app.py`

- [ ] **Step 1: `conftest.py`** — set `os.environ["DISABLE_OTEL"] = "1"` before importing the app.

- [ ] **Step 2: Tests** — `TestClient` against app: `/healthz` returns 200 and JSON `status`; `/work` returns 200.

Run (from `apps/sample-service` with venv optional):

```bash
cd apps/sample-service
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

Expected: all tests pass.

---

### Task 6: README and verification

**Files:**

- Create: `README.md`

- [ ] **Step 1: README** — prerequisites (Docker Desktop + WSL2), `docker compose up --build`, URLs (`http://localhost:3000`, `http://localhost:8000/work`), Grafana default `admin`/`admin`, Explore checklist (traces/logs/metrics), troubleshooting (OTLP env, port conflicts, `depends_on` not waiting for healthy LGTM — retry after a few seconds).

- [ ] **Step 2: Full stack smoke** (manual)

```bash
docker compose up --build -d
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/work
```

Open Grafana Explore and confirm signals after repeated `/work` calls.

---

## Spec coverage (self-review)

| Spec item | Task |
|-----------|------|
| `grafana/otel-lgtm:0.25.0` | Task 2 |
| Ports 3000, 4317, 4318 | Task 2 |
| Optional `/data` volume | Task 2 (included) |
| OTLP http/protobuf, endpoint in-compose | Task 2 env |
| FastAPI + OTel SDK | Tasks 3–4 |
| `/healthz`, `/work` behavior | Task 3 |
| Service resource attrs | Task 2 env + Task 3 |
| Verification / troubleshooting in README | Task 6 |

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-23-phase1-otel-lgtm.md`.

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks.

**2. Inline Execution** — run tasks sequentially in this session with checkpoints.

Which approach?

After approval, **inline execution** was used in-session to land the scaffold; Phase 2 can switch to **subagent-driven** for larger deltas.
