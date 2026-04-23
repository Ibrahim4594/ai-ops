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
