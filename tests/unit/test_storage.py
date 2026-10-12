"""Tests for database initialisation and repositories."""

import pytest
import threading


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_storage.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import storage.database as db_mod
    db_mod._local = threading.local()
    import importlib
    importlib.reload(db_mod)
    db_mod.init_db()
    yield db_file


class TestDatabase:
    def test_init_creates_tables(self, fresh_db):
        import storage.database as db_mod
        conn = db_mod.get_connection()
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "tasks" in tables
        assert "audit_log" in tables
        assert "user_preferences" in tables
        assert "approvals" in tables
        assert "proposal_history" in tables


class TestPreferencesRepository:
    def test_set_and_get(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        repo = repo_mod.PreferencesRepository()
        repo.set("key1", {"nested": True})
        val = repo.get("key1")
        assert val == {"nested": True}

    def test_missing_key_returns_default(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        repo = repo_mod.PreferencesRepository()
        assert repo.get("nonexistent", "fallback") == "fallback"

    def test_overwrite(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        repo = repo_mod.PreferencesRepository()
        repo.set("x", 1)
        repo.set("x", 2)
        assert repo.get("x") == 2

    def test_delete(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        repo = repo_mod.PreferencesRepository()
        repo.set("to_delete", "value")
        repo.delete("to_delete")
        assert repo.get("to_delete") is None


class TestTaskRepository:
    def test_save_and_get(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        from agent.task_state import Task, TaskStatus
        repo = repo_mod.TaskRepository()
        task = Task(instruction="test task")
        repo.save(task)
        fetched = repo.get(task.id)
        assert fetched is not None
        assert fetched.instruction == "test task"
        assert fetched.status == TaskStatus.QUEUED

    def test_update_via_save(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        from agent.task_state import Task, TaskStatus
        repo = repo_mod.TaskRepository()
        task = Task(instruction="update test")
        repo.save(task)
        task.transition(TaskStatus.COMPLETED)
        repo.save(task)
        fetched = repo.get(task.id)
        assert fetched.status == TaskStatus.COMPLETED

    def test_list_active_excludes_terminal(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        from agent.task_state import Task, TaskStatus
        repo = repo_mod.TaskRepository()
        active = Task(instruction="active")
        done = Task(instruction="done")
        done.transition(TaskStatus.COMPLETED)
        repo.save(active)
        repo.save(done)
        active_list = repo.list_active()
        ids = [t.id for t in active_list]
        assert active.id in ids
        assert done.id not in ids
