"""Approval request and decision tracking."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable

from storage.database import get_connection

ApprovalCallback = Callable[[str, str, str], bool]

_approval_callback: ApprovalCallback | None = None
_lock = threading.Lock()


def set_approval_callback(cb: ApprovalCallback) -> None:
    global _approval_callback
    with _lock:
        _approval_callback = cb


def request_approval(task_id: str, action: str, description: str) -> bool:
    """
    Persist an approval request and invoke the UI callback.
    Returns True if approved, False if denied or no callback set.
    The callback is responsible for blocking until the user decides.
    """
    ts = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO approvals (task_id, action, description, status, requested_at) VALUES (?,?,?,?,?)",
        (task_id, action, description, "pending", ts),
    )
    approval_id = cur.lastrowid
    conn.commit()

    with _lock:
        cb = _approval_callback

    if cb is None:
        _record_decision(approval_id, "denied")
        return False

    approved = cb(task_id, action, description)
    _record_decision(approval_id, "approved" if approved else "denied")
    return approved


def _record_decision(approval_id: int, status: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE approvals SET status=?, decided_at=? WHERE id=?",
        (status, datetime.now(timezone.utc).isoformat(), approval_id),
    )
    conn.commit()


def pending_approvals() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM approvals WHERE status='pending' ORDER BY requested_at"
    ).fetchall()
    return [dict(r) for r in rows]
