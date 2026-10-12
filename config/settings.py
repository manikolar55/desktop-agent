"""Application settings loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── AI Provider ──────────────────────────────────────────────────────────
    ai_provider: Literal["anthropic", "openai", "ollama", "claude_code"] = "ollama"
    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # ── Voice ────────────────────────────────────────────────────────────────
    voice_input_provider: Literal["faster_whisper", "whisper_api", "disabled"] = "disabled"
    whisper_model_size: Literal["tiny", "base", "small", "medium", "large"] = "base"
    voice_output_provider: Literal["pyttsx3", "elevenlabs", "disabled"] = "pyttsx3"
    elevenlabs_api_key: str = ""

    # ── Google Chat ──────────────────────────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8080/oauth/callback"
    google_chat_space_ids: str = ""

    # ── Upwork ───────────────────────────────────────────────────────────────
    upwork_client_id: str = ""
    upwork_client_secret: str = ""
    upwork_min_budget: int = 500
    upwork_min_hourly_rate: int = 25

    # ── Browser ──────────────────────────────────────────────────────────────
    browser_type: Literal["chromium", "chrome", "firefox"] = "chromium"
    chrome_remote_debug_port: int = 0

    # ── Security ─────────────────────────────────────────────────────────────
    credential_passphrase: str = ""

    # ── Application ──────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    db_path: Path = Path("data/agent.db")
    max_step_retries: int = Field(default=3, ge=0, le=10)
    max_task_duration_seconds: int = Field(default=3600, ge=0)

    @field_validator("db_path", mode="before")
    @classmethod
    def ensure_db_dir(cls, v: str | Path) -> Path:
        p = Path(v)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def google_chat_space_list(self) -> list[str]:
        return [s.strip() for s in self.google_chat_space_ids.split(",") if s.strip()]

    def is_ai_configured(self) -> bool:
        if self.ai_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.ai_provider == "openai":
            return bool(self.openai_api_key)
        if self.ai_provider == "ollama":
            return True
        if self.ai_provider == "claude_code":
            return True
        return False

    def is_voice_input_configured(self) -> bool:
        return self.voice_input_provider != "disabled"

    def is_voice_output_configured(self) -> bool:
        return self.voice_output_provider != "disabled"

    def is_google_chat_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    def is_upwork_configured(self) -> bool:
        return bool(self.upwork_client_id and self.upwork_client_secret)


_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings


def reload_settings() -> AppSettings:
    global _settings
    _settings = AppSettings()
    return _settings
