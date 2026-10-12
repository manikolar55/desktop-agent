"""SQLite database initialisation and connection management."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from config.settings import get_settings

_local = threading.local()

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    instruction     TEXT NOT NULL,
    objective       TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'queued',
    risk_level      TEXT NOT NULL DEFAULT 'low',
    steps_json      TEXT NOT NULL DEFAULT '[]',
    current_step    INTEGER NOT NULL DEFAULT 0,
    history_json    TEXT NOT NULL DEFAULT '[]',
    result_json     TEXT NOT NULL DEFAULT '{}',
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    idempotency_key TEXT,
    requires_approval INTEGER NOT NULL DEFAULT 0,
    approved        INTEGER NOT NULL DEFAULT 0,
    cancelled       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT,
    error_message   TEXT,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency ON tasks(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    task_id     TEXT,
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT 'agent',
    details     TEXT NOT NULL DEFAULT '',
    risk_level  TEXT NOT NULL DEFAULT 'low',
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log(task_id);

CREATE TABLE IF NOT EXISTS approvals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    action      TEXT NOT NULL,
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT NOT NULL,
    decided_at  TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_preferences (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposal_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url         TEXT NOT NULL UNIQUE,
    job_title       TEXT NOT NULL,
    platform        TEXT NOT NULL DEFAULT 'upwork',
    status          TEXT NOT NULL DEFAULT 'drafted',
    proposal_text   TEXT NOT NULL DEFAULT '',
    submitted_at    TEXT,
    created_at      TEXT NOT NULL
);
"""


def _get_db_path() -> Path:
    return get_settings().db_path


def get_connection() -> sqlite3.Connection:
    """Return a per-thread SQLite connection, initialising schema on first use."""
    if not hasattr(_local, "conn") or _local.conn is None:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        _local.conn = conn
    return _local.conn


def close_connection() -> None:
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None


def init_db() -> None:
    """Ensure schema exists. Call once at application startup."""
    get_connection()
