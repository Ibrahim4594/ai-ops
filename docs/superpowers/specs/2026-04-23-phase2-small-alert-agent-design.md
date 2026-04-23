# Phase 2 design: Small incident loop (3-5 day slice)

Date: 2026-04-23  
Repo root: `c:\Users\ibrah\Desktop\ai-ops`

## Purpose

Build a complete local incident loop on top of Phase 1:

1. receive alert payload
2. generate incident summary + evidence artifact
3. require explicit human approve/reject decision

This phase is intentionally scoped to be finished quickly while still producing a strong portfolio demo.

## Non-goals (explicit)

- No auto-remediation execution (only decision capture in this phase)
- No external SaaS integrations (Slack, PagerDuty, Jira, etc.)
- No production hardening, auth/RBAC, or multi-tenant support
- No Kubernetes migration in this slice (kept for next phase)

## Constraints / assumptions

- Host environment remains Windows + Docker Desktop + WSL2.
- Preserve Phase 1 behavior and endpoints:
  - `sample-service` `/healthz` and `/work`
  - `otel-lgtm` stack and Grafana verification workflow
- Keep runtime simple and reliable: compose-first for this slice.
- Keep data local with volume-backed persistence.

## Approaches considered

1. **Compose-only incident loop (recommended)**
   - Add one new `incident-api` service to current compose stack.
   - Fastest to deliver complete flow with minimal infra risk.
2. **Hybrid (compose + partial k3d)**
   - Adds infra complexity during the first incident-loop milestone.
   - Higher setup/debug overhead for little immediate value.
3. **k3d-first**
   - Better long-term parity, but too heavy for a 3-5 day first loop.

**Recommendation:** Compose-only now, then k3d in next phase once incident contracts are stable.

## Architecture

### Components

1. `otel-lgtm` (existing)
   - receives telemetry and provides Grafana/Prom/Loki/Tempo views
2. `sample-service` (existing)
   - still generates baseline traffic and telemetry
3. `incident-api` (new)
   - receives alert payloads
   - normalizes + summarizes incident context
   - writes evidence artifact
   - stores incident state
   - exposes approve/reject endpoint

### Data and persistence

- SQLite DB in `incident-api` container at `/data/incidents.db`
- Artifact files at `/data/artifacts/<incident_id>.json`
- Compose named volume to persist `/data`

## API surface (initial)

### `POST /v1/alerts`

Accepts one alert payload and creates/updates incident.

Output:
- `incidentId`
- `status` (`pending_approval`)
- `summary` (title/severity/what_happened/next_action)
- `evidenceArtifactPath`

### `GET /v1/incidents/{incident_id}`

Returns incident record with current status, summary, and artifact metadata.

### `POST /v1/incidents/{incident_id}/decision`

Input:
- `decision` (`approve` or `reject`)
- `actor`
- `reason`

Output:
- updated incident status
- decision timestamp

## Incident lifecycle

`new/firing alert -> pending_approval -> approved|rejected`

Rules:
- decisions only allowed from `pending_approval`
- duplicate alerts with same fingerprint can attach to same open incident

## Evidence artifact (v1)

Each incident writes a JSON artifact containing:

- raw alert payload
- normalized incident fields used for summary
- generated summary text
- local investigation pointers (for example Grafana Explore URL/time window)
- decision trail once human decision is made

## Verification / acceptance criteria

1. Posting an alert creates incident + evidence file and returns `pending_approval`.
2. Fetch endpoint returns created incident and summary content.
3. Decision endpoint transitions to `approved` or `rejected` with actor/reason/timestamp.
4. Invalid decisions return clear 4xx validation errors.
5. Incident data survives service restart (volume-backed persistence).
6. `incident-api` telemetry appears in Grafana (logs/traces/metrics at minimum basic presence).
7. Existing Phase 1 checks still pass (`sample-service` endpoints + compose health).

## Risks / mitigations

- **Alert schema drift**: store raw payload unchanged and normalize minimally.
- **Scope creep**: keep summary deterministic and local (no extra orchestration yet).
- **State corruption**: use SQLite transactions and atomic artifact writes.
- **Noisy local startup timing**: document retry behavior and keep health checks simple.

## Deliverables (this slice)

- new `apps/incident-api` service with tests
- compose integration for `incident-api`
- evidence artifacts persisted to local volume
- docs update with local run + validation steps

## Next phase preview (after this)

- Introduce k3d + Alertmanager-native webhook path
- Add controlled, allowlisted remediation proposal/execution stage
- Expand evidence with richer Prom/Loki/Tempo correlation
