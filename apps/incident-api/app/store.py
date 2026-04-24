from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
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
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _tx(self, *, immediate: bool = False):
        conn = self._conn()
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            else:
                conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
                    execution_attempts INTEGER NOT NULL DEFAULT 0,
                    max_execution_attempts INTEGER NOT NULL DEFAULT 3,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint ON incidents(fingerprint);
                CREATE INDEX IF NOT EXISTS idx_incidents_status_updated_at ON incidents(status, updated_at);

                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    FOREIGN KEY (incident_id) REFERENCES incidents(id)
                );

                CREATE TABLE IF NOT EXISTS incident_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    message TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (incident_id) REFERENCES incidents(id)
                );
                """
            )
            self._migrate_incident_columns(conn)
            self._migrate_active_fingerprint_unique_index(conn)

    def _migrate_incident_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(incidents)")}
        if "execution_attempts" not in columns:
            conn.execute("ALTER TABLE incidents ADD COLUMN execution_attempts INTEGER NOT NULL DEFAULT 0")
        if "max_execution_attempts" not in columns:
            conn.execute("ALTER TABLE incidents ADD COLUMN max_execution_attempts INTEGER NOT NULL DEFAULT 3")
        if "last_error" not in columns:
            conn.execute("ALTER TABLE incidents ADD COLUMN last_error TEXT")

    def _migrate_active_fingerprint_unique_index(self, conn: sqlite3.Connection) -> None:
        active_statuses = ("pending_approval", "approved", "executing")
        placeholders = ",".join(["?"] * len(active_statuses))

        dupes = conn.execute(
            f"""
            SELECT fingerprint, COUNT(*) AS c
            FROM incidents
            WHERE status IN ({placeholders})
            GROUP BY fingerprint
            HAVING c > 1
            """,
            active_statuses,
        ).fetchall()

        for row in dupes:
            fingerprint = row["fingerprint"]
            ids = [
                r["id"]
                for r in conn.execute(
                    f"""
                    SELECT id
                    FROM incidents
                    WHERE fingerprint = ? AND status IN ({placeholders})
                    ORDER BY created_at ASC, id ASC
                    """,
                    (fingerprint, *active_statuses),
                ).fetchall()
            ]
            for incident_id in ids[:-1]:
                conn.execute("DELETE FROM incident_events WHERE incident_id = ?", (incident_id,))
                conn.execute("DELETE FROM decisions WHERE incident_id = ?", (incident_id,))
                conn.execute("DELETE FROM incidents WHERE id = ?", (incident_id,))

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_active_fingerprint
            ON incidents(fingerprint)
            WHERE status IN ('pending_approval', 'approved', 'executing')
            """
        )

    def create_incident(self, incident_id: str, fingerprint: str, summary: dict, artifact_path: str) -> dict:
        now = utc_now()
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO incidents (id, fingerprint, status, summary_json, artifact_path, created_at, updated_at)
                VALUES (?, ?, 'pending_approval', ?, ?, ?, ?)
                """,
                (incident_id, fingerprint, json.dumps(summary), artifact_path, now, now),
            )
            self._insert_event(
                conn,
                incident_id=incident_id,
                event_type="incident_created",
                from_status=None,
                to_status="pending_approval",
                message="Incident created from alert intake.",
            )
        return self.get_incident(incident_id)

    def get_open_by_fingerprint(self, fingerprint: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM incidents
                WHERE fingerprint = ?
                  AND status IN ('pending_approval', 'approved', 'executing')
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

    def list_events(self, incident_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT event_type, from_status, to_status, message, created_at
                FROM incident_events
                WHERE incident_id = ?
                ORDER BY id ASC
                """,
                (incident_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_decision(self, incident_id: str, decision: str, actor: str, reason: str) -> dict:
        now = utc_now()
        next_status = "approved" if decision == "approve" else "rejected"
        with self._tx() as conn:
            updated = conn.execute(
                """
                UPDATE incidents
                SET status = ?, updated_at = ?
                WHERE id = ? AND status = 'pending_approval'
                """,
                (next_status, now, incident_id),
            )
            if updated.rowcount != 1:
                raise ValueError("incident is not pending approval")

            conn.execute(
                "INSERT INTO decisions (incident_id, decision, actor, reason, decided_at) VALUES (?, ?, ?, ?, ?)",
                (incident_id, decision, actor, reason, now),
            )
            self._insert_event(
                conn,
                incident_id=incident_id,
                event_type="decision_recorded",
                from_status="pending_approval",
                to_status=next_status,
                message=f"Decision '{decision}' recorded by {actor}: {reason}",
            )
        return self.get_incident(incident_id)

    def claim_next_for_execution(self) -> dict | None:
        with self._tx(immediate=True) as conn:
            row = conn.execute(
                """
                SELECT id FROM incidents
                WHERE status = 'approved'
                  AND execution_attempts < max_execution_attempts
                ORDER BY updated_at ASC, id ASC
                LIMIT 1
                """,
            ).fetchone()
            if not row:
                return None

            incident_id = row["id"]
            now = utc_now()
            updated = conn.execute(
                """
                UPDATE incidents
                SET status = 'executing', updated_at = ?
                WHERE id = ? AND status = 'approved'
                """,
                (now, incident_id),
            )
            if updated.rowcount != 1:
                return None

            self._insert_event(
                conn,
                incident_id=incident_id,
                event_type="execution_started",
                from_status="approved",
                to_status="executing",
                message="Execution worker started action run.",
            )

        return self.get_incident(incident_id)

    def mark_execution_success(self, incident_id: str) -> dict:
        now = utc_now()
        with self._tx() as conn:
            updated = conn.execute(
                """
                UPDATE incidents
                SET status = 'done', last_error = NULL, updated_at = ?
                WHERE id = ? AND status = 'executing'
                """,
                (now, incident_id),
            )
            if updated.rowcount != 1:
                raise ValueError("incident is not executing")

            self._insert_event(
                conn,
                incident_id=incident_id,
                event_type="execution_succeeded",
                from_status="executing",
                to_status="done",
                message="Execution finished successfully.",
            )
        return self.get_incident(incident_id)

    def mark_execution_failure(self, incident_id: str, error_message: str) -> dict:
        with self._tx() as conn:
            row = conn.execute(
                """
                SELECT execution_attempts, max_execution_attempts
                FROM incidents
                WHERE id = ? AND status = 'executing'
                """,
                (incident_id,),
            ).fetchone()
            if not row:
                raise ValueError("incident is not executing")

            attempts = int(row["execution_attempts"]) + 1
            max_attempts = int(row["max_execution_attempts"])
            now = utc_now()
            will_retry = attempts < max_attempts
            next_status = "approved" if will_retry else "failed"
            event_type = "execution_retry_scheduled" if will_retry else "execution_failed"
            message = (
                f"Execution attempt {attempts}/{max_attempts} failed: {error_message}. "
                + ("Retry scheduled." if will_retry else "No retries left.")
            )

            updated = conn.execute(
                """
                UPDATE incidents
                SET status = ?, execution_attempts = ?, last_error = ?, updated_at = ?
                WHERE id = ? AND status = 'executing'
                """,
                (next_status, attempts, error_message, now, incident_id),
            )
            if updated.rowcount != 1:
                raise ValueError("incident is not executing")

            self._insert_event(
                conn,
                incident_id=incident_id,
                event_type=event_type,
                from_status="executing",
                to_status=next_status,
                message=message,
            )
        return self.get_incident(incident_id)

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        incident_id: str,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        message: str,
        metadata: dict | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO incident_events (
                incident_id,
                event_type,
                from_status,
                to_status,
                message,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                event_type,
                from_status,
                to_status,
                message,
                json.dumps(metadata) if metadata else None,
                utc_now(),
            ),
        )
