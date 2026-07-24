"""SQLite-backed durable job queue for the external worker process."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from price_mixer.runtime_paths import get_runtime_paths

DEFAULT_JOB_DB = get_runtime_paths().data_file("jobs.db")
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class DurableJobQueue:
    def __init__(self, path=None, *, clock=time.time):
        self.path = Path(path or DEFAULT_JOB_DB).resolve()
        self.clock = clock

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS durable_jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 1,
                    available_at REAL NOT NULL,
                    lease_until REAL NOT NULL DEFAULT 0,
                    worker_id TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    error_type TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    started_at REAL NOT NULL DEFAULT 0,
                    finished_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_durable_jobs_claim
                    ON durable_jobs(state, available_at, created_at);
                CREATE INDEX IF NOT EXISTS idx_durable_jobs_dedupe
                    ON durable_jobs(kind, dedupe_key, created_at DESC);
                CREATE TABLE IF NOT EXISTS durable_worker_heartbeats (
                    worker_id TEXT PRIMARY KEY,
                    updated_at REAL NOT NULL
                );
                """
            )

    def enqueue(
        self,
        kind,
        payload,
        *,
        dedupe_key="",
        max_attempts=2,
        job_id=None,
        reuse_active=False,
    ):
        self.initialize()
        now = float(self.clock())
        job_id = str(job_id or uuid.uuid4().hex)
        kind = str(kind or "").strip()
        if not kind:
            raise ValueError("job kind is required")
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        superseded = []
        with self._connection(immediate=True) as connection:
            if dedupe_key:
                if reuse_active:
                    active = connection.execute(
                        "SELECT * FROM durable_jobs WHERE kind=? AND dedupe_key=? "
                        "AND state IN ('queued','running') "
                        "ORDER BY created_at DESC,rowid DESC LIMIT 1",
                        (kind, str(dedupe_key)),
                    ).fetchone()
                    if active is not None:
                        return {
                            "job_id": active["job_id"],
                            "superseded": [],
                            "reused": True,
                        }
                rows = connection.execute(
                    "SELECT job_id,payload_json FROM durable_jobs WHERE kind=? AND dedupe_key=? AND state='queued'",
                    (kind, str(dedupe_key)),
                ).fetchall()
                superseded = [
                    {
                        "job_id": row["job_id"],
                        "payload": _decode_payload(row["payload_json"]),
                    }
                    for row in rows
                ]
                connection.execute(
                    "UPDATE durable_jobs SET state='cancelled',"
                    "message='superseded',finished_at=?,updated_at=? "
                    "WHERE kind=? AND dedupe_key=? AND state='queued'",
                    (now, now, kind, str(dedupe_key)),
                )
            connection.execute(
                "INSERT INTO durable_jobs "
                "(job_id,kind,dedupe_key,payload_json,state,max_attempts,"
                "available_at,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    kind,
                    str(dedupe_key),
                    payload_json,
                    "queued",
                    max(1, int(max_attempts)),
                    now,
                    now,
                    now,
                ),
            )
        return {"job_id": job_id, "superseded": superseded, "reused": False}

    def claim(self, worker_id, *, kinds=None, lease_seconds=900):
        self.initialize()
        now = float(self.clock())
        worker_id = str(worker_id or "").strip()
        if not worker_id:
            raise ValueError("worker_id is required")
        with self._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE durable_jobs SET state='queued',worker_id='',"
                "lease_until=0,available_at=?,message='lease expired',updated_at=? "
                "WHERE state='running' AND lease_until<? AND attempts<max_attempts",
                (now, now, now),
            )
            connection.execute(
                "UPDATE durable_jobs SET state='failed',worker_id='',"
                "lease_until=0,error_type='LeaseExpired',"
                "message='lease expired after final attempt',finished_at=?,updated_at=? "
                "WHERE state='running' AND lease_until<? AND attempts>=max_attempts",
                (now, now, now),
            )
            params: list[object] = [now]
            kind_clause = ""
            normalized_kinds = [str(kind).strip() for kind in (kinds or []) if str(kind).strip()]
            if normalized_kinds:
                placeholders = ",".join("?" for _ in normalized_kinds)
                kind_clause = f" AND kind IN ({placeholders})"
                params.extend(normalized_kinds)
            row = connection.execute(
                "SELECT * FROM durable_jobs WHERE state='queued' "
                f"AND available_at<=?{kind_clause} "
                "ORDER BY created_at,rowid LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                return None
            changed = connection.execute(
                "UPDATE durable_jobs SET state='running',attempts=attempts+1,"
                "worker_id=?,lease_until=?,started_at=CASE WHEN started_at=0 "
                "THEN ? ELSE started_at END,updated_at=? "
                "WHERE job_id=? AND state='queued'",
                (
                    worker_id,
                    now + max(1, int(lease_seconds)),
                    now,
                    now,
                    row["job_id"],
                ),
            ).rowcount
            if changed != 1:
                return None
            claimed = connection.execute(
                "SELECT * FROM durable_jobs WHERE job_id=?",
                (row["job_id"],),
            ).fetchone()
        return _row_payload(claimed)

    def complete(self, job_id, *, message="completed", worker_id=None):
        return self._finish(
            job_id,
            "succeeded",
            message=message,
            worker_id=worker_id,
        )

    def cancel(self, job_id, *, message="cancelled"):
        self.initialize()
        now = float(self.clock())
        with self._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE durable_jobs SET state='cancelled',message=?,lease_until=0,"
                "worker_id='',finished_at=?,updated_at=? "
                "WHERE job_id=? AND state IN ('queued','running')",
                (str(message), now, now, str(job_id)),
            )
        return self.get(job_id)

    def resume(self, job_id):
        self.initialize()
        now = float(self.clock())
        with self._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE durable_jobs SET state='queued',attempts=0,available_at=?,"
                "lease_until=0,worker_id='',message='resumed',error_type='',"
                "started_at=0,finished_at=0,updated_at=? "
                "WHERE job_id=? AND state IN ('failed','cancelled')",
                (now, now, str(job_id)),
            )
        return self.get(job_id)

    def fail(self, job_id, error, *, retry_delay=5, worker_id=None):
        self.initialize()
        now = float(self.clock())
        error_type = type(error).__name__
        with self._connection(immediate=True) as connection:
            current = connection.execute(
                "SELECT attempts,max_attempts,state,worker_id FROM durable_jobs WHERE job_id=?",
                (str(job_id),),
            ).fetchone()
            if current is None:
                return None
            if current["state"] != "running" or (worker_id is not None and str(current["worker_id"]) != str(worker_id)):
                return self.get(job_id)
            retry = int(current["attempts"]) < int(current["max_attempts"])
            state = "queued" if retry else "failed"
            connection.execute(
                "UPDATE durable_jobs SET state=?,available_at=?,lease_until=0,"
                "worker_id='',error_type=?,message=?,finished_at=?,updated_at=? "
                "WHERE job_id=? AND state='running'",
                (
                    state,
                    now + max(0, float(retry_delay)) if retry else now,
                    error_type,
                    "retry scheduled" if retry else "job failed",
                    0 if retry else now,
                    now,
                    str(job_id),
                ),
            )
        return self.get(job_id)

    def get(self, job_id):
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM durable_jobs WHERE job_id=?",
                (str(job_id),),
            ).fetchone()
        return _row_payload(row) if row is not None else None

    def latest(self, kind, dedupe_key):
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM durable_jobs WHERE kind=? AND dedupe_key=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (str(kind), str(dedupe_key)),
            ).fetchone()
        return _row_payload(row) if row is not None else None

    def is_latest(self, job):
        latest = self.latest(job["kind"], job.get("dedupe_key", ""))
        return latest is not None and latest["job_id"] == job["job_id"]

    def counts(self):
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute("SELECT state,COUNT(*) AS count FROM durable_jobs GROUP BY state").fetchall()
        return {row["state"]: int(row["count"]) for row in rows}

    def heartbeat(self, worker_id):
        self.initialize()
        now = float(self.clock())
        with self._connection(immediate=True) as connection:
            connection.execute(
                "INSERT INTO durable_worker_heartbeats(worker_id,updated_at) "
                "VALUES (?,?) ON CONFLICT(worker_id) DO UPDATE SET "
                "updated_at=excluded.updated_at",
                (str(worker_id), now),
            )
        return now

    def worker_health(self, *, max_age=30):
        self.initialize()
        now = float(self.clock())
        threshold = now - max(1, float(max_age))
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS active,MAX(updated_at) AS latest "
                "FROM durable_worker_heartbeats WHERE updated_at>=?",
                (threshold,),
            ).fetchone()
        active = int(row["active"] or 0)
        latest = float(row["latest"] or 0)
        return {
            "status": "ok" if active else "unavailable",
            "active_workers": active,
            "latest_heartbeat_age_sec": (max(0.0, round(now - latest, 3)) if latest else None),
        }

    def prune_completed(self, *, max_age=7 * 24 * 3600, limit=500):
        """Bound successful/cancelled queue history; retain failures."""
        self.initialize()
        cutoff = float(self.clock()) - max(3600, float(max_age))
        with self._connection(immediate=True) as connection:
            job_ids = [
                row["job_id"]
                for row in connection.execute(
                    "SELECT job_id FROM durable_jobs WHERE state IN "
                    "('succeeded','cancelled') AND finished_at>0 "
                    "AND finished_at<? ORDER BY finished_at LIMIT ?",
                    (cutoff, max(1, int(limit))),
                ).fetchall()
            ]
            if job_ids:
                placeholders = ",".join("?" for _ in job_ids)
                connection.execute(
                    f"DELETE FROM durable_jobs WHERE job_id IN ({placeholders})",
                    job_ids,
                )
        return len(job_ids)

    def _finish(self, job_id, state, *, message, worker_id=None):
        if state not in TERMINAL_STATES:
            raise ValueError("invalid terminal job state")
        self.initialize()
        now = float(self.clock())
        with self._connection(immediate=True) as connection:
            params = [state, str(message), now, now, str(job_id)]
            worker_clause = ""
            if worker_id is not None:
                worker_clause = " AND worker_id=?"
                params.append(str(worker_id))
            connection.execute(
                "UPDATE durable_jobs SET state=?,message=?,lease_until=0,"
                "worker_id='',finished_at=?,updated_at=? "
                f"WHERE job_id=? AND state='running'{worker_clause}",
                params,
            )
        return self.get(job_id)

    @contextmanager
    def _connection(self, *, immediate=False):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _decode_payload(value):
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _row_payload(row):
    result = dict(row)
    result["payload"] = _decode_payload(result.pop("payload_json", "{}"))
    return result
