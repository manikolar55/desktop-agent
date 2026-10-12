"""Command parser — classifies spoken/typed text into intent categories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class CommandIntent(str, Enum):
    STOP_EVERYTHING = "stop_everything"
    CANCEL_CURRENT = "cancel_current"
    PAUSE = "pause"
    RESUME = "resume"
    STATUS_QUERY = "status_query"
    EXPLAIN_ERROR = "explain_error"
    GREETING = "greeting"
    CONVERSATIONAL = "conversational"
    NEW_TASK = "new_task"
    CONFIRM = "confirm"
    DENY = "deny"
    UNKNOWN = "unknown"


@dataclass
class ParsedCommand:
    intent: CommandIntent
    text: str
    task_instruction: str = ""


# ── Control-command patterns ──────────────────────────────────────────────────

_STOP_ALL = re.compile(
    r"\b(stop everything|stop all|cancel all|emergency stop|halt|shut(?: it)? down"
    r"|close (the )?(agent|app|application|yourself)"
    r"|quit( the agent)?|exit( the agent)?)\b", re.I
)
_CANCEL = re.compile(
    r"\b(stop(?: this)?(?: task)?|cancel(?: (this|current|the) (task|operation))?)\b", re.I
)
_PAUSE = re.compile(r"\b(pause|hold on|wait)\b", re.I)
_RESUME = re.compile(r"\b(resume|continue|go ahead|proceed|keep going)\b", re.I)
_STATUS = re.compile(
    r"\b(what are you (doing|working on)|status|progress|what('s| is) happening"
    r"|which task(s)? (you |have )?(done|completed|finished|are you doing)"
    r"|what task(s)? (have you |did you )?(done|complete|finish)"
    r"|any task|task (done|complete|status|report|history)"
    r"|what have you done|what did you do)\b",
    re.I,
)
_EXPLAIN = re.compile(
    r"\b(what went wrong|explain (the )?error|what (happened|failed)|why did it fail)\b", re.I
)
_CONFIRM = re.compile(r"^\s*(yes|yeah|yep|approve|confirm|ok|okay|go ahead|do it)\s*$", re.I)
_DENY = re.compile(r"^\s*(no|nope|deny|reject|don'?t|abort|cancel)\s*$", re.I)
_GREETING_START = re.compile(
    r"^\s*(hi+|hello+|hey+|howdy|good (morning|afternoon|evening|day)|yo|sup|greetings)\b",
    re.I,
)
_GREETING_FULL = re.compile(
    r"^\s*(how are you|how('s| is) it going|what'?s up)\s*[!?.]*\s*$",
    re.I,
)

# ── Task-verb detection (imperative commands directed at the computer) ─────────
# Strip delegation / softener prefixes before checking the task verb.
# "now", "just", "not" are included because Whisper often renders "now click"
# as "not click" and users say "just click on that link".
_DELEGATION_STRIP = re.compile(
    r"^\s*((?:(?:can|could|will|would|please|hey|now|just|not)\s+)+(?:you\s+)?)", re.I
)

# Correction prefix: "No, ...", "Not that, ...", "Actually, ..."
# When present the remainder is treated as the real instruction.
_CORRECTION_PREFIX = re.compile(
    r"^\s*(?:no[,.]?\s+|nope[,.]?\s+|not\s+that[,.]?\s+|actually[,.]?\s+|wait[,.]?\s+)",
    re.I,
)
# Task verb anywhere in text (used for correction-prefix extraction).
_TASK_VERB_ANYWHERE = re.compile(
    r"\b(open|close|navigate|go\s+to|search|find|click|type|press|send|read|write|"
    r"create|delete|move|copy|download|upload|launch|start|stop|save|play|scroll|"
    r"switch|take|get|run|set|minimize|maximize|drag|research|summarize|draft|"
    r"compose|analyze|share|convert|rename|forward|reply|schedule|add|list|"
    r"summarise|translate|compare|review|capture|merge)\b",
    re.I,
)

# If what remains starts with one of these verbs, it is a computer task.
_TASK_VERB_START = re.compile(
    r"^\s*(open|close|navigate|go\s+to|search|find|click|type|press|send|read|write|"
    r"create|delete|remove|move|copy|download|upload|launch|start|stop|save|print|"
    r"play|record|scroll|zoom|switch|install|uninstall|restart|login|logout|bookmark|"
    r"refresh|reload|enable|disable|turn|change|edit|clear|select|paste|cut|undo|"
    r"redo|take|screenshot|show|hide|get|fetch|grab|look|check|run|execute|set|"
    r"minimize|maximize|resize|drag|drop|right.click|double.click|"
    r"connect|disconnect|sign|log|"
    r"research|summarize|draft|compose|analyze|monitor|watch|track|report|share|"
    r"attach|extract|convert|compress|rename|forward|reply|schedule|book|add|list|"
    r"summarise|translate|compare|review|scan|capture|zip|unzip|merge|split|"
    r"go|click|tap|swipe|enter|submit|confirm|approve|reject)\b",
    re.I,
)


def parse_command(text: str) -> ParsedCommand:
    t = text.strip()

    # 1. Hard control commands — always checked first.
    if _STOP_ALL.search(t):
        return ParsedCommand(intent=CommandIntent.STOP_EVERYTHING, text=t)
    if _CANCEL.search(t):
        return ParsedCommand(intent=CommandIntent.CANCEL_CURRENT, text=t)
    if _PAUSE.search(t):
        return ParsedCommand(intent=CommandIntent.PAUSE, text=t)
    if _RESUME.search(t):
        return ParsedCommand(intent=CommandIntent.RESUME, text=t)
    if _STATUS.search(t):
        return ParsedCommand(intent=CommandIntent.STATUS_QUERY, text=t)
    if _EXPLAIN.search(t):
        return ParsedCommand(intent=CommandIntent.EXPLAIN_ERROR, text=t)
    if _GREETING_START.match(t) or _GREETING_FULL.match(t):
        return ParsedCommand(intent=CommandIntent.GREETING, text=t)
    if _CONFIRM.match(t):
        return ParsedCommand(intent=CommandIntent.CONFIRM, text=t)
    if _DENY.match(t):
        return ParsedCommand(intent=CommandIntent.DENY, text=t)

    # 2. Task verb check comes BEFORE the word-count guard so that short but valid
    #    imperatives like "Open YouTube" or "Close Chrome" are never dropped.
    stripped = _DELEGATION_STRIP.sub("", t)
    if _TASK_VERB_START.match(t) or _TASK_VERB_START.match(stripped):
        return ParsedCommand(intent=CommandIntent.NEW_TASK, text=t, task_instruction=t)

    # 3. Too short — almost certainly noise or an incomplete transcription.
    if len(t.split()) < 3:
        return ParsedCommand(intent=CommandIntent.UNKNOWN, text=t)

    # 3b. Correction prefix ("No, just click on that link") — strip the prefix
    #     and look for a task verb anywhere in the remainder.
    corr_match = _CORRECTION_PREFIX.match(t)
    if corr_match:
        remainder = t[corr_match.end():].strip()
        if remainder and _TASK_VERB_ANYWHERE.search(remainder):
            return ParsedCommand(
                intent=CommandIntent.NEW_TASK, text=t, task_instruction=remainder
            )

    # 4. Everything else → conversational.  The LLM handles questions, opinions,
    #    capability queries, and anything Whisper garbles into non-imperative form.
    return ParsedCommand(intent=CommandIntent.CONVERSATIONAL, text=t)
