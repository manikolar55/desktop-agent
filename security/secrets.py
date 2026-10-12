"""Secure credential storage using the OS keychain (Windows Credential Manager)."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

SERVICE_NAME = "DesktopAIAgent"

_SECRET_REDACT_PREFIXES = ("sk-", "sk-ant-", "AIza", "ya29.")


def store_secret(key: str, value: str) -> None:
    if not _KEYRING_AVAILABLE:
        log.warning("keyring not available; secret '%s' not stored persistently", key)
        return
    keyring.set_password(SERVICE_NAME, key, value)
    log.debug("Stored secret key='%s' in OS keychain", key)


def retrieve_secret(key: str) -> str | None:
    if not _KEYRING_AVAILABLE:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, key)
    except Exception as exc:
        log.error("Failed to retrieve secret '%s': %s", key, exc)
        return None


def delete_secret(key: str) -> None:
    if not _KEYRING_AVAILABLE:
        return
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except Exception:
        pass


def redact(text: str) -> str:
    """Replace known secret patterns in log strings with [REDACTED]."""
    for prefix in _SECRET_REDACT_PREFIXES:
        idx = text.find(prefix)
        while idx != -1:
            end = idx + len(prefix)
            while end < len(text) and text[end] not in (" ", "\n", "\r", '"', "'", ","):
                end += 1
            text = text[:idx] + "[REDACTED]" + text[end:]
            idx = text.find(prefix)
    return text
