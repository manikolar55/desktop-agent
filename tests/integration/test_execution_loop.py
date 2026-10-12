"""
Integration tests for the execution loop.

Uses a mock tool executor to verify:
- Successful step execution advances state
- Failed steps trigger retry with backoff
- Retry limit stops execution and marks task FAILED
- Emergency stop interrupts the loop
- Approval gate blocks and can be denied
"""

import threading
import time
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "loop_test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import storage.database as db_mod
    db_mod._local = threading.local()
    import importlib
    importlib.reload(db_mod)
    db_mod.init_db()
    import storage.repositories as repo_mod
    importlib.reload(repo_mod)
    yield db_file


def _make_task(instruction="test", risk="low", steps=None, max_retries=2):
    from agent.task_state import Task, TaskStep
    t = Task(instruction=instruction, risk_level=risk, max_retries=max_retries)
    if steps:
        t.steps = steps
    return t


def _simple_executor(task, step):
    return f"step {step.index} done"


def _failing_executor(task, step):
    raise RuntimeError("tool failure")


class TestExecutionLoopSuccess:
    def test_all_steps_complete(self, db):
        from agent.execution_loop import ExecutionLoop
        from agent.task_state import TaskStep, TaskStatus

        steps = [TaskStep(index=i, description=f"step {i}", tool="no_op") for i in range(3)]
        task = _make_task(steps=steps)
        # Pre-plan so loop skips planning
        task.steps = steps

        loop = ExecutionLoop(tool_executor=_simple_executor)
        # Override planning by directly seeding steps
        import unittest.mock as mock
        with mock.patch("agent.execution_loop.plan_task", side_effect=lambda t, config=None: t):
            result = loop.run(task)

        assert result.status == TaskStatus.COMPLETED
        assert result.progress_pct() == 100

    def test_history_records_each_step(self, db):
        from agent.execution_loop import ExecutionLoop
        from agent.task_state import TaskStep
        import unittest.mock as mock

        steps = [TaskStep(index=i, description=f"step {i}", tool="no_op") for i in range(2)]
        task = _make_task(steps=steps)

        loop = ExecutionLoop(tool_executor=_simple_executor)
        with mock.patch("agent.execution_loop.plan_task", side_effect=lambda t, config=None: t):
            result = loop.run(task)

        step_done_events = [h for h in result.history if h.event == "step_done"]
        assert len(step_done_events) == 2


class TestRetryBehaviour:
    def test_failing_step_retried_and_fails(self, db):
        from agent.execution_loop import ExecutionLoop
        from agent.task_state import TaskStep, TaskStatus
        import unittest.mock as mock

        steps = [TaskStep(index=0, description="will fail", tool="no_op")]
        task = _make_task(steps=steps, max_retries=2)
        task.max_retries = 2

        call_count = [0]

        def _executor(t, s):
            call_count[0] += 1
            raise RuntimeError("always fails")

        loop = ExecutionLoop(tool_executor=_executor)
        with mock.patch("agent.execution_loop.plan_task", side_effect=lambda t, config=None: t):
            with mock.patch("time.sleep"):  # skip backoff delays in tests
                result = loop.run(task)

        assert result.status == TaskStatus.FAILED
        assert result.error_message is not None
        # Initial attempt + max_retries retries
        assert call_count[0] == task.max_retries + 1

    def test_retry_count_increments(self, db):
        from agent.execution_loop import ExecutionLoop
        from agent.task_state import TaskStep, TaskStatus
        import unittest.mock as mock

        steps = [TaskStep(index=0, description="fail", tool="no_op")]
        task = _make_task(steps=steps, max_retries=1)

        loop = ExecutionLoop(tool_executor=_failing_executor)
        with mock.patch("agent.execution_loop.plan_task", side_effect=lambda t, config=None: t):
            with mock.patch("time.sleep"):
                result = loop.run(task)

        assert result.retry_count > 0


class TestEmergencyStop:
    def test_stop_cancels_running_task(self, db):
        from agent.execution_loop import ExecutionLoop
        from agent.task_state import TaskStep, TaskStatus
        import unittest.mock as mock

        barrier = threading.Event()
        stop_called = threading.Event()

        def _slow_executor(task, step):
            barrier.set()
            time.sleep(0.5)
            return "done"

        steps = [TaskStep(index=i, description="slow", tool="no_op") for i in range(5)]
        task = _make_task(steps=steps)
        loop = ExecutionLoop(tool_executor=_slow_executor)

        def _stopper():
            barrier.wait(timeout=2)
            loop.stop()

        t = threading.Thread(target=_stopper, daemon=True)
        t.start()

        with mock.patch("agent.execution_loop.plan_task", side_effect=lambda t, config=None: t):
            result = loop.run(task)

        assert result.status == TaskStatus.CANCELLED


class TestApprovalGate:
    def test_task_cancelled_when_approval_denied(self, db):
        from agent.execution_loop import ExecutionLoop
        from agent.task_state import TaskStep, TaskStatus
        import agent.execution_loop as loop_mod
        import unittest.mock as mock

        steps = [TaskStep(index=0, description="needs approval", tool="no_op")]
        task = _make_task(steps=steps, risk="high")
        task.requires_approval = True

        loop = ExecutionLoop(tool_executor=_simple_executor)
        with mock.patch("agent.execution_loop.plan_task", side_effect=lambda t, config=None: t):
            with mock.patch.object(loop_mod._approvals_mod, "request_approval", return_value=False):
                result = loop.run(task)

        assert result.status == TaskStatus.CANCELLED

    def test_task_runs_when_approval_granted(self, db):
        from agent.execution_loop import ExecutionLoop
        from agent.task_state import TaskStep, TaskStatus
        import agent.execution_loop as loop_mod
        import unittest.mock as mock

        steps = [TaskStep(index=0, description="needs approval", tool="no_op")]
        task = _make_task(steps=steps, risk="high")
        task.requires_approval = True

        loop = ExecutionLoop(tool_executor=_simple_executor)
        with mock.patch("agent.execution_loop.plan_task", side_effect=lambda t, config=None: t):
            with mock.patch.object(loop_mod._approvals_mod, "request_approval", return_value=True):
                result = loop.run(task)

        assert result.status == TaskStatus.COMPLETED
