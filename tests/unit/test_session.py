import time
from types import SimpleNamespace

import pytest

from agent import session


def _task(instruction="Open Chrome and check the tab", status="completed"):
    steps = [
        SimpleNamespace(tool="find_and_focus", description="Focus Chrome", result="Focused"),
        SimpleNamespace(tool="screen_ask", description="Ask about tab", result="A YouTube page with songs"),
    ]
    return SimpleNamespace(instruction=instruction, status=SimpleNamespace(value=status), steps=steps)


@pytest.fixture(autouse=True)
def _clean():
    session.clear()
    yield
    session.clear()


def test_remember_and_context():
    session.remember(_task(), "browser")
    rec = session.last()
    assert rec and rec.agent == "browser"
    block = session.context_block(rec)
    assert "FOLLOW-UP" in block and "A YouTube page with songs" in block


def test_qa_agents_do_not_overwrite_context():
    session.remember(_task(), "browser")
    session.remember(_task("What is Python?"), "voice_qa")
    assert session.last().instruction.startswith("Open Chrome")


def test_cancelled_not_remembered():
    session.remember(_task(status="cancelled"), "browser")
    assert session.last() is None


def test_expires():
    session.remember(_task(), "browser")
    session._last.finished_at = time.time() - 3600
    assert session.last() is None


@pytest.mark.parametrize("text,expected", [
    ("now click the first one", True),
    ("scroll down", True),
    ("what is it doing now", True),
    ("Open Notepad", False),
    ("Find my resume on the computer please and open it for me right now thanks a lot", False),
])
def test_heuristic(text, expected):
    assert session.looks_like_followup(text) is expected
