"""Modal approval dialog for high-risk actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit
)


class ApprovalDialog(QDialog):
    def __init__(self, task_id: str, action: str, description: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Action Approval Required")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(480)
        self._approved = False

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel("The agent is requesting approval for a significant action.")
        header.setWordWrap(True)
        header.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(header)

        action_label = QLabel(f"Action: <b>{action}</b>")
        layout.addWidget(action_label)

        desc_box = QTextEdit()
        desc_box.setPlainText(description)
        desc_box.setReadOnly(True)
        desc_box.setFixedHeight(100)
        layout.addWidget(desc_box)

        task_label = QLabel(f"Task ID: {task_id[:8]}...")
        task_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(task_label)

        warning = QLabel("Review carefully. This action may be irreversible or externally visible.")
        warning.setStyleSheet("color: #cc4400; font-size: 11px;")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        btn_layout = QHBoxLayout()
        deny_btn = QPushButton("Deny")
        deny_btn.setStyleSheet("background: #cc2200; color: white; padding: 8px 20px;")
        deny_btn.clicked.connect(self._deny)

        approve_btn = QPushButton("Approve")
        approve_btn.setStyleSheet("background: #226600; color: white; padding: 8px 20px;")
        approve_btn.clicked.connect(self._approve)

        btn_layout.addWidget(deny_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(approve_btn)
        layout.addLayout(btn_layout)

    def _approve(self) -> None:
        self._approved = True
        self.accept()

    def _deny(self) -> None:
        self._approved = False
        self.reject()

    def was_approved(self) -> bool:
        return self._approved
