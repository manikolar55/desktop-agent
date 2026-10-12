"""Browser lifecycle manager — single shared browser instance."""

from __future__ import annotations

import logging
from config.settings import get_settings
from browser.playwright_adapter import PlaywrightAdapter

log = logging.getLogger(__name__)

_browser_manager: "BrowserManager | None" = None


class BrowserManager:
    def __init__(self) -> None:
        self._adapter: PlaywrightAdapter | None = None

    def _ensure(self) -> PlaywrightAdapter:
        if self._adapter is None:
            s = get_settings()
            self._adapter = PlaywrightAdapter(browser_type=s.browser_type, headless=False)
            cdp_port = s.chrome_remote_debug_port
            cdp_url = f"http://localhost:{cdp_port}" if cdp_port else None
            self._adapter.launch(cdp_url=cdp_url)
        return self._adapter

    def _call(self, fn):
        """Call fn(adapter). If the browser was closed externally, re-launch and retry."""
        try:
            return fn(self._ensure())
        except Exception as exc:
            msg = str(exc).lower()
            if any(k in msg for k in ("closed", "target page", "browser has been", "context")):
                log.warning("Browser context lost (%s) — re-launching", exc)
                try:
                    if self._adapter:
                        self._adapter.close()
                except Exception:
                    pass
                self._adapter = None
                return fn(self._ensure())
            raise

    def navigate(self, url: str) -> str:
        return self._call(lambda a: a.navigate(url))

    def read_page(self) -> str:
        return self._call(lambda a: a.read_page())

    def click(self, selector: str) -> str:
        return self._call(lambda a: a.click(selector))

    def fill(self, selector: str, value: str) -> str:
        return self._call(lambda a: a.fill(selector, value))

    def screenshot(self, name: str = "") -> str:
        return self._call(lambda a: a.screenshot(name))

    def current_url(self) -> str:
        return self._ensure().current_url() if self._adapter else ""

    def get_console_errors(self) -> list[str]:
        return self._ensure().get_console_errors() if self._adapter else []

    def close(self) -> None:
        if self._adapter:
            self._adapter.close()
            self._adapter = None


def get_browser_manager() -> BrowserManager:
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager
