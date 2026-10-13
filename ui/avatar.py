"""
Two floating windows matching the Voice AI Assistant Desktop Mockup:

  1. _OrbWindow   — Large glowing orb (180 px) + speech bubble, center-screen
  2. FloatingAvatar — Small dark control panel (top-left): status, PTT, text, wake-word

FloatingAvatar owns _OrbWindow; calling show()/hide() on FloatingAvatar
automatically shows/hides both, so app.py needs no changes.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QTimer, QSettings, Signal
from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QRadialGradient,
    QLinearGradient, QPainterPath, QFont,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMenu, QApplication, QSizePolicy,
)

log = logging.getLogger(__name__)

ORB_SIZE = 180

STATE_COLORS: dict[str, str] = {
    "idle":                 "#3a7bd5",
    "listening":            "#00c853",
    "thinking":             "#ff8f00",
    "working":              "#7c4dff",
    "waiting_for_approval": "#ff6d00",
    "speaking":             "#00bcd4",
    "paused":               "#546e7a",
    "error":                "#f44336",
}

STATE_LABELS: dict[str, str] = {
    "idle":                 "Idle",
    "listening":            "Listening...",
    "thinking":             "Thinking...",
    "working":              "Running",
    "waiting_for_approval": "Needs Approval",
    "speaking":             "Speaking...",
    "paused":               "Paused",
    "error":                "Error",
}


# ══════════════════════════════════════════════════════════════════════════════
# Shared visual primitives
# ══════════════════════════════════════════════════════════════════════════════

class OrbWidget(QWidget):
    """180 px animated glowing orb with a cute face."""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(ORB_SIZE, ORB_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._state = "idle"
        self._pulse = 0.0
        self._pulse_dir = 1.0
        self._blink = False

        QTimer(self).timeout.connect(self._tick) or None
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(30)

        b = QTimer(self)
        b.timeout.connect(self._blink_once)
        b.start(4000)

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def _tick(self) -> None:
        speed = 0.02 if self._state == "idle" else 0.06
        self._pulse += speed * self._pulse_dir
        if self._pulse >= 1.0:
            self._pulse_dir = -1.0
        elif self._pulse <= 0.0:
            self._pulse_dir = 1.0
        self.update()

    def _blink_once(self) -> None:
        self._blink = True
        self.update()
        QTimer.singleShot(110, self._unblink)

    def _unblink(self) -> None:
        self._blink = False
        self.update()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        base = QColor(STATE_COLORS.get(self._state, "#3a7bd5"))
        cx = cy = ORB_SIZE // 2
        r = ORB_SIZE // 2 - 8

        # Atmospheric glow (3 rings)
        for i in range(3):
            gr = int(r + 12 + i * 10 + self._pulse * 14)
            alpha = int((60 - i * 18) + self._pulse * 22)
            g = QRadialGradient(cx, cy, gr)
            gc = QColor(base)
            gc.setAlpha(max(0, alpha))
            g.setColorAt(0.0, gc)
            g.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(g))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(cx - gr, cy - gr, gr * 2, gr * 2)

        # 3-D sphere
        sg = QRadialGradient(cx - r * 0.28, cy - r * 0.28, r * 1.15)
        light = base.lighter(180)
        light.setAlpha(255)
        sg.setColorAt(0.0, light)
        sg.setColorAt(0.45, base)
        dark = base.darker(165)
        dark.setAlpha(255)
        sg.setColorAt(1.0, dark)
        p.setBrush(QBrush(sg))
        p.setPen(QPen(base.lighter(130), 1.5))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # Specular highlight
        hg = QRadialGradient(cx - r * 0.32, cy - r * 0.38, r * 0.46)
        hg.setColorAt(0, QColor(255, 255, 255, 95))
        hg.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # Face — eyes
        p.setBrush(QColor(255, 255, 255, 245))
        eye_y = cy - 12
        eye_r = 7
        if self._blink:
            pen = QPen(QColor(255, 255, 255, 245), 4.5,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(cx - 24, eye_y + eye_r, cx - 10, eye_y + eye_r)
            p.drawLine(cx + 10, eye_y + eye_r, cx + 24, eye_y + eye_r)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(cx - 24, eye_y, eye_r * 2, eye_r * 2)
            p.drawEllipse(cx + 10, eye_y, eye_r * 2, eye_r * 2)

        # Face — mouth
        pen = QPen(QColor(255, 255, 255, 230), 4,
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        mouth = QRect(cx - 18, cy + 6, 36, 22)
        p.drawArc(mouth, 0, (-180 if self._state != "error" else 180) * 16)


class _SpeechBubble(QWidget):
    """White rounded bubble with left-pointing tail — sits right of the orb."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self.setMinimumSize(180, 100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_text(self, text: str) -> None:
        self._text = text
        self.update()

    def paintEvent(self, _) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        tail = 14
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(QRectF(tail, 4, w - tail - 4, h - 8), 14, 14)

        mid_y = h // 2
        path.moveTo(tail, mid_y - 9)
        path.lineTo(0, mid_y)
        path.lineTo(tail, mid_y + 9)

        p.fillPath(path, QBrush(QColor(255, 255, 255, 240)))
        p.setPen(QPen(QColor(200, 210, 230, 180), 1))
        p.drawPath(path)

        p.setPen(QPen(QColor(40, 50, 70, 230)))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(
            QRectF(tail + 14, 14, w - tail - 28, h - 28),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            | Qt.TextFlag.TextWordWrap,
            self._text,
        )


class _Chip(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__("● Idle", parent)
        self._apply("idle")

    def _apply(self, state: str) -> None:
        c = QColor(STATE_COLORS.get(state, "#888888"))
        r, g, b = c.red(), c.green(), c.blue()
        label = STATE_LABELS.get(state, state.replace("_", " ").title())
        self.setText(f"● {label}")
        self.setStyleSheet(
            f"color:rgba({r},{g},{b},230);"
            f"background:rgba({r},{g},{b},30);"
            "border-radius:9px;padding:2px 9px;"
            "font-size:10px;font-weight:700;"
        )

    def update_state(self, state: str) -> None:
        self._apply(state)


class _Toggle(QWidget):
    toggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(36, 20)
        self._on = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def is_on(self) -> bool:
        return self._on

    def mousePressEvent(self, _) -> None:  # noqa: N802
        self._on = not self._on
        self.update()
        self.toggled.emit(self._on)

    def paintEvent(self, _) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        track = QColor("#3a7bd5") if self._on else QColor(70, 75, 90)
        p.setBrush(track)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 4, w, h - 8, (h - 8) // 2, (h - 8) // 2)
        tx = w - h + 2 if self._on else 2
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawEllipse(tx, 2, h - 4, h - 4)


# ══════════════════════════════════════════════════════════════════════════════
# Window 1 — Large floating orb (center of screen)
# ══════════════════════════════════════════════════════════════════════════════

class _OrbWindow(QWidget):
    """Frameless transparent window: big orb on the left, speech bubble right."""

    # relay drag saves to settings under "orb/"
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drag: QPoint | None = None
        self._settings = QSettings("DevsloopTech", "DesktopAIAgent")
        self._setup_window()
        self._setup_ui()
        self._restore_pos()

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(ORB_SIZE + 230, ORB_SIZE + 30)

    def _setup_ui(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self._orb = OrbWidget()
        row.addWidget(self._orb, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._bubble = _SpeechBubble("Hey! I'm your voice agent.\nHow can I help you today?")
        row.addWidget(self._bubble, stretch=1)

    # ── State ─────────────────────────────────────────────────────────────────

    def set_state(self, state: str, message: str = "") -> None:
        self._orb.set_state(state)
        if message:
            self._bubble.set_text(message)

    # ── Drag ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag and ev.buttons() == Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _) -> None:  # noqa: N802
        self._drag = None
        self._settings.setValue("orb/pos", self.pos())

    def paintEvent(self, _) -> None:  # noqa: N802
        pass  # fully transparent container

    def _restore_pos(self) -> None:
        pos = self._settings.value("orb/pos")
        screen = QApplication.primaryScreen().availableGeometry()
        if pos:
            x = max(0, min(pos.x(), screen.width() - self.width()))
            y = max(0, min(pos.y(), screen.height() - self.height()))
            self.move(x, y)
        else:
            # Center of screen by default
            self.move(
                (screen.width() - self.width()) // 2,
                (screen.height() - self.height()) // 2 - 60,
            )


# ══════════════════════════════════════════════════════════════════════════════
# Window 2 — Small control panel (top-left)
# ══════════════════════════════════════════════════════════════════════════════

class FloatingAvatar(QWidget):
    """Small dark control panel — also owns the large _OrbWindow."""

    show_dashboard_requested = Signal()
    task_submitted = Signal(str)
    stop_all_requested = Signal()
    _ptt_done = Signal(str)   # internal: carries transcription result to main thread

    _PANEL_W = 190
    _PANEL_H = 150

    def __init__(self) -> None:
        super().__init__()
        self._drag: QPoint | None = None
        self._settings = QSettings("DevsloopTech", "DesktopAIAgent")
        self._state = "idle"
        self._ptt_auto_restart = False

        # Create the orb window
        self._orb_win = _OrbWindow()

        self._setup_window()
        self._setup_ui()
        self._restore_pos()
        self._start_refresh()

        # Wire internal PTT signal — guaranteed main-thread delivery from any thread
        self._ptt_done.connect(self._on_ptt_done)

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self._PANEL_W, self._PANEL_H)

    # ── UI ───────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(7)

        # ── Header: dot + title + chip ────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(5)

        dot = QLabel("●")
        dot.setStyleSheet("color:#3a7bd5;font-size:10px;background:transparent;")
        title = QLabel("Voice Agent")
        title.setStyleSheet(
            "color:rgba(255,255,255,215);font-size:11px;font-weight:700;"
            "background:transparent;"
        )
        hdr.addWidget(dot)
        hdr.addWidget(title)
        hdr.addStretch()

        self._chip = _Chip()
        hdr.addWidget(self._chip)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setToolTip("Quit")
        close_btn.setStyleSheet(
            "QPushButton{background:rgba(220,48,48,0);color:rgba(255,255,255,120);"
            "border:none;border-radius:4px;font-size:11px;font-weight:700;}"
            "QPushButton:hover{background:rgba(220,48,48,200);color:white;}"
        )
        close_btn.clicked.connect(QApplication.quit)
        hdr.addWidget(close_btn)
        col.addLayout(hdr)

        # ── Push to Talk ──────────────────────────────────────────────────────
        self._ptt_btn = QPushButton("🎤  Push to talk")
        self._ptt_btn.setFixedHeight(30)
        self._ptt_btn.setStyleSheet(
            "QPushButton{background:rgba(40,48,72,200);color:rgba(255,255,255,210);"
            "border:1px solid rgba(255,255,255,20);border-radius:7px;"
            "font-size:11px;font-weight:600;padding:0 10px;text-align:left;}"
            "QPushButton:hover{background:rgba(58,123,213,160);}"
            "QPushButton:disabled{color:rgba(255,255,255,80);}"
        )
        self._ptt_btn.clicked.connect(self._ptt_clicked)
        col.addWidget(self._ptt_btn)

        # ── Submit / text input ───────────────────────────────────────────────
        self._input = QLineEdit()
        self._input.setPlaceholderText("Submit…")
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(
            "QLineEdit{background:rgba(40,48,72,200);color:white;"
            "border:1px solid rgba(255,255,255,20);border-radius:7px;"
            "padding:0 9px;font-size:11px;}"
            "QLineEdit:focus{border:1px solid rgba(58,123,213,180);}"
        )
        self._input.returnPressed.connect(self._submit)
        col.addWidget(self._input)

        # ── Wake word row ─────────────────────────────────────────────────────
        wake_row = QHBoxLayout()
        wake_row.setSpacing(6)
        wake_lbl = QLabel("Wake word")
        wake_lbl.setStyleSheet(
            "color:rgba(255,255,255,120);font-size:10px;background:transparent;"
        )
        self._wake = _Toggle()
        self._wake.toggled.connect(self._on_wake_toggle)
        wake_row.addWidget(wake_lbl)
        wake_row.addStretch()
        wake_row.addWidget(self._wake)
        col.addLayout(wake_row)

    # ── show / hide — proxy to orb window too ────────────────────────────────

    def show(self) -> None:
        super().show()
        self._orb_win.show()

    def hide(self) -> None:
        super().hide()
        self._orb_win.hide()

    # ── Paint — dark rounded pill ─────────────────────────────────────────────

    def paintEvent(self, _) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(1, 1, self.width() - 2, self.height() - 2, 14, 14)

        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0, QColor(20, 25, 42, 242))
        bg.setColorAt(1, QColor(12, 16, 30, 248))
        p.fillPath(path, QBrush(bg))

        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        p.drawPath(path)

        # top glare
        glare = QLinearGradient(0, 0, self.width(), 0)
        glare.setColorAt(0.0, QColor(255, 255, 255, 0))
        glare.setColorAt(0.5, QColor(255, 255, 255, 28))
        glare.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(QPen(QBrush(glare), 1))
        p.drawLine(16, 2, self.width() - 16, 2)

    # ── Drag ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag and ev.buttons() == Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _) -> None:  # noqa: N802
        self._drag = None
        self._settings.setValue("panel/pos", self.pos())

    def _restore_pos(self) -> None:
        pos = self._settings.value("panel/pos")
        screen = QApplication.primaryScreen().availableGeometry()
        if pos:
            x = max(0, min(pos.x(), screen.width() - self.width()))
            y = max(0, min(pos.y(), screen.height() - self.height()))
            self.move(x, y)
        else:
            self.move(20, 30)  # top-left like the mockup

    # ── State API ─────────────────────────────────────────────────────────────

    def set_state(self, state: str, message: str = "") -> None:
        self._state = state
        self._chip.update_state(state)
        self._orb_win.set_state(state, message)

    def update_from_task(self, task) -> None:
        state_map = {
            "queued":                "idle",
            "planning":              "thinking",
            "running":               "working",
            "waiting_for_approval":  "waiting_for_approval",
            "waiting_for_input":     "waiting_for_approval",
            "verifying":             "thinking",
            "completed":             "idle",
            "failed":                "error",
            "cancelled":             "idle",
        }
        ui_state = state_map.get(task.status.value, "working")
        step = task.current_step_obj()
        msg = step.description[:80] if step else task.instruction[:80]
        self.set_state(ui_state, msg)

        # Hide the panel during active execution so it does not appear in screenshots
        # taken by screen_read, preventing the agent from trying to close its own UI.
        _EXEC_STATES = {"planning", "running", "verifying"}
        _DONE_STATES = {"completed", "failed", "cancelled", "waiting_for_approval"}
        if task.status.value in _EXEC_STATES:
            if self.isVisible():
                self.setVisible(False)
                self._orb_win.setVisible(False)
        elif task.status.value in _DONE_STATES:
            if not self.isVisible():
                self.setVisible(True)
                self._orb_win.setVisible(True)

        if task.status.value == "completed":
            self._orb_win._bubble.set_text("Task done!\nWhat's next?")
        elif task.status.value == "failed":
            self._orb_win._bubble.set_text(
                f"Something went wrong.\n{(task.error_message or '')[:60]}"
            )

    # ── Voice ─────────────────────────────────────────────────────────────────

    def _ptt_clicked(self) -> None:
        from voice.input import get_voice_input
        vi = get_voice_input()

        if not vi.is_available():
            self._orb_win._bubble.set_text(
                "Microphone not available.\nType your task below."
            )
            return

        self._ptt_btn.setEnabled(False)
        self._ptt_btn.setText("🔴  Listening…")
        self.set_state("listening", "Speak now — I'll stop when you go quiet.")

        import threading

        def _go():
            try:
                # 0.008 threshold captures quiet microphones; Whisper VAD will
                # still filter out background noise in the recorded audio.
                text = vi.listen_and_transcribe(silence_threshold=0.010)
            except Exception as exc:
                log.warning("PTT error: %s", exc)
                text = ""
            # Emit signal — Qt delivers this on the main thread regardless of which
            # thread emits it (AutoConnection crosses thread boundaries safely)
            self._ptt_done.emit(text)

        threading.Thread(target=_go, daemon=True, name="PTTRecord").start()

    def _on_ptt_done(self, text: str) -> None:
        """Always runs on the main thread — safe to touch any widget here."""
        self._ptt_btn.setEnabled(True)
        self._ptt_btn.setText("🎤  Push to talk")
        self._ptt_btn.repaint()

        if text:
            log.info("PTT result: %r", text[:80])
            self._orb_win._bubble.set_text(text[:120])
            self.set_state("working", text[:80])
            self.task_submitted.emit(text)
            # Auto-restart only after agent is idle (checked by poll timer)
            self._ptt_auto_restart = True
        else:
            self.set_state("idle")
            self._orb_win._bubble.set_text(
                "I didn't catch that.\nTry speaking again."
            )
            # Wait before retrying so the user has time to prepare to speak
            QTimer.singleShot(1500, self._ptt_clicked)

    def _submit(self) -> None:
        text = self._input.text().strip()
        if text:
            self._input.clear()
            self.task_submitted.emit(text)

    def _on_wake_toggle(self, on: bool) -> None:
        try:
            from voice.input import get_voice_input
            vi = get_voice_input()
            if on and vi.is_available():
                vi.set_callback(lambda t: self.task_submitted.emit(t) if t else None)
                vi.start_listening()
            else:
                vi.stop_listening()
        except Exception as exc:
            log.warning("Wake word toggle: %s", exc)

    # ── Context menu (right-click) ─────────────────────────────────────────────

    def contextMenuEvent(self, ev) -> None:  # noqa: N802
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#161c2e;color:white;"
            "border:1px solid rgba(255,255,255,18);border-radius:8px;padding:4px;}"
            "QMenu::item{padding:6px 18px;border-radius:5px;}"
            "QMenu::item:selected{background:rgba(58,123,213,140);}"
        )
        menu.addAction("Open Dashboard", self.show_dashboard_requested)
        menu.addSeparator()
        menu.addAction("Emergency Stop", self.stop_all_requested)
        menu.addSeparator()
        menu.addAction("Quit", QApplication.quit)
        menu.exec(ev.globalPos())

    # ── Auto-refresh ──────────────────────────────────────────────────────────

    def _start_refresh(self) -> None:
        t = QTimer(self)
        t.timeout.connect(self._idle_check)
        t.start(1500)

    def _idle_check(self) -> None:
        try:
            from agent.orchestrator import get_orchestrator
            from voice.speech_output import get_speech_output
            orch = get_orchestrator()
            active = orch.active_task()
            tts_busy = get_speech_output().is_speaking()

            # TaskQueue never clears self._active — check task status directly.
            # "waiting_for_approval" is included so PTT restarts and the user can
            # say "yes" / "no" to approve via voice (wired in app.py).
            _DONE = {"completed", "failed", "cancelled", "waiting_for_approval"}
            task_running = (
                active is not None
                and active.status.value not in _DONE
            )

            if not task_running and not tts_busy:
                if self._state not in ("listening", "idle"):
                    self.set_state("idle")
                    self._orb_win._bubble.set_text(
                        "Hey! I'm your voice agent.\nHow can I help you today?"
                    )
                if self._ptt_auto_restart and self._ptt_btn.isEnabled():
                    self._ptt_auto_restart = False
                    self._ptt_clicked()
        except Exception:
            pass
