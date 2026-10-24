"""Spoken feedback ("that was wrong", "good job", "when I say X I mean Y") → learning memory."""

from __future__ import annotations

import re

from agent import learning

_POSITIVE = re.compile(
    r"^\s*(good job|well done|great job|nice work|nice one|perfect|exactly|correct|"
    r"(that|this|it)('s| is| was) (right|correct|perfect|great|good|exactly (right|what i wanted)))\b[\s.!]*$",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"^\s*(no[,.]?\s+)?((that|this|it)('s| is| was) (not (right|correct|what i (asked|wanted|said))|wrong|incorrect)|"
    r"you (did|got) (it|that) wrong|wrong|not what i (asked|wanted|said))\b",
    re.IGNORECASE,
)
_TEACH = re.compile(
    r"^\s*(?:when i say|remember that|remember,?|note that)\s+[\"']?(.+?)[\"']?\s+"
    r"(?:i mean|means|mean)\s+[\"']?(.+?)[\"']?[\s.!]*$",
    re.IGNORECASE,
)


def classify(text: str) -> tuple[str, str] | None:
    """Return ("teach", "wrong|right"), ("positive", ""), ("negative", note) or None."""
    m = _TEACH.match(text)
    if m:
        return "teach", f"{m.group(1)}|{m.group(2)}"
    if _POSITIVE.match(text):
        return "positive", ""
    if _NEGATIVE.match(text) and len(text.split()) <= 25:
        return "negative", text.strip()
    return None


def handle(text: str, last_task) -> str | None:
    """Apply feedback to the learning memory. Returns a short spoken reply, or None if `text` isn't feedback."""
    fb = classify(text)
    if fb is None:
        return None
    kind, payload = fb

    if kind == "teach":
        wrong, right = payload.split("|", 1)
        learning.teach_vocab(wrong, right)
        return f"Got it. When you say {wrong.strip()}, I'll understand {right.strip()}."

    if last_task is None:
        return "I don't have a recent task to learn from yet."
    agent = last_task.metadata.get("agent", "")
    if kind == "positive":
        learning.mark_verified(last_task.instruction, agent)
        return "Thanks, I'll remember that this worked."
    learning.record_failure(last_task.instruction, agent, payload)
    return "Sorry about that. I'll remember not to do it that way."
