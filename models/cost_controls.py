"""Token budget tracking and cost controls."""

from __future__ import annotations

import threading
from datetime import date

_lock = threading.Lock()
_daily_tokens: dict[str, int] = {}

DEFAULT_DAILY_TOKEN_LIMIT = 100_000


def record_usage(provider: str, tokens: int) -> None:
    today = date.today().isoformat()
    key = f"{today}:{provider}"
    with _lock:
        _daily_tokens[key] = _daily_tokens.get(key, 0) + tokens


def daily_usage(provider: str) -> int:
    today = date.today().isoformat()
    key = f"{today}:{provider}"
    with _lock:
        return _daily_tokens.get(key, 0)


def within_budget(provider: str, limit: int = DEFAULT_DAILY_TOKEN_LIMIT) -> bool:
    return daily_usage(provider) < limit
