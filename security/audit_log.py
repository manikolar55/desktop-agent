"""Append-only audit log stored in SQLite."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from security.secrets import redact
from storage.database import get_connection

log = logging.getLogger(__name__)


def record(
    action: str,
    details: str = "",
    task_id: str | None = None,
    risk_level: str = "low",
    actor: str = "agent",
) -> None:
    safe_details = redact(details)
    ts = datetime.now(timezone.utc).isoformat()
    try:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO audit_log (timestamp, task_id, action, actor, details, risk_level)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ts, task_id, action, actor, safe_details, risk_level),
        )
        conn.commit()
    except Exception as exc:
        log.error("Audit log write failed: %s", exc)

    log.info("[AUDIT] %s | %s | %s | %s", risk_level.upper(), action, actor, safe_details[:200])


def recent_entries(limit: int = 100) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
