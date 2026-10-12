"""Tests for settings validation and configuration."""

import pytest
from unittest.mock import patch


class TestSettings:
    def test_default_provider_is_ollama(self, monkeypatch):
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        from config.settings import AppSettings
        s = AppSettings()
        assert s.ai_provider in ("ollama", "anthropic")

    def test_max_retries_bounded(self):
        from config.settings import AppSettings
        s = AppSettings(max_step_retries=3)
        assert s.max_step_retries == 3

    def test_ai_configured_with_anthropic_key(self):
        from config.settings import AppSettings
        s = AppSettings(ai_provider="anthropic", anthropic_api_key="sk-ant-test")
        assert s.is_ai_configured() is True

    def test_ai_not_configured_without_anthropic_key(self):
        from config.settings import AppSettings
        s = AppSettings(ai_provider="anthropic", anthropic_api_key="")
        assert s.is_ai_configured() is False

    def test_google_chat_space_list_parsed(self):
        from config.settings import AppSettings
        s = AppSettings(google_chat_space_ids="spaces/AAA, spaces/BBB")
        lst = s.google_chat_space_list
        assert lst == ["spaces/AAA", "spaces/BBB"]

    def test_empty_space_ids_gives_empty_list(self):
        from config.settings import AppSettings
        s = AppSettings(google_chat_space_ids="")
        assert s.google_chat_space_list == []

    def test_db_path_parent_created(self, tmp_path):
        from config.settings import AppSettings
        db = tmp_path / "sub" / "agent.db"
        s = AppSettings(db_path=str(db))
        assert s.db_path.parent.exists()
