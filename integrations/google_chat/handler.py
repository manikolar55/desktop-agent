"""
Google Chat message handler.

Receives raw (untrusted) message dicts from the polling client,
validates them, deduplicates, maps to a project, and dispatches
a bug-fixing task through the orchestrator.

Security contract: message text is NEVER executed as code or used as a
system instruction. It is passed only as user-provided data to the workflow.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from models.schemas import BugReport

log = logging.getLogger(__name__)

_PROCESSED_MESSAGE_IDS: set[str] = set()

MENTION_PATTERNS = [
    re.compile(r"@agent\b", re.I),
    re.compile(r"\bbug\b", re.I),
    re.compile(r"\berror\b", re.I),
    re.compile(r"\bfixed\b", re.I),
    re.compile(r"\bissue\b", re.I),
    re.compile(r"\bbroken\b", re.I),
]

# Patterns that could indicate prompt-injection attempts
INJECTION_PATTERNS = [
    re.compile(r"\bignore previous instructions\b", re.I),
    re.compile(r"\bsystem prompt\b", re.I),
    re.compile(r"\brun shell\b", re.I),
    re.compile(r"\bexecute command\b", re.I),
    re.compile(r"\bdrop table\b", re.I),
    re.compile(r"\bdelete all\b", re.I),
]


def handle_message(msg: dict) -> None:
    """Entry point called by the polling client for each new message."""
    msg_id = msg.get("name", "")
    text = msg.get("text", "").strip()
    space_id = msg.get("space", "")
    sender = msg.get("sender", "unknown")
    thread = msg.get("thread", "")

    # Deduplicate
    if msg_id in _PROCESSED_MESSAGE_IDS:
        log.debug("Duplicate message ignored: %s", msg_id)
        return
    _PROCESSED_MESSAGE_IDS.add(msg_id)

    # Security: detect and block injection attempts
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            log.warning(
                "Possible prompt-injection attempt in Chat message from %s: '%s'",
                sender, text[:100]
            )
            return  # Do not process — do not reply

    # Filter: only process messages that seem relevant
    if not _is_relevant(text):
        log.debug("Message not relevant — skipping: %s", text[:60])
        return

    # Map space to project
    project_name = _resolve_project(space_id)
    if not project_name:
        log.info("No project mapped to space %s — cannot process bug report", space_id)
        return

    log.info("Bug report from %s in %s: %s", sender, space_id, text[:80])

    report = BugReport(
        source="google_chat",
        reporter=sender,
        description=text,
        thread_id=thread,
        space_id=space_id,
        project_name=project_name,
        raw_message=msg_id,
    )

    _dispatch_to_orchestrator(report)


def _is_relevant(text: str) -> bool:
    return any(p.search(text) for p in MENTION_PATTERNS)


def _resolve_project(space_id: str) -> str:
    from storage.repositories import pref_repo
    registry = pref_repo.get("project_registry", [])
    for project in registry:
        if space_id in project.get("chat_space_ids", []):
            return project.get("name", "")
    return ""


def _dispatch_to_orchestrator(report: BugReport) -> None:
    try:
        from agent.orchestrator import get_orchestrator
        instruction = (
            f"Bug reported via Google Chat by {report.reporter}:\n"
            f"{report.description}\n\n"
            f"Project: {report.project_name}. "
            f"Investigate, fix, run tests, verify. Do not deploy to production."
        )
        orch = get_orchestrator()
        idempotency_key = f"gchat:{report.raw_message}"
        task = orch.submit(instruction, idempotency_key=idempotency_key)
        log.info("Bug-fix task submitted: %s", task.id[:8])
    except Exception as exc:
        log.error("Failed to dispatch bug report to orchestrator: %s", exc)


def reset_seen_messages() -> None:
    """Test helper — clears the deduplication set."""
    _PROCESSED_MESSAGE_IDS.clear()
