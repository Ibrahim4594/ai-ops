from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass

from .store import IncidentStore

logger = logging.getLogger(__name__)


@dataclass
class ExecutionActionRunner:
    """Simple action runner stub; replace with real integrations later."""

    fail_on_severities: set[str]

    @classmethod
    def from_env(cls) -> "ExecutionActionRunner":
        configured = os.getenv("INCIDENT_ACTION_FAIL_ON_SEVERITY", "").strip()
        severities = {item.strip().lower() for item in configured.split(",") if item.strip()}
        return cls(fail_on_severities=severities)

    def run(self, incident: dict) -> None:
        summary = json.loads(incident["summary_json"])
        severity = str(summary.get("severity", "")).lower()
        if severity in self.fail_on_severities:
            raise RuntimeError(f"simulated action failure for severity={severity}")


class IncidentExecutionWorker:
    def __init__(self, store: IncidentStore, interval_seconds: float, runner: ExecutionActionRunner) -> None:
        self.store = store
        self.interval_seconds = interval_seconds
        self.runner = runner
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="incident-execution-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                incident = self.store.claim_next_for_execution()
                if incident is None:
                    self._stop_event.wait(self.interval_seconds)
                    continue

                try:
                    self.runner.run(incident)
                    self.store.mark_execution_success(incident["id"])
                except Exception as exc:  # noqa: BLE001 - keep worker resilient.
                    self.store.mark_execution_failure(incident["id"], str(exc))
            except Exception:  # noqa: BLE001 - worker must keep polling.
                logger.exception("incident execution worker loop error")
                self._stop_event.wait(self.interval_seconds)
