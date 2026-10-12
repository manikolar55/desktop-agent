"""Tests for task state model and state machine."""

import pytest
from agent.task_state import Task, TaskStatus, TaskStep, TERMINAL_STATUSES, CANCELLABLE_STATUSES


def make_task(instruction="do something") -> Task:
    return Task(instruction=instruction)


class TestTaskCreation:
    def test_default_status_is_queued(self):
        t = make_task()
        assert t.status == TaskStatus.QUEUED

    def test_has_unique_id(self):
        t1, t2 = make_task(), make_task()
        assert t1.id != t2.id

    def test_history_starts_empty(self):
        assert make_task().history == []


class TestStateTransitions:
    def test_queued_to_planning(self):
        t = make_task()
        t.transition(TaskStatus.PLANNING)
        assert t.status == TaskStatus.PLANNING
        assert len(t.history) == 1

    def test_terminal_statuses(self):
        for s in TERMINAL_STATUSES:
            t = make_task()
            t.transition(s)
            assert t.is_terminal()
            assert t.completed_at is not None

    def test_cancellable_statuses(self):
        for s in CANCELLABLE_STATUSES:
            t = make_task()
            t.status = s
            assert t.can_cancel()

    def test_completed_is_not_cancellable(self):
        t = make_task()
        t.transition(TaskStatus.COMPLETED)
        assert not t.can_cancel()

    def test_cancel_sets_flag_and_status(self):
        t = make_task()
        t.cancel()
        assert t.cancelled is True
        assert t.status == TaskStatus.CANCELLED

    def test_cancel_on_completed_does_nothing(self):
        t = make_task()
        t.transition(TaskStatus.COMPLETED)
        t.cancel()
        assert t.status == TaskStatus.COMPLETED


class TestProgress:
    def test_no_steps_gives_zero_percent(self):
        assert make_task().progress_pct() == 0

    def test_half_steps_gives_fifty_percent(self):
        t = make_task()
        t.steps = [
            TaskStep(index=0, description="a", status="completed"),
            TaskStep(index=1, description="b", status="pending"),
        ]
        assert t.progress_pct() == 50

    def test_all_steps_gives_hundred_percent(self):
        t = make_task()
        t.steps = [TaskStep(index=i, description="x", status="completed") for i in range(4)]
        assert t.progress_pct() == 100


class TestSerialization:
    def test_round_trip(self):
        t = make_task("round trip test")
        t.transition(TaskStatus.RUNNING)
        t.steps = [TaskStep(index=0, description="step A")]
        row = t.to_db_row()
        restored = Task.from_db_row(row)
        assert restored.id == t.id
        assert restored.status == TaskStatus.RUNNING
        assert len(restored.steps) == 1
        assert restored.steps[0].description == "step A"
