"""Execution loop: runs task steps, handles retries, approvals, and stop signals."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

import security.approvals as _approvals_mod
from agent.planner import plan_task
from agent.task_state import Task, TaskStatus, TaskStep
from storage.repositories import task_repo

log = logging.getLogger(__name__)

ToolExecutor = Callable[[Task, TaskStep], str]
ProgressCallback = Callable[[Task], None]


class ExecutionLoop:
    def __init__(
        self,
        tool_executor: ToolExecutor,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self._executor = tool_executor
        self._progress_cb = progress_callback
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def reset_stop(self) -> None:
        self._stop_event.clear()

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    def run(self, task: Task, config=None) -> Task:
        self._stop_event.clear()
        try:
            return self._run_task(task, config=config)
        except Exception as exc:
            log.exception("Unexpected error in execution loop for task %s", task.id[:8])
            task.error_message = str(exc)
            task.transition(TaskStatus.FAILED)
            task_repo.save(task)
            return task

    def _run_task(self, task: Task, config=None) -> Task:
        if config and getattr(config, "agentic", False):
            return self._run_task_agentic(task, config)

        # ── Planning ─────────────────────────────────────────────────────────
        task.transition(TaskStatus.PLANNING)
        task_repo.save(task)
        self._notify(task)

        task = plan_task(task, config=config)
        task_repo.save(task)

        # ── Pre-execution approval ────────────────────────────────────────────
        if task.requires_approval and not task.approved:
            task.transition(TaskStatus.WAITING_FOR_APPROVAL)
            task_repo.save(task)
            self._notify(task)

            # Use module reference so tests can patch it correctly
            approved = _approvals_mod.request_approval(
                task.id,
                "execute_task",
                f"Approve execution of: {task.objective}",
            )
            if not approved:
                task.transition(TaskStatus.CANCELLED)
                task_repo.save(task)
                return task
            task.approved = True
            task_repo.save(task)

        # ── Step execution — while loop to support retry ──────────────────────
        task.transition(TaskStatus.RUNNING)
        task_repo.save(task)
        self._notify(task)

        settings = _load_settings()
        max_duration = settings.max_task_duration_seconds
        start_time = time.monotonic()

        step_index = task.current_step
        while step_index < len(task.steps):
            if self._stop_event.is_set() or task.cancelled:
                task.transition(TaskStatus.CANCELLED)
                task_repo.save(task)
                return task

            if max_duration and (time.monotonic() - start_time) > max_duration:
                task.error_message = f"Task exceeded maximum duration of {max_duration}s"
                task.transition(TaskStatus.FAILED)
                task_repo.save(task)
                return task

            task.current_step = step_index
            step = task.steps[step_index]
            success = self._run_step(task, step)
            task_repo.save(task)
            self._notify(task)

            if success:
                step_index += 1
                task.retry_count = 0  # reset per-step retry count after success
            else:
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    backoff = min(2 ** task.retry_count, 30)
                    task.add_history(
                        "retry",
                        f"Step {step_index} failed; retry {task.retry_count}/{task.max_retries} in {backoff}s",
                    )
                    task_repo.save(task)
                    time.sleep(backoff)
                    # step_index unchanged — retry same step
                else:
                    task.error_message = step.error
                    task.transition(TaskStatus.FAILED)
                    task_repo.save(task)
                    return task

        # ── Verification ──────────────────────────────────────────────────────
        task.transition(TaskStatus.VERIFYING)
        task_repo.save(task)
        self._notify(task)
        task.add_history("verified", "All steps completed")

        task.result["summary"] = f"Completed {len(task.steps)} steps successfully"
        task.transition(TaskStatus.COMPLETED)
        task_repo.save(task)
        self._notify(task)
        return task

    def _run_task_agentic(self, task: Task, config) -> Task:
        """Agentic loop: Claude generates one step at a time and sees each result."""
        from agent.planner import plan_next_step

        task.transition(TaskStatus.PLANNING)
        task_repo.save(task)
        self._notify(task)

        settings = _load_settings()
        max_duration = settings.max_task_duration_seconds
        start_time = time.monotonic()

        completed: list[dict] = []

        # First step also carries risk/approval metadata
        first = plan_next_step(task.instruction, [], config=config)
        if first is None:
            task.objective = task.instruction
            task.result["summary"] = "Nothing to do"
            task.transition(TaskStatus.COMPLETED)
            task_repo.save(task)
            return task

        task.objective = task.instruction
        task.risk_level = first.get("risk_level", "low")
        task.requires_approval = first.get("requires_approval", False)
        task_repo.save(task)

        # Pre-execution approval gate
        if task.requires_approval and not task.approved:
            task.transition(TaskStatus.WAITING_FOR_APPROVAL)
            task_repo.save(task)
            self._notify(task)
            approved = _approvals_mod.request_approval(
                task.id, "execute_task", f"Approve: {task.instruction}"
            )
            if not approved:
                task.transition(TaskStatus.CANCELLED)
                task_repo.save(task)
                return task
            task.approved = True
            task_repo.save(task)

        task.transition(TaskStatus.RUNNING)
        task_repo.save(task)
        self._notify(task)

        next_step_data = first
        step_index = 0
        _MAX_STEPS = 20
        _last_tool = None
        _same_tool_streak = 0
        _tool_history: list[str] = []  # last N tools for oscillation detection

        while next_step_data is not None and step_index < _MAX_STEPS:
            if self._stop_event.is_set() or task.cancelled:
                task.transition(TaskStatus.CANCELLED)
                task_repo.save(task)
                return task

            if max_duration and (time.monotonic() - start_time) > max_duration:
                task.error_message = f"Task exceeded max duration {max_duration}s"
                task.transition(TaskStatus.FAILED)
                task_repo.save(task)
                return task

            # Thrash protection: detect both consecutive repeats and A-B-A-B oscillation
            current_tool = next_step_data["tool"]
            if current_tool == _last_tool:
                _same_tool_streak += 1
            else:
                _same_tool_streak = 1
                _last_tool = current_tool
            _tool_history.append(current_tool)
            if len(_tool_history) > 8:
                _tool_history.pop(0)

            # Tools that are "observation only" — no forward progress on their own
            _OBS_TOOLS = {"screen_read", "find_and_focus"}

            _thrash = False
            # 1. Same tool called 3+ times in a row
            if _same_tool_streak >= 3:
                _thrash = True
            # 2. A-B-A-B-A-B oscillation between exactly two tools
            elif len(_tool_history) >= 6:
                last6 = _tool_history[-6:]
                if (last6[0] == last6[2] == last6[4] and last6[1] == last6[3] == last6[5]
                        and last6[0] != last6[1]):
                    _thrash = True
            # 3. Last 5 steps were only observation tools — no real action taken
            elif len(_tool_history) >= 5:
                if all(t in _OBS_TOOLS for t in _tool_history[-5:]):
                    _thrash = True

            if _thrash:
                log.warning(
                    "Agentic loop: thrash detected (tool history=%s) — stopping",
                    _tool_history[-6:],
                )
                break

            step = TaskStep(
                index=step_index,
                description=next_step_data["description"],
                tool=next_step_data["tool"],
                parameters=next_step_data["parameters"],
            )
            task.steps.append(step)
            task.current_step = step_index
            task_repo.save(task)

            success = self._run_step(task, step)
            task_repo.save(task)
            self._notify(task)

            completed.append({
                "description": step.description,
                "tool": step.tool,
                "result": step.result if success else step.error,
            })

            if not success:
                task.error_message = step.error
                task.transition(TaskStatus.FAILED)
                task_repo.save(task)
                return task

            step_index += 1
            next_step_data = plan_next_step(task.instruction, completed, config=config)

        task.add_history("verified", f"Agentic loop completed {step_index} steps")
        task.result["summary"] = f"Completed {step_index} steps"
        task.transition(TaskStatus.COMPLETED)
        task_repo.save(task)
        self._notify(task)
        return task

    def _run_step(self, task: Task, step: TaskStep) -> bool:
        step.status = "running"
        step.started_at = datetime.now(timezone.utc).isoformat()
        from security.audit_log import record as audit
        audit(step.tool, step.description, task_id=task.id, risk_level=task.risk_level)

        try:
            result = self._executor(task, step)
            step.result = result
            step.status = "completed"
            step.completed_at = datetime.now(timezone.utc).isoformat()
            task.add_history("step_done", f"Step {step.index}: {step.description[:80]}")
            return True
        except Exception as exc:
            step.error = str(exc)
            step.status = "failed"
            step.completed_at = datetime.now(timezone.utc).isoformat()
            task.add_history("step_failed", f"Step {step.index}: {str(exc)[:200]}")
            log.error("Step %d failed for task %s: %s", step.index, task.id[:8], exc)
            return False

    def _notify(self, task: Task) -> None:
        if self._progress_cb:
            try:
                self._progress_cb(task)
            except Exception:
                pass


def _load_settings():
    from config.settings import get_settings
    return get_settings()
