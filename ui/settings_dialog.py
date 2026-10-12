"""Settings dialog — first-run wizard and ongoing configuration."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QFormLayout, QLineEdit, QComboBox, QSpinBox, QCheckBox,
    QPushButton, QLabel, QTextEdit, QGroupBox, QMessageBox
)

from storage.repositories import pref_repo


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(600, 500)
        self._setup_ui()
        self._load()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        tabs.addTab(self._build_ai_tab(), "AI Provider")
        tabs.addTab(self._build_voice_tab(), "Voice")
        tabs.addTab(self._build_browser_tab(), "Browser")
        tabs.addTab(self._build_upwork_tab(), "Upwork Profile")
        tabs.addTab(self._build_projects_tab(), "Projects")
        tabs.addTab(self._build_security_tab(), "Security")

        layout.addWidget(tabs)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _build_ai_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._ai_provider = QComboBox()
        self._ai_provider.addItems(["ollama", "anthropic", "openai"])
        self._anthropic_key = QLineEdit()
        self._anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._openai_key = QLineEdit()
        self._openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._ollama_url = QLineEdit()
        self._ollama_model = QLineEdit()
        form.addRow("Provider:", self._ai_provider)
        form.addRow("Anthropic API Key:", self._anthropic_key)
        form.addRow("OpenAI API Key:", self._openai_key)
        form.addRow("Ollama URL:", self._ollama_url)
        form.addRow("Ollama Model:", self._ollama_model)
        note = QLabel("Keys are stored in the OS keychain, not in plain text files.")
        note.setStyleSheet("color: #888;")
        form.addRow(note)
        return w

    def _build_voice_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._voice_in = QComboBox()
        self._voice_in.addItems(["disabled", "faster_whisper", "whisper_api"])
        self._whisper_size = QComboBox()
        self._whisper_size.addItems(["tiny", "base", "small", "medium", "large"])
        self._voice_out = QComboBox()
        self._voice_out.addItems(["pyttsx3", "elevenlabs", "disabled"])
        form.addRow("Voice Input:", self._voice_in)
        form.addRow("Whisper Model Size:", self._whisper_size)
        form.addRow("Voice Output:", self._voice_out)
        note = QLabel(
            "faster_whisper runs locally. whisper_api requires an OpenAI key.\n"
            "Larger Whisper models are more accurate but slower."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888;")
        form.addRow(note)
        return w

    def _build_browser_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._browser_type = QComboBox()
        self._browser_type.addItems(["chromium", "chrome", "firefox"])
        self._debug_port = QSpinBox()
        self._debug_port.setRange(0, 65535)
        self._debug_port.setSpecialValueText("Not set")
        form.addRow("Browser:", self._browser_type)
        form.addRow("Remote Debug Port:", self._debug_port)
        note = QLabel(
            "Set Remote Debug Port only if you want the agent to connect to your "
            "running Chrome session. Launch Chrome with --remote-debugging-port=9222."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888;")
        form.addRow(note)
        return w

    def _build_upwork_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._up_name = QLineEdit()
        self._up_title = QLineEdit()
        self._up_skills = QLineEdit()
        self._up_skills.setPlaceholderText("Comma-separated, e.g. Python, React, FastAPI")
        self._up_exp = QSpinBox()
        self._up_exp.setRange(0, 40)
        self._up_min_budget = QSpinBox()
        self._up_min_budget.setRange(0, 100000)
        self._up_rate = QSpinBox()
        self._up_rate.setRange(0, 500)
        self._up_portfolio = QTextEdit()
        self._up_portfolio.setMaximumHeight(80)
        self._up_portfolio.setPlaceholderText("List verified portfolio projects, one per line")
        form.addRow("Full Name:", self._up_name)
        form.addRow("Professional Title:", self._up_title)
        form.addRow("Skills:", self._up_skills)
        form.addRow("Years Experience:", self._up_exp)
        form.addRow("Min Budget (USD):", self._up_min_budget)
        form.addRow("Hourly Rate (USD):", self._up_rate)
        form.addRow("Portfolio Projects:", self._up_portfolio)
        note = QLabel("Only verified information will be used in proposals.")
        note.setStyleSheet("color: #888;")
        form.addRow(note)
        return w

    def _build_projects_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        label = QLabel(
            "Project registry is configured in projects.yaml. "
            "Copy config/projects.example.yaml to config/projects.yaml and edit it.\n"
            "Restart the application after changes."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch()
        return w

    def _build_security_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._max_retries = QSpinBox()
        self._max_retries.setRange(0, 10)
        self._max_duration = QSpinBox()
        self._max_duration.setRange(0, 86400)
        self._max_duration.setSuffix(" s")
        self._max_duration.setSpecialValueText("No limit")
        form.addRow("Max Step Retries:", self._max_retries)
        form.addRow("Max Task Duration:", self._max_duration)
        return w

    def _load(self) -> None:
        prefs = pref_repo.all()
        self._ai_provider.setCurrentText(prefs.get("ai_provider", "ollama"))
        self._ollama_url.setText(prefs.get("ollama_url", "http://localhost:11434"))
        self._ollama_model.setText(prefs.get("ollama_model", "llama3.2"))
        self._voice_in.setCurrentText(prefs.get("voice_input", "disabled"))
        self._whisper_size.setCurrentText(prefs.get("whisper_size", "base"))
        self._voice_out.setCurrentText(prefs.get("voice_output", "pyttsx3"))
        self._browser_type.setCurrentText(prefs.get("browser_type", "chromium"))
        self._debug_port.setValue(prefs.get("debug_port", 0))
        self._max_retries.setValue(prefs.get("max_retries", 3))
        self._max_duration.setValue(prefs.get("max_duration", 3600))

        profile = prefs.get("upwork_profile", {})
        self._up_name.setText(profile.get("name", ""))
        self._up_title.setText(profile.get("title", ""))
        self._up_skills.setText(", ".join(profile.get("skills", [])))
        self._up_exp.setValue(profile.get("experience_years", 0))
        self._up_min_budget.setValue(profile.get("min_budget_usd", 500))
        self._up_rate.setValue(profile.get("hourly_rate_usd", 0))
        self._up_portfolio.setPlainText(
            "\n".join(profile.get("portfolio_projects", []))
        )

    def _save(self) -> None:
        pref_repo.set("ai_provider", self._ai_provider.currentText())
        pref_repo.set("ollama_url", self._ollama_url.text())
        pref_repo.set("ollama_model", self._ollama_model.text())
        pref_repo.set("voice_input", self._voice_in.currentText())
        pref_repo.set("whisper_size", self._whisper_size.currentText())
        pref_repo.set("voice_output", self._voice_out.currentText())
        pref_repo.set("browser_type", self._browser_type.currentText())
        pref_repo.set("debug_port", self._debug_port.value())
        pref_repo.set("max_retries", self._max_retries.value())
        pref_repo.set("max_duration", self._max_duration.value())

        # Save API keys to OS keychain, not to preferences db
        from security.secrets import store_secret
        if self._anthropic_key.text():
            store_secret("anthropic_api_key", self._anthropic_key.text())
        if self._openai_key.text():
            store_secret("openai_api_key", self._openai_key.text())

        profile = {
            "name": self._up_name.text(),
            "title": self._up_title.text(),
            "skills": [s.strip() for s in self._up_skills.text().split(",") if s.strip()],
            "experience_years": self._up_exp.value(),
            "min_budget_usd": self._up_min_budget.value(),
            "hourly_rate_usd": self._up_rate.value(),
            "portfolio_projects": [
                p.strip() for p in self._up_portfolio.toPlainText().splitlines() if p.strip()
            ],
        }
        pref_repo.set("upwork_profile", profile)

        QMessageBox.information(self, "Saved", "Settings saved. Restart may be required for some changes.")
        self.accept()
