"""Task planner: turns a user instruction into structured steps."""

from __future__ import annotations

import logging
from typing import Any

from agent.task_state import Task, TaskStep
from models.provider import get_provider

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are the planning component of an AI desktop assistant.
Given a user instruction, produce a JSON plan with these fields:
{
  "objective": "one sentence goal",
  "risk_level": "low|medium|high",
  "requires_approval": true|false,
  "steps": [
    {"description": "...", "tool": "...", "parameters": {...}}
  ]
}

Available tools:
- browser_navigate: {"url": "..."} — open a URL in Chrome
- browser_read: {} — read current page text / find elements
- browser_click: {"selector": "..."} — click an element on the page
- browser_fill: {"selector": "...", "value": "..."} — fill a form field
- browser_screenshot: {} — screenshot the current browser tab
- file_read: {"path": "..."} — read a local file
- file_write: {"path": "...", "content": "..."} — write a local file
- shell_run: {"command": "..."} — run a shell command (medium risk)
- web_search: {"query": "..."} — search the web
- summarize: {"text": "..."} — summarise text
- draft_document: {"title": "...", "body": "..."} — create a document
- google_chat_read: {} — read Google Chat messages
- google_chat_reply: {"message": "...", "thread_id": "..."} — reply in Google Chat
- upwork_search: {"keywords": "..."} — search Upwork job listings
- upwork_analyse: {"job_url": "..."} — analyse a job posting
- upwork_propose: {"job_url": "..."} — write a proposal for a job
- code_task: {"instruction": "...", "project": "..."} — send coding task to Claude Code
- screen_read: {} — capture and describe what is currently visible on the screen
- screen_click: {"x": 0, "y": 0, "button": "left"} — click at screen coordinates
- screen_type: {"text": "..."} — type text at the current cursor position
- screen_hotkey: {"keys": "ctrl+c"} — press a keyboard shortcut
- find_and_focus: {"title": "..."} — find a desktop window by title and bring it to front
- open_app: {"app": "chrome|notepad|calculator|..."} — open an application
- close_window: {"title": "Chrome|Notepad|...", "exe": "chrome.exe"} — close a window or kill a process
- wait_for_approval: {} — pause and request user approval
- ask_user: {"question": "..."} — ask the user a clarifying question
- no_op: {} — nothing to do

IMPORTANT — tool selection rules:
1. To open an app that is NOT already running: use open_app.
2. To navigate a URL in the user's EXISTING Chrome/browser window (already open on screen):
   - Step 1: find_and_focus with title "Chrome" to bring it to front.
   - Step 2: screen_hotkey with keys "ctrl+l" to focus the address bar.
   - Step 3: screen_type with the URL text.
   - Step 4: screen_hotkey with keys "enter" to navigate.
   Do NOT use browser_navigate for this — it opens a separate automated browser the user doesn't want.
3. Only use browser_navigate / browser_read / browser_click / browser_fill when you need
   to programmatically scrape or automate a web page (not just open a URL the user will interact with).
4. For clicking, reading screen, typing, hotkeys: always use screen_* and find_and_focus.

Set requires_approval=true for any action that sends messages, submits data externally, deletes files, or runs destructive commands.
Set risk_level="high" for irreversible, financially consequential, or externally visible actions.
Return ONLY the JSON object. No markdown, no explanation.
""".strip()


_AGENTIC_SUFFIX = """

STEP-BY-STEP MODE — you are called once per step.
Each call: review the instruction and the steps already completed (with results),
then return EXACTLY ONE next step as a JSON object:
  {"description": "...", "tool": "...", "parameters": {...}}
If the task is fully complete, return:
  {"done": true}
On the VERY FIRST call (no steps completed yet), also include:
  "risk_level": "low|medium|high"  and  "requires_approval": true|false

CRITICAL — screen coordinates:
When a screen_read step has been completed and its result describes the screen,
read that description carefully and use the ACTUAL positions of elements when
choosing screen_click coordinates. Never guess — use what screen_read reported.

Return ONLY valid JSON. No markdown, no explanation.
"""


def plan_next_step(
    instruction: str,
    completed_steps: list[dict],
    config=None,
) -> dict | None:
    """Return the next step to execute, or None when the task is done.

    completed_steps: list of {"description", "tool", "result"} for executed steps.
    """
    provider = get_provider()
    base_system = config.system_prompt if config else SYSTEM_PROMPT
    system = base_system + _AGENTIC_SUFFIX
    allowed = set(config.allowed_tools) if config and config.allowed_tools else None

    lines = [f"User instruction: {instruction}"]
    if completed_steps:
        lines.append("\nSteps completed so far:")
        for s in completed_steps:
            result_preview = (s.get("result") or s.get("error") or "")[:500]
            lines.append(f'  [{s["tool"]}] {s["description"]}\n    Result: {result_preview}')
        lines.append('\nWhat is the NEXT step? (or {"done": true} if complete)')
    else:
        lines.append("\nWhat is the FIRST step to take?")

    result: dict = provider.json_complete(
        system=system,
        user="\n".join(lines),
        max_tokens=512,
    )

    if not result or result.get("done"):
        return None

    tool = result.get("tool", "no_op")
    if allowed and tool not in allowed:
        log.warning("Agentic step used disallowed tool '%s' — blocked", tool)
        tool = "no_op"

    return {
        "description": result.get("description", ""),
        "tool": tool,
        "parameters": result.get("parameters", {}),
        "risk_level": result.get("risk_level", "low"),
        "requires_approval": result.get("requires_approval", False),
    }


def plan_task(task: Task, config=None) -> Task:
    """Plan a task.  Pass a SubAgentConfig to use a domain-focused prompt and tool set."""
    provider = get_provider()
    agent_name = config.name if config else "default"
    log.info("Planning task %s with %s [agent=%s]", task.id[:8], provider.name(), agent_name)

    system = config.system_prompt if config else SYSTEM_PROMPT

    result: dict[str, Any] = provider.json_complete(
        system=system,
        user=f"User instruction: {task.instruction}",
        max_tokens=1024,
    )

    task.objective = result.get("objective", task.instruction)
    task.risk_level = result.get("risk_level", "low")
    task.requires_approval = result.get("requires_approval", False)

    raw_steps = result.get("steps", [])
    if not raw_steps:
        raw_steps = [{"description": task.instruction, "tool": "ask_user", "parameters": {}}]

    allowed = set(config.allowed_tools) if config and config.allowed_tools else None

    steps = []
    for i, s in enumerate(raw_steps):
        tool = s.get("tool", "no_op")
        if allowed and tool not in allowed:
            log.warning("Planner used disallowed tool '%s' for agent '%s' — blocked", tool, agent_name)
            tool = "no_op"
        steps.append(TaskStep(
            index=i,
            description=s.get("description", ""),
            tool=tool,
            parameters=s.get("parameters", {}),
        ))
    task.steps = steps
    task.add_history("planned", f"{len(task.steps)} steps, risk={task.risk_level}, agent={agent_name}")
    return task
