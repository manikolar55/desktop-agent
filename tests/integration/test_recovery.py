"""
Integration tests for task restart recovery.

Verifies that:
- Tasks interrupted mid-run are safely re-queued
- High-risk steps are NOT auto-retried on restart
- Low-risk interrupted tasks rewind one step and re-queue
- Tasks in terminal states are not touched
"""

import pytest
import threading


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "recovery_test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import storage.database as db_mod
    db_mod._local = threading.local()
    import importlib
    importlib.reload(db_mod)
    db_mod.init_db()
    import storage.repositories as repo_mod
    importlib.reload(repo_mod)
    yield db_file


class TestRestartRecovery:
    def test_running_low_risk_task_requeued_at_previous_step(self, db):
        import importlib, storage.repositories as repo_mod
        importlib.reload(repo_mod)
        from agent.task_state import Task, TaskStatus, TaskStep
        from agent.recovery import recover_interrupted_tasks

        task = Task(instruction="low risk running task", risk_level="low")
        task.steps = [
            TaskStep(index=0, description="safe step A", tool="file_read", status="completed"),
            TaskStep(index=1, description="safe step B", tool="file_read", status="running"),
        ]
        task.current_step = 1
        task.status = TaskStatus.RUNNING
        repo_mod.task_repo.save(task)

        recovered = recover_interrupted_tasks()
        assert len(recovered) == 1
        fetched = repo_mod.task_repo.get(task.id)
        assert fetched.status == TaskStatus.QUEUED
        assert fetched.current_step == 0  # rewound one step

    def test_running_high_risk_task_paused_not_retried(self, db):
        import importlib, storage.repositories as repo_mod
        importlib.reload(repo_mod)
        from agent.task_state import Task, TaskStatus, TaskStep
        from agent.recovery import recover_interrupted_tasks

        task = Task(instruction="high risk task", risk_level="high")
        task.steps = [
            TaskStep(index=0, description="dangerous step", tool="shell_run", status="running"),
        ]
        task.current_step = 0
        task.status = TaskStatus.RUNNING
        repo_mod.task_repo.save(task)

        recovered = recover_interrupted_tasks()
        assert len(recovered) == 1
        fetched = repo_mod.task_repo.get(task.id)
        # Must NOT be re-queued — must require manual review
        assert fetched.status == TaskStatus.WAITING_FOR_INPUT
        assert fetched.error_message is not None

    def test_planning_task_requeued(self, db):
        import importlib, storage.repositories as repo_mod
        importlib.reload(repo_mod)
        from agent.task_state import Task, TaskStatus
        from agent.recovery import recover_interrupted_tasks

        task = Task(instruction="planning task")
        task.status = TaskStatus.PLANNING
        repo_mod.task_repo.save(task)

        recovered = recover_interrupted_tasks()
        assert any(r.id == task.id for r in recovered)
        fetched = repo_mod.task_repo.get(task.id)
        assert fetched.status == TaskStatus.QUEUED

    def test_completed_task_not_touched(self, db):
        import importlib, storage.repositories as repo_mod
        importlib.reload(repo_mod)
        from agent.task_state import Task, TaskStatus
        from agent.recovery import recover_interrupted_tasks

        task = Task(instruction="done task")
        task.transition(TaskStatus.COMPLETED)
        repo_mod.task_repo.save(task)

        recovered = recover_interrupted_tasks()
        assert not any(r.id == task.id for r in recovered)
        fetched = repo_mod.task_repo.get(task.id)
        assert fetched.status == TaskStatus.COMPLETED

    def test_cancelled_task_not_touched(self, db):
        import importlib, storage.repositories as repo_mod
        importlib.reload(repo_mod)
        from agent.task_state import Task, TaskStatus
        from agent.recovery import recover_interrupted_tasks

        task = Task(instruction="cancelled task")
        task.cancel()
        repo_mod.task_repo.save(task)

        recovered = recover_interrupted_tasks()
        assert not any(r.id == task.id for r in recovered)
