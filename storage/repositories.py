"""Data-access layer for tasks, preferences, proposals, and audit entries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agent.task_state import Task, TaskStatus
from storage.database import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Task repository ──────────────────────────────────────────────────────────

class TaskRepository:
    def save(self, task: Task) -> None:
        row = task.to_db_row()
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO tasks (
                id, instruction, objective, status, risk_level,
                steps_json, current_step, history_json, result_json,
                retry_count, max_retries, idempotency_key,
                requires_approval, approved, cancelled,
                created_at, updated_at, completed_at, error_message, metadata_json
            ) VALUES (
                :id, :instruction, :objective, :status, :risk_level,
                :steps_json, :current_step, :history_json, :result_json,
                :retry_count, :max_retries, :idempotency_key,
                :requires_approval, :approved, :cancelled,
                :created_at, :updated_at, :completed_at, :error_message, :metadata_json
            )
            ON CONFLICT(id) DO UPDATE SET
                instruction=excluded.instruction,
                objective=excluded.objective,
                status=excluded.status,
                risk_level=excluded.risk_level,
                steps_json=excluded.steps_json,
                current_step=excluded.current_step,
                history_json=excluded.history_json,
                result_json=excluded.result_json,
                retry_count=excluded.retry_count,
                max_retries=excluded.max_retries,
                requires_approval=excluded.requires_approval,
                approved=excluded.approved,
                cancelled=excluded.cancelled,
                updated_at=excluded.updated_at,
                completed_at=excluded.completed_at,
                error_message=excluded.error_message,
                metadata_json=excluded.metadata_json
            """,
            row,
        )
        conn.commit()

    def get(self, task_id: str) -> Task | None:
        conn = get_connection()
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return Task.from_db_row(dict(row)) if row else None

    def get_by_idempotency_key(self, key: str) -> Task | None:
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM tasks WHERE idempotency_key=?", (key,)
        ).fetchone()
        return Task.from_db_row(dict(row)) if row else None

    def list_active(self) -> list[Task]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status NOT IN ('completed','failed','cancelled') ORDER BY created_at"
        ).fetchall()
        return [Task.from_db_row(dict(r)) for r in rows]

    def list_recent(self, limit: int = 50) -> list[Task]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Task.from_db_row(dict(r)) for r in rows]

    def list_by_status(self, status: TaskStatus) -> list[Task]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status=? ORDER BY created_at", (status.value,)
        ).fetchall()
        return [Task.from_db_row(dict(r)) for r in rows]

    def delete(self, task_id: str) -> None:
        conn = get_connection()
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()


# ── Preferences repository ───────────────────────────────────────────────────

class PreferencesRepository:
    def set(self, key: str, value: Any) -> None:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO user_preferences (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
            """,
            (key, json.dumps(value), _now()),
        )
        conn.commit()

    def get(self, key: str, default: Any = None) -> Any:
        conn = get_connection()
        row = conn.execute(
            "SELECT value_json FROM user_preferences WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row["value_json"]) if row else default

    def all(self) -> dict[str, Any]:
        conn = get_connection()
        rows = conn.execute("SELECT key, value_json FROM user_preferences").fetchall()
        return {r["key"]: json.loads(r["value_json"]) for r in rows}

    def delete(self, key: str) -> None:
        conn = get_connection()
        conn.execute("DELETE FROM user_preferences WHERE key=?", (key,))
        conn.commit()


# ── Proposal repository ──────────────────────────────────────────────────────

class ProposalRepository:
    def save(self, job_url: str, job_title: str, platform: str,
             proposal_text: str, status: str = "drafted") -> None:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO proposal_history (job_url, job_title, platform, status, proposal_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_url) DO UPDATE SET
                status=excluded.status,
                proposal_text=excluded.proposal_text
            """,
            (job_url, job_title, platform, status, proposal_text, _now()),
        )
        conn.commit()

    def already_applied(self, job_url: str) -> bool:
        conn = get_connection()
        row = conn.execute(
            "SELECT 1 FROM proposal_history WHERE job_url=?", (job_url,)
        ).fetchone()
        return row is not None

    def mark_submitted(self, job_url: str) -> None:
        conn = get_connection()
        conn.execute(
            "UPDATE proposal_history SET status='submitted', submitted_at=? WHERE job_url=?",
            (_now(), job_url),
        )
        conn.commit()

    def list_recent(self, limit: int = 20) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM proposal_history ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


task_repo = TaskRepository()
pref_repo = PreferencesRepository()
proposal_repo = ProposalRepository()
