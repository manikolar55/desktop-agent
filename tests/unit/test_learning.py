import types

import pytest

from agent import feedback, learning


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(learning, "_PATH", tmp_path / "learned.json")


STEPS = [
    {"tool": "find_and_focus", "description": "focus chrome", "parameters": {"title": "Chrome"}},
    {"tool": "screen_hotkey", "description": "address bar", "parameters": {"keys": "ctrl+l"}},
]


def test_vocab_seed_and_teach():
    assert learning.apply_vocab("open piecham now") == "open PyCharm now"
    learning.teach_vocab("jarvish", "Jarvis")
    assert learning.apply_vocab("hey Jarvish") == "hey Jarvis"


def test_recipe_recorded_and_recalled():
    assert learning.record_success("open youtube and search songs", "browser", STEPS)
    hint = learning.hints_for("open YouTube and search for songs", "browser")
    assert "LEARNED FROM PAST SUCCESSES" in hint and "ctrl+l" in hint
    assert learning.hints_for("open youtube and search songs", "desktop") == ""
    assert learning.hints_for("write a report about sales", "browser") == ""


def test_recipe_dedup_increments_count():
    learning.record_success("open youtube", "browser", STEPS)
    learning.record_success("Open YouTube", "browser", STEPS)
    recipes = learning._load()["recipes"]
    assert len(recipes) == 1 and recipes[0]["count"] == 2


def test_qa_agents_are_not_learned():
    assert not learning.record_success("what is python", "voice_qa", STEPS)


def test_failure_removes_recipe_and_adds_correction():
    learning.record_success("open youtube", "browser", STEPS)
    learning.record_failure("open youtube", "browser", "that's wrong, you opened Upwork")
    data = learning._load()
    assert data["recipes"] == []
    hint = learning.hints_for("open youtube", "browser")
    assert "USER CORRECTIONS" in hint and "Upwork" in hint


def test_verified_marks_recipe():
    learning.record_success("open youtube", "browser", STEPS)
    assert learning.mark_verified("open youtube", "browser")
    assert "confirmed by the user" in learning.hints_for("open youtube", "browser")


def test_feedback_classification():
    assert feedback.classify("good job")[0] == "positive"
    assert feedback.classify("That was wrong")[0] == "negative"
    assert feedback.classify("no, that's not what I asked")[0] == "negative"
    assert feedback.classify("when I say piecham I mean PyCharm") == ("teach", "piecham|PyCharm")
    assert feedback.classify("open youtube") is None
    assert feedback.classify("Remember that Chrome is slow") is None


def test_feedback_handle_updates_memory():
    task = types.SimpleNamespace(instruction="open youtube", metadata={"agent": "browser"})
    learning.record_success("open youtube", "browser", STEPS)
    assert feedback.handle("perfect", task)
    assert learning._load()["recipes"][0]["verified"] is True
    assert feedback.handle("that was wrong", task)
    assert learning._load()["recipes"] == []
    assert "recent task" in feedback.handle("good job", None)
    assert feedback.handle("open youtube", task) is None
