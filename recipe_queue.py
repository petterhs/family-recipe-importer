"""Small SQLite-backed queue for recipe-import workers.

The queue stores metadata and recipe drafts, never provider credentials.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

STATUSES = {"pending", "processing", "review", "approved", "imported", "failed"}
ACTIVE_STATUSES = ("pending", "processing", "review", "approved", "imported")


class Queue:
    def __init__(self, path: str | Path, lease_seconds: int = 900) -> None:
        self.path = str(path)
        self.lease_seconds = lease_seconds
        self._conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL,
                worker_id TEXT,
                lease_until REAL,
                attempts INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL DEFAULT '{}',
                draft TEXT,
                warnings TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("payload", "draft", "warnings"):
            if result[key] is not None:
                result[key] = json.loads(result[key])
        return result

    def create(self, source_url: str, source_type: str = "video", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        job, _ = self.create_or_get(source_url, source_type, payload)
        return job

    def create_or_get(
        self,
        source_url: str,
        source_type: str = "video",
        payload: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create a job unless the same source already has an active job.

        Failed jobs are intentionally not deduplicated so a caller can retry
        after fixing a transient worker or source problem.
        """
        if not source_url.startswith(("https://", "http://")):
            raise ValueError("source_url must be an http(s) URL")
        self.requeue_expired()
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        existing = self._conn.execute(
            f"SELECT * FROM jobs WHERE source_url = ? AND status IN ({placeholders}) ORDER BY created_at LIMIT 1",
            (source_url, *ACTIVE_STATUSES),
        ).fetchone()
        if existing is not None:
            return self._row(existing), False  # type: ignore[return-value]
        now = time.time()
        job_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO jobs (id, source_url, source_type, status, payload, created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?, ?)",
            (job_id, source_url, source_type, json.dumps(payload or {}), now, now),
        )
        self._conn.commit()
        return self.get(job_id), True  # type: ignore[return-value]

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._row(self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def list(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if status is not None and status not in STATUSES:
            raise ValueError(f"unknown status: {status}")
        self.requeue_expired()
        query = "SELECT * FROM jobs"
        args: list[Any] = []
        if status:
            query += " WHERE status = ?"
            args.append(status)
        query += " ORDER BY created_at LIMIT ?"
        args.append(min(max(limit, 1), 200))
        return [self._row(row) for row in self._conn.execute(query, args)]  # type: ignore[misc]

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        self.requeue_expired()
        now = time.time()
        lease_until = now + self.lease_seconds
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._conn.execute("SELECT id FROM jobs WHERE status = 'pending' ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            self._conn.commit()
            return None
        self._conn.execute(
            "UPDATE jobs SET status='processing', worker_id=?, lease_until=?, attempts=attempts+1, updated_at=? WHERE id=?",
            (worker_id, lease_until, now, row["id"]),
        )
        self._conn.commit()
        return self.get(row["id"])

    def _update(self, job_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        if not fields:
            result = self.get(job_id)
            if result is None:
                raise KeyError(job_id)
            return result
        fields["updated_at"] = time.time()
        values = []
        assignments = []
        for key, value in fields.items():
            if key in {"draft", "warnings", "payload"}:
                value = json.dumps(value)
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        cursor = self._conn.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?", values)
        if cursor.rowcount != 1:
            raise KeyError(job_id)
        self._conn.commit()
        return self.get(job_id)  # type: ignore[return-value]

    def result(self, job_id: str, worker_id: str, draft: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
        job = self.get(job_id)
        if not job or job["worker_id"] != worker_id or job["status"] != "processing":
            raise ValueError("job is not owned by this worker")
        return self._update(job_id, {"status": "review", "draft": draft, "warnings": warnings, "lease_until": None})

    def fail(self, job_id: str, worker_id: str, error: str) -> dict[str, Any]:
        job = self.get(job_id)
        if not job or job["worker_id"] != worker_id or job["status"] != "processing":
            raise ValueError("job is not owned by this worker")
        return self._update(job_id, {"status": "failed", "error": error[:4000], "lease_until": None})

    def requeue_expired(self) -> int:
        now = time.time()
        cursor = self._conn.execute(
            "UPDATE jobs SET status='pending', worker_id=NULL, lease_until=NULL, updated_at=? WHERE status='processing' AND lease_until < ?",
            (now, now),
        )
        self._conn.commit()
        return cursor.rowcount


def new_token() -> str:
    return secrets.token_urlsafe(32)
