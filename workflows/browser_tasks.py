"""Reusable browser workflow helpers."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def open_url(url: str) -> str:
    from browser.manager import get_browser_manager
    return get_browser_manager().navigate(url)


def read_current_page() -> str:
    from browser.manager import get_browser_manager
    return get_browser_manager().read_page()


def take_screenshot(name: str = "") -> str:
    from browser.manager import get_browser_manager
    return get_browser_manager().screenshot(name)


def search_and_summarize(url: str, query: str) -> str:
    from browser.manager import get_browser_manager
    from models.provider import get_provider
    bm = get_browser_manager()
    bm.navigate(url)
    page_text = bm.read_page()
    provider = get_provider()
    return provider.complete(
        f"Summarise the following web page content relevant to the query: '{query}'",
        page_text[:4000],
        max_tokens=512,
    )
