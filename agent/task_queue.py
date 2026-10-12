"""Thread-safe in-memory task queue backed by SQLite persistence."""

from __future__ import annotations

import logging
import threading
from collections import deque

from agent.task_state import Task, TaskStatus, TERMINAL_STATUSES
from storage.repositories import task_repo

log = logging.getLogger(__name__)


class TaskQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: deque[Task] = deque()
        self._active: Task | None = None

    def enqueue(self, task: Task) -> Task:
        if task.idempotency_key:
            existing = task_repo.get_by_idempotency_key(task.idempotency_key)
            if existing and existing.status not in TERMINAL_STATUSES:
                log.info("Duplicate task blocked by idempotency key %s", task.idempotency_key)
                return existing
        task_repo.save(task)
        with self._lock:
            self._queue.append(task)
        log.info("Task enqueued: %s [%s]", task.id[:8], task.instruction[:60])
        return task

    def next(self) -> Task | None:
        with self._lock:
            if self._queue:
                self._active = self._queue.popleft()
                return self._active
        return None

    def cancel_active(self) -> bool:
        with self._lock:
            if self._active and self._active.can_cancel():
                self._active.cancel()
                task_repo.save(self._active)
                log.info("Active task cancelled: %s", self._active.id[:8])
                return True
        return False

    def cancel_all(self) -> int:
        count = 0
        with self._lock:
            if self._active and self._active.can_cancel():
                self._active.cancel()
                task_repo.save(self._active)
                count += 1
            for task in list(self._queue):
                if task.can_cancel():
                    task.cancel()
                    task_repo.save(task)
                    count += 1
            self._queue.clear()
        log.info("Emergency stop: cancelled %d tasks", count)
        return count

    def active_task(self) -> Task | None:
        with self._lock:
            return self._active

    def queued_tasks(self) -> list[Task]:
        with self._lock:
            return list(self._queue)

    def restore_from_db(self) -> int:
        """On startup, reload tasks that were running or queued when the app last closed."""
        tasks = task_repo.list_active()
        count = 0
        for task in tasks:
            if task.status in (TaskStatus.QUEUED, TaskStatus.PLANNING):
                with self._lock:
                    self._queue.append(task)
                count += 1
            elif task.status == TaskStatus.RUNNING:
                # Mark interrupted tasks as failed rather than re-running them —
                # they may have already produced side-effects mid-execution.
                task.add_history("recovered", "App restarted while task was running — marked failed")
                task.status = TaskStatus.FAILED
                task.error_message = "Interrupted by app restart"
                task_repo.save(task)
                count += 1
        log.info("Restored %d tasks from previous session", count)
        return count

    def size(self) -> int:
        with self._lock:
            return len(self._queue)
