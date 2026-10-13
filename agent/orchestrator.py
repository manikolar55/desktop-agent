"""Central orchestrator: owns the task queue, execution loop, and tool dispatch."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from agent.execution_loop import ExecutionLoop
from agent.task_queue import TaskQueue
from agent.task_state import Task, TaskStatus, TaskStep
from config.permissions import Action
from security.audit_log import record as audit
from storage.repositories import task_repo

log = logging.getLogger(__name__)

StatusCallback = Callable[[Task], None]


class Orchestrator:
    def __init__(self) -> None:
        self._queue = TaskQueue()
        self._loop = ExecutionLoop(
            tool_executor=self._dispatch_tool,
            progress_callback=self._on_progress,
        )
        self._status_callbacks: list[StatusCallback] = []
        self._worker_thread: threading.Thread | None = None
        self._running = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        recovered = self._queue.restore_from_db()
        log.info("Orchestrator started; recovered %d tasks", recovered)
        self._worker_thread = threading.Thread(
            target=self._worker, name="AgentWorker", daemon=True
        )
        self._worker_thread.start()

    def stop(self) -> None:
        self._running = False
        self._loop.stop()
        log.info("Orchestrator stopping")

    def emergency_stop(self) -> int:
        """Cancel everything immediately."""
        self._loop.stop()
        count = self._queue.cancel_all()
        audit("emergency_stop", f"Cancelled {count} tasks", risk_level="medium", actor="user")
        return count

    # ── Task submission ───────────────────────────────────────────────────────

    def submit(self, instruction: str, idempotency_key: str | None = None) -> Task:
        task = Task(instruction=instruction, idempotency_key=idempotency_key)
        task = self._queue.enqueue(task)
        audit("task_submitted", instruction[:120], task_id=task.id)
        return task

    def cancel_current(self) -> bool:
        self._loop.stop()
        result = self._queue.cancel_active()
        self._loop.reset_stop()
        return result

    # ── Status ────────────────────────────────────────────────────────────────

    def add_status_callback(self, cb: StatusCallback) -> None:
        self._status_callbacks.append(cb)

    def active_task(self) -> Task | None:
        return self._queue.active_task()

    def queued_tasks(self) -> list[Task]:
        return self._queue.queued_tasks()

    def recent_tasks(self, limit: int = 50) -> list[Task]:
        return task_repo.list_recent(limit)

    # ── Worker loop ───────────────────────────────────────────────────────────

    def _worker(self) -> None:
        import time
        from agent.router import get_router
        router = get_router()

        while self._running:
            task = self._queue.next()
            if task is None:
                time.sleep(0.5)
                continue
            if task.status == TaskStatus.CANCELLED:
                continue
            self._loop.reset_stop()
            config = router.route(task.instruction)
            log.info("Starting task %s [%s]: %s", task.id[:8], config.name, task.instruction[:80])
            self._loop.run(task, config=config)

    # ── Tool dispatch ─────────────────────────────────────────────────────────

    def _dispatch_tool(self, task: Task, step: TaskStep) -> str:
        tool = step.tool
        params = step.parameters

        if tool == "no_op":
            return "No action taken"

        if tool == "wait":
            import time as _time
            seconds = float(params.get("seconds", 2))
            seconds = min(seconds, 10)  # cap at 10s
            _time.sleep(seconds)
            return f"Waited {seconds}s"

        if tool == "ask_user":
            return f"[User input required] {step.description}"

        if tool == "wait_for_approval":
            from security.approvals import request_approval
            approved = request_approval(task.id, tool, step.description)
            return "Approved" if approved else "Denied"

        if tool == "web_search":
            return self._tool_web_search(params)

        if tool in ("browser_navigate", "browser_read", "browser_click",
                    "browser_fill", "browser_screenshot"):
            return self._tool_browser(tool, params, task)

        if tool == "file_read":
            return self._tool_file_read(params)

        if tool == "file_write":
            return self._tool_file_write(params, task)

        if tool == "shell_run":
            return self._tool_shell(params, task)

        if tool == "summarize":
            return self._tool_summarize(params)

        if tool == "draft_document":
            return self._tool_draft_document(params)

        if tool == "code_task":
            return self._tool_code_task(params, task)

        if tool in ("google_chat_read", "google_chat_reply"):
            return self._tool_google_chat(tool, params, task)

        if tool in ("upwork_search", "upwork_analyse", "upwork_propose",
                    "upwork_implementation_plan", "upwork_process_queue"):
            return self._tool_upwork(tool, params, task)

        if tool in ("screen_read", "screen_click", "screen_type",
                    "open_app", "find_and_focus", "screen_hotkey", "close_window"):
            return self._tool_computer(tool, params, task)

        return f"Unknown tool '{tool}' — skipped"

    def _tool_web_search(self, params: dict) -> str:
        query = params.get("query", "")
        if not query:
            return "No search query provided"
        try:
            import httpx
            resp = httpx.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=15,
            )
            from browser.page_inspector import extract_text_from_html
            text = extract_text_from_html(resp.text)
            return text[:3000]
        except Exception as exc:
            return f"Web search failed: {exc}"

    def _tool_browser(self, tool: str, params: dict, task: Task) -> str:
        try:
            from browser.manager import get_browser_manager
            bm = get_browser_manager()
            if tool == "browser_navigate":
                return bm.navigate(params.get("url", ""))
            if tool == "browser_read":
                return bm.read_page()
            if tool == "browser_click":
                return bm.click(params.get("selector", ""))
            if tool == "browser_fill":
                return bm.fill(params.get("selector", ""), params.get("value", ""))
            if tool == "browser_screenshot":
                path = bm.screenshot()
                return f"Screenshot saved: {path}"
        except Exception as exc:
            return f"Browser action failed: {exc}"
        return "Unknown browser action"

    def _tool_file_read(self, params: dict) -> str:
        import os
        path = params.get("path", "")
        if not path or not os.path.exists(path):
            return f"File not found: {path}"
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(10000)

    def _tool_file_write(self, params: dict, task: Task) -> str:
        from config.permissions import Action, requires_approval
        from security.approvals import request_approval
        path = params.get("path", "")
        content = params.get("content", "")
        if not path:
            return "No path specified"
        if requires_approval(Action.EDIT_PROJECT_FILE):
            approved = request_approval(task.id, "file_write", f"Write file: {path}")
            if not approved:
                return "Write denied by user"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} bytes to {path}"

    def _tool_shell(self, params: dict, task: Task) -> str:
        from config.permissions import Action, requires_approval
        from security.approvals import request_approval
        cmd = params.get("command", "")
        if not cmd:
            return "No command"
        if requires_approval(Action.RUN_SHELL_COMMAND):
            approved = request_approval(task.id, "shell_run", f"Run command: {cmd}")
            if not approved:
                return "Command denied"
        import subprocess
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60
        )
        out = result.stdout[:2000] + (result.stderr[:500] if result.returncode else "")
        return out

    def _tool_summarize(self, params: dict) -> str:
        text = params.get("text", "")
        from models.provider import get_provider
        p = get_provider()
        return p.complete("Summarise the following text concisely.", text, max_tokens=512)

    def _tool_draft_document(self, params: dict) -> str:
        from workflows.documents import draft_document
        return draft_document(params)

    def _tool_code_task(self, params: dict, task: Task) -> str:
        from integrations.claude_code.session import send_code_task
        return send_code_task(params.get("instruction", ""), params.get("project", ""))

    def _tool_google_chat(self, tool: str, params: dict, task: Task) -> str:
        return f"[Google Chat] {tool} not yet configured — check integration settings"

    def _tool_computer(self, tool: str, params: dict, task: Task) -> str:
        from computer.windows.adapter import WindowsAdapter, _WIN32_AVAILABLE
        adapter = WindowsAdapter()

        if tool == "screen_read":
            import time as _time
            # 1.5s: page render time + Qt main-thread hide propagation (150ms drain timer)
            _time.sleep(1.5)
            png = adapter.capture_screen()
            if not png:
                return "Screen capture not available (pyautogui missing)"

            import os, base64
            path = "data/screenshot_latest.png"
            with open(path, "wb") as f:
                f.write(png)

            try:
                from models.provider import get_provider
                provider = get_provider()
                b64 = base64.b64encode(png).decode()
                desc = provider.complete_with_image(
                    "You are an AI desktop agent analyzing a screenshot to decide the next action.",
                    (
                        "Describe everything you see on this screenshot precisely:\n"
                        "- What application/window is in focus (title bar text)\n"
                        "- The URL shown in the address bar (if a browser is open)\n"
                        "- Key UI elements visible (search box, buttons, links, text)\n"
                        "- Approximate screen coordinates (x, y) for important clickable elements\n"
                        "Be concise but precise. This is used to decide the next click/type action."
                    ),
                    b64,
                    max_tokens=600,
                )
                return f"Screen contents:\n{desc}"
            except Exception as exc:
                return f"Screenshot saved to {path} (vision error: {exc})"

        if tool == "find_and_focus":
            title = params.get("title", "")
            win = adapter.find_window(title)
            if win:
                adapter.focus_window(win)
                return f"Focused window: '{win.title}'"
            return f"No window found matching '{title}'"

        if tool == "open_app":
            app = params.get("app", params.get("executable", ""))
            # Common aliases
            aliases = {
                "chrome": "chrome.exe",
                "google chrome": "chrome.exe",
                "notepad": "notepad.exe",
                "calculator": "calc.exe",
                "explorer": "explorer.exe",
                "cmd": "cmd.exe",
                "terminal": "cmd.exe",
                "whatsapp": "whatsapp:",
                "telegram": "telegram.exe",
            }
            exe = aliases.get(app.lower(), app)
            ok = adapter.open_application(exe)
            return f"Opened '{exe}'" if ok else f"Failed to open '{exe}'"

        if tool == "screen_click":
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            btn = params.get("button", "left")
            adapter.click_mouse(x, y, btn)
            return f"Clicked {btn} at ({x}, {y})"

        if tool == "screen_type":
            text = params.get("text", "")
            # Use pyautogui hotkey approach for better Unicode support
            try:
                import pyautogui
                import pyperclip
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
            except Exception:
                adapter.send_keys(text)
            return f"Typed: {text[:60]}"

        if tool == "screen_hotkey":
            keys = params.get("keys", "")
            try:
                import pyautogui
                pyautogui.hotkey(*keys.split("+"))
                return f"Hotkey: {keys}"
            except Exception as exc:
                return f"Hotkey failed: {exc}"

        if tool == "close_window":
            title = params.get("title", "")
            # Try graceful WM_CLOSE first, then Alt+F4, then taskkill
            if _WIN32_AVAILABLE and title:
                win = adapter.find_window(title)
                if win:
                    try:
                        import win32gui, win32con
                        win32gui.PostMessage(win.hwnd, win32con.WM_CLOSE, 0, 0)
                        return f"Closed window: '{win.title}'"
                    except Exception:
                        pass
            # Fallback: taskkill by exe name
            exe = params.get("exe", "")
            if exe:
                import subprocess
                subprocess.run(f"taskkill /IM {exe} /F", shell=True, capture_output=True)
                return f"Killed process: {exe}"
            return "close_window: no matching window found"

        return f"Unknown computer tool: {tool}"

    def _tool_upwork(self, tool: str, params: dict, task: Task) -> str:
        from workflows.job_research import upwork_tool
        return upwork_tool(tool, params, task)

    def _on_progress(self, task: Task) -> None:
        for cb in self._status_callbacks:
            try:
                cb(task)
            except Exception:
                pass


_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
