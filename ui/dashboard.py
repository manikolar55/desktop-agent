"""Dark sidebar dashboard — matches the Voice AI Assistant mockup."""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QLinearGradient,
    QPainterPath, QFont
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QFrame, QSizePolicy, QApplication
)

from agent.task_state import Task, TaskStatus

log = logging.getLogger(__name__)

# ── Palette ───────────────────────────────────────────────────────────────────
BG_DARK   = QColor(14, 17, 28)
BG_CARD   = QColor(22, 27, 44)
BG_INPUT  = QColor(30, 36, 55)
BORDER    = QColor(255, 255, 255, 20)
TEXT_PRI  = QColor(255, 255, 255, 230)
TEXT_SEC  = QColor(255, 255, 255, 120)
ACCENT    = QColor(58, 123, 213)
SUCCESS   = QColor(34, 170, 68)
DANGER    = QColor(220, 48, 48)
WARN      = QColor(255, 140, 0)

STATUS_COLOR: dict[str, QColor] = {
    "queued":                QColor(128, 128, 128),
    "planning":              QColor(68, 136, 255),
    "running":               SUCCESS,
    "waiting_for_approval":  WARN,
    "waiting_for_input":     WARN,
    "verifying":             QColor(68, 170, 255),
    "completed":             SUCCESS,
    "failed":                DANGER,
    "cancelled":             QColor(128, 128, 128),
}


def _card_style() -> str:
    return (
        "background:rgba(22,27,44,255);"
        "border:1px solid rgba(255,255,255,18);"
        "border-radius:10px;"
    )


def _label(text: str, size: int = 11, bold: bool = False,
           color: QColor = TEXT_PRI, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    weight = "700" if bold else "400"
    r, g, b, a = color.red(), color.green(), color.blue(), color.alpha()
    lbl.setStyleSheet(
        f"color:rgba({r},{g},{b},{a});font-size:{size}px;font-weight:{weight};"
        "background:transparent;border:none;"
    )
    lbl.setWordWrap(wrap)
    return lbl


# ── Reusable card container ───────────────────────────────────────────────────

class _Card(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 10, 10)
        p.fillPath(path, QBrush(BG_CARD))
        p.setPen(QPen(BORDER, 1))
        p.drawPath(path)


# ── Transcript entry ──────────────────────────────────────────────────────────

class _TranscriptEntry(QWidget):
    def __init__(self, role: str, text: str, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(6)

        ts = datetime.now().strftime("%H:%M")
        ts_lbl = _label(ts, size=9, color=TEXT_SEC)
        ts_lbl.setFixedWidth(32)
        row.addWidget(ts_lbl)

        if role == "agent":
            icon = _label("⬡", size=11, color=ACCENT)
        else:
            icon = _label("▸", size=11, color=TEXT_SEC)
        icon.setFixedWidth(14)
        row.addWidget(icon)

        msg = _label(text[:200], size=10, color=TEXT_PRI if role == "agent" else TEXT_SEC, wrap=True)
        row.addWidget(msg, stretch=1)


# ── Status chip ───────────────────────────────────────────────────────────────

class _StatusChip(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__("● Idle", parent)
        self._set("idle")

    def _set(self, status: str) -> None:
        color = STATUS_COLOR.get(status, QColor(128, 128, 128))
        r, g, b = color.red(), color.green(), color.blue()
        label = status.replace("_", " ").title()
        self.setText(f"● {label}")
        self.setStyleSheet(
            f"color:rgba({r},{g},{b},230);"
            f"background:rgba({r},{g},{b},22);"
            "border-radius:10px;padding:2px 10px;"
            "font-size:11px;font-weight:700;"
        )

    def update_status(self, status: str) -> None:
        self._set(status)


# ── Current task section ──────────────────────────────────────────────────────

class _CurrentTaskSection(_Card):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.addWidget(_label("Current Task", size=10, bold=True, color=TEXT_SEC))
        hdr.addStretch()
        self._step_lbl = _label("Step — / —", size=10, color=TEXT_SEC)
        hdr.addWidget(self._step_lbl)
        col.addLayout(hdr)

        self._task_name = _label("No active task", size=12, bold=True, wrap=True)
        col.addWidget(self._task_name)

        # Progress bar — drawn manually
        self._progress_bar = _ProgressBar()
        self._progress_bar.setFixedHeight(6)
        col.addWidget(self._progress_bar)

        self._output_label = _label("", size=10, color=TEXT_SEC, wrap=True)
        col.addWidget(self._output_label)

    def update_task(self, task: Task | None) -> None:
        if task is None:
            self._task_name.setText("No active task")
            self._step_lbl.setText("Step — / —")
            self._progress_bar.set_value(0)
            self._output_label.setText("")
            return

        total = len(task.steps)
        current = task.current_step + 1 if task.steps else 0
        self._step_lbl.setText(f"Step {current} / {total}" if total else "Step — / —")
        self._task_name.setText(task.instruction[:80])
        self._progress_bar.set_value(task.progress_pct())

        step = task.current_step_obj()
        if step and step.description:
            self._output_label.setText(step.description[:120])
        elif task.error_message:
            self._output_label.setText(f"Error: {task.error_message[:100]}")
        else:
            self._output_label.setText("")


class _ProgressBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._value = 0

    def set_value(self, v: int) -> None:
        self._value = max(0, min(100, v))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()

        # Track
        p.setBrush(QBrush(QColor(255, 255, 255, 25)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 3, 3)

        # Fill
        if self._value > 0:
            fill_w = int(r.width() * self._value / 100)
            grad = QLinearGradient(0, 0, fill_w, 0)
            grad.setColorAt(0, ACCENT)
            grad.setColorAt(1, QColor(100, 180, 255))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(0, 0, fill_w, r.height(), 3, 3)


# ── Approval banner ───────────────────────────────────────────────────────────

class _ApprovalSection(_Card):
    approve_clicked = Signal()
    deny_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(8)

        hdr = QHBoxLayout()
        warn_icon = _label("⚠", size=13, color=WARN)
        hdr.addWidget(warn_icon)
        hdr.addWidget(_label("Approval Required", size=11, bold=True, color=WARN))
        hdr.addStretch()
        col.addLayout(hdr)

        self._desc_label = _label("", size=10, color=TEXT_PRI, wrap=True)
        col.addWidget(self._desc_label)

        btn_row = QHBoxLayout()
        self._approve_btn = QPushButton("Approve")
        self._approve_btn.setFixedHeight(30)
        self._approve_btn.setStyleSheet(
            "QPushButton{background:rgba(34,170,68,180);color:white;border:none;"
            "border-radius:6px;font-size:11px;font-weight:700;}"
            "QPushButton:hover{background:rgba(34,170,68,255);}"
        )
        self._approve_btn.clicked.connect(self.approve_clicked)

        self._deny_btn = QPushButton("Deny")
        self._deny_btn.setFixedHeight(30)
        self._deny_btn.setStyleSheet(
            "QPushButton{background:rgba(220,48,48,150);color:white;border:none;"
            "border-radius:6px;font-size:11px;font-weight:700;}"
            "QPushButton:hover{background:rgba(220,48,48,230);}"
        )
        self._deny_btn.clicked.connect(self.deny_clicked)

        btn_row.addWidget(self._approve_btn)
        btn_row.addWidget(self._deny_btn)
        col.addLayout(btn_row)

    def set_description(self, text: str) -> None:
        self._desc_label.setText(text[:200])


# ── Live transcript ───────────────────────────────────────────────────────────

class _TranscriptSection(_Card):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(4)

        col.addWidget(_label("Live Transcript", size=10, bold=True, color=TEXT_SEC))

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background:transparent;border:none;")
        self._scroll.setMinimumHeight(120)
        self._scroll.setMaximumHeight(200)

        self._inner = QWidget()
        self._inner.setStyleSheet("background:transparent;")
        self._inner_col = QVBoxLayout(self._inner)
        self._inner_col.setContentsMargins(0, 0, 4, 0)
        self._inner_col.setSpacing(0)
        self._inner_col.addStretch()

        self._scroll.setWidget(self._inner)
        col.addWidget(self._scroll)

    def add_entry(self, role: str, text: str) -> None:
        entry = _TranscriptEntry(role, text, self._inner)
        self._inner_col.addWidget(entry)
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        sb = self._scroll.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())


# ── Bottom action bar ─────────────────────────────────────────────────────────

class _ActionBar(QWidget):
    open_project_clicked = Signal()
    terminal_clicked = Signal()
    chat_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        def _btn(label: str, tooltip: str, danger: bool = False) -> QPushButton:
            b = QPushButton(label)
            b.setFixedHeight(32)
            b.setToolTip(tooltip)
            if danger:
                b.setStyleSheet(
                    "QPushButton{background:rgba(220,48,48,140);color:white;border:none;"
                    "border-radius:7px;font-size:10px;font-weight:600;padding:0 8px;}"
                    "QPushButton:hover{background:rgba(220,48,48,220);}"
                )
            else:
                b.setStyleSheet(
                    "QPushButton{background:rgba(58,123,213,110);color:white;border:none;"
                    "border-radius:7px;font-size:10px;font-weight:600;padding:0 8px;}"
                    "QPushButton:hover{background:rgba(58,123,213,200);}"
                )
            return b

        self._proj_btn = _btn("⬡ Project", "Open project folder")
        self._proj_btn.clicked.connect(self.open_project_clicked)

        self._term_btn = _btn("⌨ Terminal", "Open terminal")
        self._term_btn.clicked.connect(self.terminal_clicked)

        self._chat_btn = _btn("✉ Chat", "Open Google Chat")
        self._chat_btn.clicked.connect(self.chat_clicked)

        self._stop_btn = _btn("■ Stop", "Emergency stop", danger=True)
        self._stop_btn.clicked.connect(self.stop_clicked)

        row.addWidget(self._proj_btn, stretch=1)
        row.addWidget(self._term_btn, stretch=1)
        row.addWidget(self._chat_btn, stretch=1)
        row.addWidget(self._stop_btn, stretch=1)


# ── Main Dashboard window ─────────────────────────────────────────────────────

class Dashboard(QWidget):
    task_submitted = Signal(str)
    stop_all_requested = Signal()
    cancel_current_requested = Signal()
    approve_requested = Signal()
    deny_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Desktop Agent")
        self.setMinimumSize(380, 680)
        self.resize(400, 720)
        self._setup_window()
        self._setup_ui()
        self._start_refresh_timer()

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 14, 14)
        bg_grad = QLinearGradient(0, 0, 0, self.height())
        bg_grad.setColorAt(0, QColor(14, 17, 28, 245))
        bg_grad.setColorAt(1, QColor(10, 12, 22, 252))
        p.fillPath(path, QBrush(bg_grad))
        p.setPen(QPen(BORDER, 1))
        p.drawPath(path)

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = _label("AI Desktop Agent", size=14, bold=True)
        hdr.addWidget(title)
        hdr.addStretch()
        self._status_chip = _StatusChip()
        hdr.addWidget(self._status_chip)
        outer.addLayout(hdr)

        # ── Input ─────────────────────────────────────────────────────────────
        input_card = _Card()
        input_col = QVBoxLayout(input_card)
        input_col.setContentsMargins(10, 8, 10, 8)
        input_col.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a task or question…")
        self._input.setFixedHeight(32)
        self._input.setStyleSheet(
            "QLineEdit{background:rgba(30,36,55,255);color:white;"
            "border:1px solid rgba(255,255,255,25);border-radius:7px;"
            "padding:0 10px;font-size:12px;}"
            "QLineEdit:focus{border:1px solid rgba(58,123,213,180);}"
        )
        self._input.returnPressed.connect(self._submit)

        send_btn = QPushButton("Send")
        send_btn.setFixedSize(60, 32)
        send_btn.setStyleSheet(
            "QPushButton{background:rgba(58,123,213,200);color:white;border:none;"
            "border-radius:7px;font-size:11px;font-weight:700;}"
            "QPushButton:hover{background:rgba(58,123,213,255);}"
        )
        send_btn.clicked.connect(self._submit)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self._input, stretch=1)
        row.addWidget(send_btn)
        input_col.addLayout(row)
        outer.addWidget(input_card)

        # ── Current task ──────────────────────────────────────────────────────
        self._task_section = _CurrentTaskSection()
        outer.addWidget(self._task_section)

        # ── Approval (hidden by default) ──────────────────────────────────────
        self._approval_section = _ApprovalSection()
        self._approval_section.setVisible(False)
        self._approval_section.approve_clicked.connect(self.approve_requested)
        self._approval_section.deny_clicked.connect(self.deny_requested)
        outer.addWidget(self._approval_section)

        # ── Live transcript ───────────────────────────────────────────────────
        self._transcript = _TranscriptSection()
        outer.addWidget(self._transcript, stretch=1)

        # ── Resource indicator ────────────────────────────────────────────────
        res_row = QHBoxLayout()
        self._res_label = _label("CPU —%  RAM —MB", size=9, color=TEXT_SEC)
        res_row.addStretch()
        res_row.addWidget(self._res_label)
        outer.addLayout(res_row)

        # ── Action bar ────────────────────────────────────────────────────────
        self._action_bar = _ActionBar()
        self._action_bar.stop_clicked.connect(self.stop_all_requested)
        self._action_bar.open_project_clicked.connect(self._open_project)
        self._action_bar.terminal_clicked.connect(self._open_terminal)
        self._action_bar.chat_clicked.connect(self._open_chat)
        outer.addWidget(self._action_bar)

    # ── Internal handlers ─────────────────────────────────────────────────────

    def _submit(self) -> None:
        text = self._input.text().strip()
        if text:
            self._input.clear()
            self._transcript.add_entry("user", text)
            self.task_submitted.emit(text)

    def _open_project(self) -> None:
        import subprocess, os
        try:
            from storage.repositories import pref_repo
            projects = pref_repo.get("project_registry", [])
            if projects:
                path = projects[0].get("repository_path", ".")
                os.startfile(path)
        except Exception:
            pass

    def _open_terminal(self) -> None:
        import subprocess
        subprocess.Popen(["cmd.exe", "/k", "echo AI Desktop Agent Terminal"])

    def _open_chat(self) -> None:
        import webbrowser
        webbrowser.open("https://chat.google.com")

    # ── Public API (called from main thread via queue drain) ──────────────────

    def update_task_status(self, task: Task) -> None:
        self._task_section.update_task(task)
        self._status_chip.update_status(task.status.value)

        waiting = task.status in (
            TaskStatus.WAITING_FOR_APPROVAL, TaskStatus.WAITING_FOR_INPUT
        )
        self._approval_section.setVisible(waiting)
        if waiting and task.steps:
            step = task.current_step_obj()
            desc = step.description if step else task.instruction
            self._approval_section.set_description(desc)

    def append_log(self, text: str) -> None:
        self._transcript.add_entry("agent", text)

    # ── Refresh timer ─────────────────────────────────────────────────────────

    def _start_refresh_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

    def _refresh(self) -> None:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().used // (1024 * 1024)
            self._res_label.setText(f"CPU {cpu:.0f}%  RAM {mem}MB")
        except ImportError:
            self._res_label.setText("")
        except Exception:
            pass

        try:
            from agent.orchestrator import get_orchestrator
            orch = get_orchestrator()
            active = orch.active_task()
            if active is None:
                self._task_section.update_task(None)
                self._status_chip.update_status("idle")
                self._approval_section.setVisible(False)
        except Exception:
            pass
