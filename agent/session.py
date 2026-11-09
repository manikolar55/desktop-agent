"""Short-term session memory: lets a follow-up instruction continue the previous task."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# Only tasks that leave something on screen can be continued. Q&A / file search must not
# overwrite the context of the Chrome page the user is still working in.
STATEFUL_AGENTS = ("browser", "desktop", "email_chat", "file_docs")

_TTL_SECONDS = 15 * 60

_FOLLOWUP_MARKERS = (
    "now", "then", "next", "also", "again", "that", "it", "this", "those", "these",
    "first", "second", "third", "last", "same", "there", "scroll", "back", "click",
    "continue", "and", "another", "one", "more", "tab", "page", "result",
)


@dataclass
class SessionRecord:
    instruction: str
    agent: str
    status: str
    steps: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    finished_at: float = field(default_factory=time.time)


_last: SessionRecord | None = None


def remember(task, agent: str) -> None:
    global _last
    if agent not in STATEFUL_AGENTS:
        return
    status = task.status.value
    if status == "cancelled":
        return
    steps = [f"{s.tool}: {s.description[:90]}" for s in task.steps[-8:]]
    findings = [
        f"{s.tool} -> {str(s.result).strip()[:400]}"
        for s in task.steps
        if s.tool in ("screen_ask", "screen_read", "web_search", "browser_read") and s.result
    ][-2:]
    _last = SessionRecord(task.instruction, agent, status, steps, findings)


def last() -> SessionRecord | None:
    if _last is None or time.time() - _last.finished_at > _TTL_SECONDS:
        return None
    return _last


def clear() -> None:
    global _last
    _last = None


def looks_like_followup(instruction: str) -> bool:
    words = re.findall(r"[a-z']+", instruction.lower())
    if len(words) > 14:
        return False
    text = " " + " ".join(words) + " "
    return any(f" {m} " in text for m in _FOLLOWUP_MARKERS)


def context_block(rec: SessionRecord) -> str:
    lines = [
        "PREVIOUS TASK — the new instruction is a FOLLOW-UP to it. Continue from where it left off:",
        f"  Instruction: {rec.instruction}",
        f"  Outcome: {rec.status}",
    ]
    if rec.steps:
        lines.append("  What was done: " + " | ".join(rec.steps))
    for f in rec.findings:
        lines.append(f"  Seen/said: {f}")
    lines.append(
        "The app or page from that task is most likely still open. Do NOT reopen it, do NOT "
        "navigate away and do NOT start over — bring it to the front (find_and_focus) and act on "
        "its current state to do what the new instruction asks."
    )
    return "\n".join(lines)
