"""Google Chat integration using the Google Chat REST API with OAuth 2.0."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

MessageCallback = Callable[[dict], None]

TOKEN_FILE = Path("data/google_token.json")
SCOPES = [
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/chat.messages.create",
]


class GoogleChatClient:
    """
    Polls configured Chat spaces for new messages.

    Status: partially_supported
    Requires: Google Cloud project, Chat API enabled, OAuth 2.0 credentials.
    Full pub/sub delivery requires a registered Chat app with a verified domain.
    Polling is used as a fallback.
    """

    def __init__(self) -> None:
        self._creds = None
        self._service = None
        self._callback: MessageCallback | None = None
        self._poll_thread: threading.Thread | None = None
        self._running = threading.Event()
        self._seen_message_ids: set[str] = set()

    def authenticate(self) -> bool:
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            if TOKEN_FILE.exists():
                self._creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

            if not self._creds or not self._creds.valid:
                if self._creds and self._creds.expired and self._creds.refresh_token:
                    self._creds.refresh(Request())
                else:
                    from config.settings import get_settings
                    s = get_settings()
                    if not s.google_client_id:
                        log.error("Google OAuth not configured")
                        return False
                    flow = InstalledAppFlow.from_client_config(
                        {
                            "installed": {
                                "client_id": s.google_client_id,
                                "client_secret": s.google_client_secret,
                                "redirect_uris": [s.google_redirect_uri],
                                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                "token_uri": "https://oauth2.googleapis.com/token",
                            }
                        },
                        SCOPES,
                    )
                    self._creds = flow.run_local_server(port=8080)

                TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                TOKEN_FILE.write_text(self._creds.to_json())

            self._service = build("chat", "v1", credentials=self._creds)
            log.info("Google Chat authenticated")
            return True
        except Exception as exc:
            log.error("Google Chat authentication failed: %s", exc)
            return False

    def set_message_callback(self, cb: MessageCallback) -> None:
        self._callback = cb

    def start_polling(self, space_ids: list[str], interval_seconds: int = 30) -> None:
        self._running.set()
        self._poll_thread = threading.Thread(
            target=self._poll_worker,
            args=(space_ids, interval_seconds),
            daemon=True,
            name="GoogleChatPoll",
        )
        self._poll_thread.start()
        log.info("Google Chat polling started for %d spaces", len(space_ids))

    def stop_polling(self) -> None:
        self._running.clear()

    def send_reply(self, space_id: str, thread_name: str, text: str) -> bool:
        if not self._service:
            return False
        # Treat as medium-risk action — caller should have approval
        try:
            self._service.spaces().messages().create(
                parent=space_id,
                body={"text": text, "thread": {"name": thread_name}},
                messageReplyOption="REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD",
            ).execute()
            return True
        except Exception as exc:
            log.error("Failed to send Chat reply: %s", exc)
            return False

    def _poll_worker(self, space_ids: list[str], interval: int) -> None:
        while self._running.is_set():
            for space_id in space_ids:
                try:
                    self._poll_space(space_id)
                except Exception as exc:
                    log.error("Poll error for space %s: %s", space_id, exc)
            time.sleep(interval)

    def _poll_space(self, space_id: str) -> None:
        if not self._service:
            return
        result = self._service.spaces().messages().list(
            parent=space_id, pageSize=10
        ).execute()
        for msg in result.get("messages", []):
            msg_name = msg.get("name", "")
            if msg_name in self._seen_message_ids:
                continue
            self._seen_message_ids.add(msg_name)
            if self._callback:
                # Treat message content as untrusted data — never execute as code
                safe_msg = {
                    "name": msg_name,
                    "space": space_id,
                    "sender": msg.get("sender", {}).get("displayName", "unknown"),
                    "text": msg.get("text", ""),
                    "thread": msg.get("thread", {}).get("name", ""),
                    "create_time": msg.get("createTime", ""),
                }
                self._callback(safe_msg)


_client: GoogleChatClient | None = None


def get_chat_client() -> GoogleChatClient:
    global _client
    if _client is None:
        _client = GoogleChatClient()
    return _client


def start_monitoring(space_ids: list[str], poll_interval: int = 30) -> bool:
    """
    Authenticate and begin polling the given Chat spaces.
    Wires the message handler automatically.
    Returns True if authentication succeeded.
    """
    from integrations.google_chat.handler import handle_message
    client = get_chat_client()
    client.set_message_callback(handle_message)
    if not client.authenticate():
        return False
    client.start_polling(space_ids, poll_interval)
    return True
