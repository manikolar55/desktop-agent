"""
AI Desktop Agent — application entry point.
Run with: python app.py
"""

from __future__ import annotations

import logging
import queue
import sys
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QColor, QPixmap

# Initialise logging before any imports that use it
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def _make_tray_icon() -> QIcon:
    px = QPixmap(16, 16)
    px.fill(QColor("#4488ff"))
    return QIcon(px)


_CLEAN_SYSTEM = (
    "You are a voice command interpreter for an AI desktop assistant on Windows. "
    "The user's speech was transcribed by Whisper and may contain errors, repeated words, "
    "filler phrases, or garbled app names. "
    "Your job: extract the user's ACTUAL intent as a short, clear computer task instruction.\n\n"
    "Rules:\n"
    "- Fix obvious transcription errors: 'Ichon'→'iCloud', 'up work'→'Upwork', "
    "'you tube'→'YouTube', 'goggle'→'Google', 'chrone'→'Chrome'\n"
    "- Remove filler: 'for me', 'please', 'I want you to', 'can you', 'that is already open'\n"
    "- Keep app names, URLs, search terms intact\n"
    "- If the instruction has repeated sentences, keep only one clean version\n"
    "- Return ONLY the cleaned instruction — no explanation, no quotes\n\n"
    "Examples:\n"
    "  'Open app Ichon from for me and in that window open cloud and select the cloud subscription'"
    " → 'Open iCloud and select cloud subscription'\n"
    "  'I open the Chrome browser and in the Chrome browser open terminal and in the terminal search cloud'"
    " → 'Open Chrome and search Google Cloud Console'\n"
    "  'The Chrome browser current Chrome browser that is already open open that such the YouTube'"
    " → 'Open YouTube in Chrome'\n"
    "  'Open the Chrome browser and search up for a new app open the existing Chrome browser not the new one'"
    " → 'Search for new apps in existing Chrome window'\n"
    "  'Search Upwork in the new tab of the browser' → 'Open Upwork in a new Chrome tab'\n"
)


def _clean_instruction(raw: str) -> str:
    """Fix Whisper transcription errors with Claude before routing/planning."""
    if len(raw.split()) < 5:
        return raw  # short commands are usually fine
    try:
        from models.provider import get_provider
        cleaned = get_provider().complete(_CLEAN_SYSTEM, raw, max_tokens=80)
        cleaned = cleaned.strip().strip('"').strip("'")
        if cleaned and len(cleaned) > 3:
            return cleaned
    except Exception:
        pass
    return raw


def main() -> None:
    import os, signal
    os.makedirs("data", exist_ok=True)

    # Make Ctrl+C quit the Qt app cleanly instead of just interrupting the main thread
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Initialise database
    from storage.database import init_db
    init_db()

    # Load project registry from YAML into preferences DB
    from config.project_registry import bootstrap_registry
    registry = bootstrap_registry()
    log.info("Project registry: %d projects loaded", len(registry))

    # Initialise approval callback (wires UI to security layer)
    from security.approvals import set_approval_callback

    app = QApplication(sys.argv)
    app.setApplicationName("AI Desktop Agent")
    app.setOrganizationName("DevsloopTech")
    app.setQuitOnLastWindowClosed(False)

    # ── Start orchestrator ────────────────────────────────────────────────────
    from agent.orchestrator import get_orchestrator
    orch = get_orchestrator()

    # ── Build UI ──────────────────────────────────────────────────────────────
    from ui.avatar import FloatingAvatar
    from ui.dashboard import Dashboard

    avatar = FloatingAvatar()
    dashboard = Dashboard()

    # Shared state for the currently-open approval dialog so voice "yes/no" can close it.
    _active_approval: dict = {}

    # Wire approval callback to show a dialog on the UI thread
    def _approval_cb(task_id: str, action: str, description: str) -> bool:
        result = [False]
        done = threading.Event()

        def _show():
            from ui.approval_dialog import ApprovalDialog
            dlg = ApprovalDialog(task_id, action, description, parent=dashboard)
            _active_approval["dlg"] = dlg
            _active_approval["result"] = result
            if dlg.exec():
                result[0] = dlg.was_approved()
            _active_approval.clear()
            done.set()

        QTimer.singleShot(0, _show)
        done.wait(timeout=120)
        _active_approval.clear()
        return result[0]

    set_approval_callback(_approval_cb)

    # ── Wire signals ──────────────────────────────────────────────────────────
    def _handle_instruction(text: str) -> None:
        from voice.commands import parse_command, CommandIntent
        cmd = parse_command(text)
        log.info("Command: intent=%s text=%s", cmd.intent.value, text)

        if cmd.intent.name == "STOP_EVERYTHING":
            n = orch.emergency_stop()
            from voice.speech_output import get_speech_output
            get_speech_output().speak(f"Stopped. Cancelled {n} tasks.")
            return

        if cmd.intent.name == "CONFIRM":
            from voice.speech_output import get_speech_output
            if _active_approval.get("dlg"):
                _active_approval["result"][0] = True
                QTimer.singleShot(0, _active_approval["dlg"].accept)
                get_speech_output().speak("Approved.")
            else:
                get_speech_output().speak("Nothing waiting for approval right now.")
            return

        if cmd.intent.name == "DENY":
            from voice.speech_output import get_speech_output
            if _active_approval.get("dlg"):
                _active_approval["result"][0] = False
                QTimer.singleShot(0, _active_approval["dlg"].reject)
                get_speech_output().speak("Denied.")
            else:
                get_speech_output().speak("Nothing waiting for approval right now.")
            return

        if cmd.intent.name == "CANCEL_CURRENT":
            orch.cancel_current()
            return

        if cmd.intent.name == "STATUS_QUERY":
            from voice.speech_output import get_speech_output
            active = orch.active_task()
            recent = orch.recent_tasks(5)

            lines = []
            if active:
                lines.append(f"Currently working on: {active.instruction[:60]}.")
            else:
                lines.append("I'm idle right now.")

            done = [t for t in recent if t.status.value == "completed"]
            if done:
                names = ", ".join(t.instruction[:40] for t in done[:3])
                lines.append(f"Recently completed: {names}.")
            else:
                lines.append("No completed tasks yet.")

            msg = " ".join(lines)
            get_speech_output().speak(msg)
            dashboard.append_log(msg)
            return

        if cmd.intent.name == "GREETING":
            from voice.speech_output import get_speech_output
            reply = "Hello! I'm your AI agent. What would you like me to do?"
            get_speech_output().speak(reply)
            dashboard.append_log(reply)
            avatar.set_state("idle", reply)
            return

        if cmd.intent.name in ("CONVERSATIONAL", "EXPLAIN_ERROR"):
            from voice.speech_output import get_speech_output
            from models.provider import get_provider
            _CONV_SYSTEM = (
                "You are Jarvis, an AI desktop assistant that CAN control the computer — "
                "open apps, click, type, browse the web, read files, send messages, and more.\n\n"
                "IMPORTANT: When the user's message implies performing an action "
                "(open, search, navigate, click, type, find, etc.) — even if phrased as a "
                "question, complaint, or casual request — respond ONLY with:\n"
                "ACTION: <exact task instruction in plain English>\n\n"
                "Examples:\n"
                "  'Back on the other end, search YouTube.' → ACTION: open YouTube\n"
                "  'Why you are not opening the YouTube?' → ACTION: open YouTube\n"
                "  'Can you search Upwork for me?' → ACTION: search Upwork\n"
                "  'You didn't click the link.' → ACTION: click on the Upwork link\n\n"
                "For genuine questions with no action (e.g. 'what time is it?', "
                "'how are you?'), reply normally in 1-2 short sentences."
            )
            try:
                provider = get_provider()
                reply = provider.complete(_CONV_SYSTEM, cmd.text, max_tokens=100)
            except Exception:
                reply = "I'm on it. Let me try that again for you."
            reply = reply.strip()

            # If LLM detected a task, submit it instead of just speaking
            if reply.upper().startswith("ACTION:"):
                task_instruction = reply.split(":", 1)[1].strip().splitlines()[0].strip()
                task = orch.submit(task_instruction)
                short = task_instruction[:60]
                spoken = f"Got it. {short}."
                get_speech_output().speak(spoken)
                dashboard.append_log(f"Task submitted: {task.id[:8]} — {short}")
                avatar.set_state("idle", short)
                return

            get_speech_output().speak(reply)
            dashboard.append_log(f"[Chat] {reply}")
            avatar.set_state("idle", reply[:80])
            return

        if cmd.intent.name == "UNKNOWN":
            from voice.speech_output import get_speech_output
            get_speech_output().speak("Sorry, I didn't catch that. Could you say that again?")
            dashboard.append_log(f"[?] Unclear input: {text[:50]}")
            return

        if cmd.intent.name == "NEW_TASK":
            raw = cmd.task_instruction or text
            instruction = _clean_instruction(raw)
            if instruction != raw:
                log.info("Instruction cleaned: %r → %r", raw[:60], instruction[:60])
            task = orch.submit(instruction)
            short = instruction[:60]
            dashboard.append_log(f"Task submitted: {task.id[:8]} — {short}")
            from voice.speech_output import get_speech_output
            get_speech_output().speak(f"Got it. Working on: {short}")
            return

    avatar.task_submitted.connect(_handle_instruction)
    dashboard.task_submitted.connect(_handle_instruction)
    avatar.show_dashboard_requested.connect(dashboard.show)
    avatar.show_dashboard_requested.connect(dashboard.raise_)

    def _emergency_stop() -> None:
        orch.emergency_stop()
        from voice.speech_output import get_speech_output
        get_speech_output().speak("Emergency stop. All tasks cancelled.")

    avatar.stop_all_requested.connect(_emergency_stop)
    dashboard.stop_all_requested.connect(_emergency_stop)
    dashboard.cancel_current_requested.connect(orch.cancel_current)

    # Thread-safe task progress routing — worker thread enqueues, main thread drains.
    # TTS is triggered HERE (worker thread) so is_speaking() is True before
    # _idle_check can fire on the main thread — eliminates the PTT/TTS race.
    _ui_queue: queue.Queue = queue.Queue()
    _spoken_task_states: dict[str, str] = {}

    def _on_task_update(task) -> None:
        from voice.speech_output import get_speech_output
        cur = task.status.value
        prev = _spoken_task_states.get(task.id)
        if cur != prev:
            _spoken_task_states[task.id] = cur
            if cur == "completed":
                # Only speak step results from content tools (summarize, search, draft).
                # Action tools (hotkey, click, navigate, type) return debug strings like
                # "Hotkey: enter" which should never be spoken aloud.
                _CONTENT_TOOLS = {"summarize", "draft_document", "web_search",
                                   "google_chat_read", "ask_user"}
                spoken = None
                if task.steps:
                    last = task.steps[-1]
                    r = last.result
                    if (last.tool in _CONTENT_TOOLS
                            and isinstance(r, str) and 20 < len(r) < 600):
                        spoken = r
                get_speech_output().speak(spoken or "Task completed.")
            elif cur == "failed":
                err = task.error_message or "unknown error"
                get_speech_output().speak(f"Task failed. {err[:60]}")
            elif cur == "waiting_for_approval":
                get_speech_output().speak("I need your approval to continue.")
            elif cur == "cancelled":
                get_speech_output().speak("Task cancelled.")
        _ui_queue.put(task)

    def _drain_ui_queue() -> None:
        try:
            while True:
                task = _ui_queue.get_nowait()
                avatar.update_from_task(task)
                dashboard.update_task_status(task)
        except queue.Empty:
            pass

    _drain_timer = QTimer()
    _drain_timer.timeout.connect(_drain_ui_queue)
    _drain_timer.start(150)

    orch.add_status_callback(_on_task_update)

    # ── System tray ───────────────────────────────────────────────────────────
    tray = QSystemTrayIcon(_make_tray_icon(), parent=app)
    tray_menu = QMenu()
    tray_menu.addAction("Show Avatar", avatar.show)
    tray_menu.addAction("Open Dashboard", dashboard.show)
    tray_menu.addSeparator()
    tray_menu.addAction("Emergency Stop", _emergency_stop)
    tray_menu.addSeparator()
    tray_menu.addAction("Quit", app.quit)
    tray.setContextMenu(tray_menu)
    tray.setToolTip("AI Desktop Agent")
    tray.show()

    # ── Start orchestrator worker ─────────────────────────────────────────────
    orch.start()

    # ── Show UI ───────────────────────────────────────────────────────────────
    avatar.show()
    log.info("AI Desktop Agent started")

    # ── First-run check ───────────────────────────────────────────────────────
    from storage.repositories import pref_repo
    if not pref_repo.get("first_run_complete", False):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(parent=dashboard)
        dlg.setWindowTitle("Welcome — First-Run Setup")
        dlg.exec()
        pref_repo.set("first_run_complete", True)

    ret = app.exec()

    # ── Shutdown ──────────────────────────────────────────────────────────────
    orch.stop()
    from browser.manager import get_browser_manager
    try:
        get_browser_manager().close()
    except Exception:
        pass
    sys.exit(ret)


if __name__ == "__main__":
    main()
