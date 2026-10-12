"""Tests for task queue — persistence, idempotency, cancel-all."""

import os
import tempfile
import pytest

# Use a temp DB for tests
os.environ.setdefault("DB_PATH", ":memory:")


def _fresh_queue():
    from agent.task_queue import TaskQueue
    return TaskQueue()


def _task(instruction="test task", key=None):
    from agent.task_state import Task
    return Task(instruction=instruction, idempotency_key=key)


class TestEnqueue:
    def test_enqueue_returns_task(self, tmp_db):
        q = _fresh_queue()
        t = q.enqueue(_task())
        assert t.id is not None

    def test_idempotency_blocks_duplicate(self, tmp_db):
        q = _fresh_queue()
        t1 = q.enqueue(_task(key="k1"))
        t2 = q.enqueue(_task(key="k1"))
        assert t1.id == t2.id
        assert q.size() == 1

    def test_different_keys_both_enqueued(self, tmp_db):
        q = _fresh_queue()
        q.enqueue(_task(key="a"))
        q.enqueue(_task(key="b"))
        assert q.size() == 2


class TestNext:
    def test_next_returns_fifo(self, tmp_db):
        q = _fresh_queue()
        t1 = q.enqueue(_task("first"))
        t2 = q.enqueue(_task("second"))
        assert q.next().instruction == "first"
        assert q.next().instruction == "second"

    def test_next_on_empty_returns_none(self, tmp_db):
        q = _fresh_queue()
        assert q.next() is None


class TestCancelAll:
    def test_cancel_all_clears_queue(self, tmp_db):
        q = _fresh_queue()
        for _ in range(3):
            q.enqueue(_task())
        cancelled = q.cancel_all()
        assert cancelled >= 3
        assert q.size() == 0


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import importlib
    import storage.database as db_mod
    import storage.repositories as repo_mod
    import threading
    db_mod._local = threading.local()
    importlib.reload(db_mod)
    importlib.reload(repo_mod)
    db_mod.init_db()
    yield db_file
