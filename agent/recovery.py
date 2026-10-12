"""Task recovery — safe restart handling for incomplete tasks."""

from __future__ import annotations

import logging

from agent.task_state import Task, TaskStatus
from storage.repositories import task_repo

log = logging.getLogger(__name__)


def recover_interrupted_tasks() -> list[Task]:
    """
    Called at startup. Returns tasks that were running when the app last shut down.
    Resets them to QUEUED at their last safe step so they can be retried.
    Consequential steps (high-risk) are NOT automatically re-executed — they remain
    at the step before the risky one with a note requiring user review.
    """
    candidates = task_repo.list_active()
    recovered = []

    for task in candidates:
        if task.status == TaskStatus.RUNNING:
            _handle_interrupted_running(task)
            recovered.append(task)
        elif task.status == TaskStatus.PLANNING:
            task.transition(TaskStatus.QUEUED)
            task.add_history("recovered", "Re-queued for planning after restart")
            task_repo.save(task)
            recovered.append(task)

    if recovered:
        log.info("Recovery: %d tasks restored from previous session", len(recovered))
    return recovered


def _handle_interrupted_running(task: Task) -> None:
    step = task.current_step_obj()
    if step is None:
        task.transition(TaskStatus.QUEUED)
        task.add_history("recovered", "No active step; re-queued")
        task_repo.save(task)
        return

    if task.risk_level == "high" or step.tool in (
        "shell_run", "file_write", "google_chat_reply", "upwork_propose", "code_task"
    ):
        task.add_history(
            "recovery_paused",
            f"Was executing high-risk step '{step.tool}' — manual review required before retry",
        )
        task.status = TaskStatus.WAITING_FOR_INPUT
        task.error_message = (
            f"App restarted while executing step {step.index} ({step.tool}). "
            f"Review and resubmit if appropriate."
        )
        task_repo.save(task)
    else:
        # Safe to retry from previous step
        task.current_step = max(0, task.current_step - 1)
        task.transition(TaskStatus.QUEUED)
        task.add_history("recovered", f"Re-queued at step {task.current_step}")
        task_repo.save(task)
