"""Task list panel shown in the dashboard."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QGroupBox, QProgressBar
)

from agent.task_state import Task, TaskStatus

STATUS_COLORS = {
    TaskStatus.QUEUED: "#888888",
    TaskStatus.PLANNING: "#4488ff",
    TaskStatus.RUNNING: "#22aa44",
    TaskStatus.WAITING_FOR_APPROVAL: "#ff8800",
    TaskStatus.WAITING_FOR_INPUT: "#ff8800",
    TaskStatus.VERIFYING: "#44aaff",
    TaskStatus.COMPLETED: "#22cc66",
    TaskStatus.FAILED: "#cc2200",
    TaskStatus.CANCELLED: "#888888",
}


class TaskPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Active task
        active_box = QGroupBox("Active Task")
        active_layout = QVBoxLayout(active_box)
        self._active_label = QLabel("Idle")
        self._active_label.setWordWrap(True)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        active_layout.addWidget(self._active_label)
        active_layout.addWidget(self._progress)
        layout.addWidget(active_box)

        # Queued
        queue_box = QGroupBox("Queued")
        queue_layout = QVBoxLayout(queue_box)
        self._queue_list = QListWidget()
        self._queue_list.setMaximumHeight(100)
        queue_layout.addWidget(self._queue_list)
        layout.addWidget(queue_box)

        # Recent
        recent_box = QGroupBox("Recent Tasks")
        recent_layout = QVBoxLayout(recent_box)
        self._recent_list = QListWidget()
        self._recent_list.setMaximumHeight(150)
        recent_layout.addWidget(self._recent_list)
        layout.addWidget(recent_box)

        layout.addStretch()

    def update_active(self, task: Task | None) -> None:
        if task is None:
            self._active_label.setText("Idle")
            self._active_label.setStyleSheet("")
            self._progress.setValue(0)
            return
        color = STATUS_COLORS.get(task.status, "#888")
        self._active_label.setText(
            f'<span style="color:{color}">● {task.status.value.upper()}</span>  '
            f'{task.instruction[:80]}'
        )
        self._progress.setValue(task.progress_pct())

    def update_queue(self, tasks: list[Task]) -> None:
        self._queue_list.clear()
        for t in tasks:
            item = QListWidgetItem(f"[{t.status.value}] {t.instruction[:60]}")
            self._queue_list.addItem(item)

    def update_recent(self, tasks: list[Task]) -> None:
        self._recent_list.clear()
        for t in tasks[:20]:
            color = STATUS_COLORS.get(t.status, "#888")
            item = QListWidgetItem(f"[{t.status.value}] {t.instruction[:60]}")
            item.setForeground(QColor(color))
            self._recent_list.addItem(item)
