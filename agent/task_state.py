"""Task data model and state machine."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_INPUT = "waiting_for_input"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
CANCELLABLE_STATUSES = {
    TaskStatus.QUEUED,
    TaskStatus.PLANNING,
    TaskStatus.RUNNING,
    TaskStatus.WAITING_FOR_APPROVAL,
    TaskStatus.WAITING_FOR_INPUT,
    TaskStatus.VERIFYING,
}


class TaskStep(BaseModel):
    index: int
    description: str
    tool: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    result: Any = None
    error: str = ""
    started_at: str = ""
    completed_at: str = ""


class HistoryEntry(BaseModel):
    timestamp: str
    event: str
    details: str = ""


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    instruction: str
    objective: str = ""
    status: TaskStatus = TaskStatus.QUEUED
    risk_level: str = "low"
    steps: list[TaskStep] = Field(default_factory=list)
    current_step: int = 0
    history: list[HistoryEntry] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 3
    idempotency_key: str | None = None
    requires_approval: bool = False
    approved: bool = False
    cancelled: bool = False
    created_at: str = Field(default_factory=lambda: _now())
    updated_at: str = Field(default_factory=lambda: _now())
    completed_at: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_history(self, event: str, details: str = "") -> None:
        self.history.append(HistoryEntry(timestamp=_now(), event=event, details=details))
        self.updated_at = _now()

    def transition(self, new_status: TaskStatus) -> None:
        self.add_history("status_change", f"{self.status} → {new_status}")
        self.status = new_status
        self.updated_at = _now()
        if new_status in TERMINAL_STATUSES:
            self.completed_at = _now()

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def can_cancel(self) -> bool:
        return self.status in CANCELLABLE_STATUSES

    def cancel(self) -> None:
        if self.can_cancel():
            self.cancelled = True
            self.transition(TaskStatus.CANCELLED)

    def current_step_obj(self) -> TaskStep | None:
        if 0 <= self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None

    def progress_pct(self) -> int:
        if not self.steps:
            return 0
        done = sum(1 for s in self.steps if s.status == "completed")
        return int(done / len(self.steps) * 100)

    # ── Serialisation helpers for SQLite ────────────────────────────────────

    def to_db_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "instruction": self.instruction,
            "objective": self.objective,
            "status": self.status.value,
            "risk_level": self.risk_level,
            "steps_json": json.dumps([s.model_dump() for s in self.steps]),
            "current_step": self.current_step,
            "history_json": json.dumps([h.model_dump() for h in self.history]),
            "result_json": json.dumps(self.result),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "idempotency_key": self.idempotency_key,
            "requires_approval": int(self.requires_approval),
            "approved": int(self.approved),
            "cancelled": int(self.cancelled),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
            "metadata_json": json.dumps(self.metadata),
        }

    @classmethod
    def from_db_row(cls, row: dict) -> "Task":
        return cls(
            id=row["id"],
            instruction=row["instruction"],
            objective=row["objective"],
            status=TaskStatus(row["status"]),
            risk_level=row["risk_level"],
            steps=[TaskStep(**s) for s in json.loads(row["steps_json"])],
            current_step=row["current_step"],
            history=[HistoryEntry(**h) for h in json.loads(row["history_json"])],
            result=json.loads(row["result_json"]),
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            idempotency_key=row["idempotency_key"],
            requires_approval=bool(row["requires_approval"]),
            approved=bool(row["approved"]),
            cancelled=bool(row["cancelled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            error_message=row["error_message"],
            metadata=json.loads(row["metadata_json"]),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
