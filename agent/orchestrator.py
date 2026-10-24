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

        if tool == "speak_answer":
            return self._tool_speak_answer(params)

        if tool == "screen_ask":
            return self._tool_screen_ask(params)

        if tool == "file_search":
            return self._tool_file_search(params)

        if tool == "file_open":
            return self._tool_file_open(params)

        if tool == "file_index_rebuild":
            from tools.file_indexer import get_indexer
            get_indexer().rebuild()
            return "File index rebuild started in background — will complete in ~30 seconds"

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

            import os, base64, io
            path = "data/screenshot_latest.png"
            with open(path, "wb") as f:
                f.write(png)

            # The vision model reports coordinates in the image it receives, so send a
            # fixed-size image and remember the factor needed to map clicks to real pixels.
            from PIL import Image
            full = Image.open(io.BytesIO(png))
            send_w = 1280
            send_h = round(full.height * send_w / full.width)
            self._shot_scale = full.width / send_w
            buf = io.BytesIO()
            full.convert("RGB").resize((send_w, send_h), Image.LANCZOS).save(buf, format="JPEG", quality=80)
            png = buf.getvalue()

            try:
                from models.provider import get_provider
                provider = get_provider()
                b64 = base64.b64encode(png).decode()
                desc = provider.complete_with_image(
                    "You are an AI desktop agent analyzing a screenshot to decide the next click or type action.",
                    (
                        f"This screenshot is exactly {send_w}x{send_h} pixels. All coordinates you give "
                        f"must be in this {send_w}x{send_h} pixel space.\n"
                        "Describe what you see on this screenshot. Be precise and concise:\n"
                        "1. Active window/app name (read the title bar)\n"
                        "2. URL in address bar (if visible — copy it exactly)\n"
                        "3. For each important UI element (buttons, links, input boxes, search bars, tabs):\n"
                        "   - Its label/text\n"
                        "   - Exact pixel coordinates: (x, y) where x=0 is left edge, y=0 is top edge\n"
                        "   Example: 'Search box at (640, 45)', 'Submit button at (820, 510)'\n"
                        "4. Any error messages or dialogs visible\n"
                        "Focus on elements the agent may need to click or type into next."
                    ),
                    b64,
                    media_type="image/jpeg",
                    max_tokens=500,
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
                # Browsers
                "chrome": "chrome.exe",
                "google chrome": "chrome.exe",
                "firefox": "firefox.exe",
                "edge": "msedge.exe",
                "microsoft edge": "msedge.exe",
                # System
                "notepad": "notepad.exe",
                "calculator": "calc.exe",
                "calc": "calc.exe",
                "explorer": "explorer.exe",
                "file explorer": "explorer.exe",
                "files": "explorer.exe",
                "cmd": "cmd.exe",
                "terminal": "cmd.exe",
                "command prompt": "cmd.exe",
                "powershell": "powershell.exe",
                "task manager": "taskmgr.exe",
                "settings": "ms-settings:",
                "control panel": "control.exe",
                "paint": "mspaint.exe",
                "wordpad": "wordpad.exe",
                # Office
                "word": "WINWORD.EXE",
                "excel": "EXCEL.EXE",
                "powerpoint": "POWERPNT.EXE",
                "outlook": "OUTLOOK.EXE",
                "onenote": "ONENOTE.EXE",
                # Communication
                "whatsapp": "whatsapp:",
                "telegram": "telegram.exe",
                "discord": "discord.exe",
                "slack": "slack.exe",
                "zoom": "zoom.exe",
                "teams": "teams.exe",
                "microsoft teams": "teams.exe",
                "skype": "skype.exe",
                # Media
                "spotify": "spotify.exe",
                "vlc": "vlc.exe",
                "photos": "ms-photos:",
                # Dev
                "vscode": "code.exe",
                "visual studio code": "code.exe",
                "vs code": "code.exe",
                "notepad++": "notepad++.exe",
                # Apple
                "icloud": "iCloudPhotos.exe",
                "ichon": "iCloudPhotos.exe",
            }
            exe = aliases.get(app.lower(), app)
            ok = adapter.open_application(exe)
            return f"Opened '{exe}'" if ok else f"Failed to open '{exe}'"

        if tool == "screen_click":
            scale = getattr(self, "_shot_scale", 1.0)
            x = int(int(params.get("x", 0)) * scale)
            y = int(int(params.get("y", 0)) * scale)
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

    def _tool_screen_ask(self, params: dict) -> str:
        """Answer a question about what is on screen (screenshot + open window titles) and speak it."""
        import base64, io, time as _time
        from computer.windows.adapter import WindowsAdapter
        question = params.get("question", "").strip() or "What is on my screen right now?"
        adapter = WindowsAdapter()
        _time.sleep(1.0)
        png = adapter.capture_screen()
        if not png:
            return "Screen capture not available (pyautogui missing)"

        from PIL import Image
        full = Image.open(io.BytesIO(png))
        send_w = 1280
        send_h = round(full.height * send_w / full.width)
        buf = io.BytesIO()
        full.resize((send_w, send_h), Image.LANCZOS).save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        titles = [w.title for w in adapter.list_windows()
                  if not any(s in w.title for s in ("AI Desktop Agent", "Program Manager"))]
        titles_text = "\n".join(f"- {t[:120]}" for t in titles[:25]) or "(unavailable)"

        from models.provider import get_provider
        answer = get_provider().complete_with_image(
            "You answer questions about the user's computer screen for a voice assistant. "
            "Be accurate and brief: 1-3 plain spoken sentences, no markdown, no coordinates. "
            "Use the open window titles as hard evidence (editor titles usually contain the "
            "project name). If the user names an app that is not open, say so and say which "
            "app is actually showing.",
            f"Open window titles:\n{titles_text}\n\nUser question: {question}",
            b64,
            max_tokens=250,
        ).strip()
        try:
            from voice.speech_output import get_speech_output
            get_speech_output().speak(answer)
        except Exception as exc:
            log.warning("screen_ask TTS failed: %s", exc)
        return answer

    def _tool_speak_answer(self, params: dict) -> str:
        answer = params.get("answer", "").strip()
        if not answer:
            return "No answer provided"
        try:
            from voice.speech_output import get_speech_output
            get_speech_output().speak(answer)
        except Exception as exc:
            log.warning("speak_answer TTS failed: %s", exc)
        return answer

    def _tool_file_search(self, params: dict) -> str:
        from tools.file_indexer import get_indexer
        indexer = get_indexer()
        if not indexer.is_ready():
            return "File index is still building — please try again in a few seconds"
        query = params.get("query", "").strip()
        if not query:
            return "No search query provided"
        results = indexer.search(query)
        if not results:
            stats = indexer.stats()
            return (
                f"No files found matching '{query}'. "
                f"Index has {stats['filenames_indexed']} filenames. "
                "Try a shorter or different term, or use file_index_rebuild to rescan."
            )
        lines = [f"Found {len(results)} file(s) matching '{query}':"]
        for r in results:
            lines.append(f"  {r['name']}  →  {r['path']}")
        return "\n".join(lines)

    def _tool_file_open(self, params: dict) -> str:
        import os
        path = params.get("path", "").strip()
        if not path:
            return "No path provided"
        if not os.path.exists(path):
            return f"File not found: {path}"
        try:
            os.startfile(path)
            return f"Opened: {path}"
        except Exception as exc:
            return f"Failed to open '{path}': {exc}"

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
