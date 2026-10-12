"""
Integration tests for Google Chat event parsing and handler.
No real credentials needed — uses mocked messages.
"""

import pytest
from integrations.google_chat.handler import (
    handle_message, reset_seen_messages, _is_relevant, _resolve_project
)


@pytest.fixture(autouse=True)
def clean_state():
    reset_seen_messages()
    yield
    reset_seen_messages()


def _msg(text, msg_id="msg/test001", space="spaces/TEST", sender="user@example.com"):
    return {
        "name": msg_id,
        "space": space,
        "sender": sender,
        "text": text,
        "thread": "spaces/TEST/threads/001",
        "create_time": "2026-01-01T00:00:00Z",
    }


class TestRelevanceDetection:
    def test_bug_keyword_is_relevant(self):
        assert _is_relevant("There's a bug in the checkout flow") is True

    def test_error_keyword_is_relevant(self):
        assert _is_relevant("Getting a 500 error on the API") is True

    def test_mention_is_relevant(self):
        assert _is_relevant("@agent please check this issue") is True

    def test_casual_chat_is_not_relevant(self):
        assert _is_relevant("Hey, how's everyone doing?") is False

    def test_meeting_notice_is_not_relevant(self):
        assert _is_relevant("Standup at 10am today") is False


class TestProjectResolution:
    def test_known_space_resolves_to_project(self, monkeypatch):
        monkeypatch.setattr(
            "integrations.google_chat.handler._resolve_project.__code__",
            _resolve_project.__code__,
        )
        from storage.repositories import pref_repo
        pref_repo.set("project_registry", [
            {"name": "MyApp", "chat_space_ids": ["spaces/ABC123"], "repository_path": "."}
        ])
        result = _resolve_project("spaces/ABC123")
        assert result == "MyApp"

    def test_unknown_space_returns_empty(self):
        from storage.repositories import pref_repo
        pref_repo.set("project_registry", [])
        result = _resolve_project("spaces/UNKNOWN")
        assert result == ""


class TestOAuthFailureHandling:
    def test_authenticate_fails_gracefully_without_credentials(self):
        """Should return False, not raise, when credentials are missing."""
        from integrations.google_chat.client import GoogleChatClient
        from unittest.mock import patch

        with patch("config.settings.get_settings") as mock_settings:
            mock_settings.return_value.google_client_id = ""
            mock_settings.return_value.google_client_secret = ""
            client = GoogleChatClient()
            result = client.authenticate()
        assert result is False


class TestMessageHandlerFlow:
    def test_full_flow_dispatches_task(self, monkeypatch):
        dispatched = []
        monkeypatch.setattr(
            "integrations.google_chat.handler._dispatch_to_orchestrator",
            lambda r: dispatched.append(r),
        )
        monkeypatch.setattr(
            "integrations.google_chat.handler._resolve_project",
            lambda space_id: "TestProject",
        )

        handle_message(_msg("@agent there's a bug with user login — getting 401"))
        assert len(dispatched) == 1
        assert dispatched[0].project_name == "TestProject"
        assert dispatched[0].reporter == "user@example.com"

    def test_unknown_space_not_dispatched(self, monkeypatch):
        dispatched = []
        monkeypatch.setattr(
            "integrations.google_chat.handler._dispatch_to_orchestrator",
            lambda r: dispatched.append(r),
        )
        monkeypatch.setattr(
            "integrations.google_chat.handler._resolve_project",
            lambda space_id: "",  # no project found
        )
        handle_message(_msg("@agent bug found"))
        assert dispatched == []

    def test_idempotency_key_contains_message_id(self, monkeypatch):
        dispatched = []
        submitted = []

        def fake_dispatch(report):
            dispatched.append(report)

        monkeypatch.setattr(
            "integrations.google_chat.handler._dispatch_to_orchestrator",
            fake_dispatch,
        )
        monkeypatch.setattr(
            "integrations.google_chat.handler._resolve_project",
            lambda space_id: "Proj",
        )
        handle_message(_msg("@agent error in dashboard", msg_id="msg/abc123"))
        assert len(dispatched) == 1
        assert dispatched[0].raw_message == "msg/abc123"
