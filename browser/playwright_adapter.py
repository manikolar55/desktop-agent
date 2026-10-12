"""Playwright-based browser automation adapter."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, Browser, Page, Playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    log.warning("Playwright not installed. Run: playwright install chromium")


class PlaywrightAdapter:
    def __init__(self, browser_type: str = "chromium", headless: bool = False) -> None:
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright is not installed")
        self._browser_type = browser_type
        self._headless = headless
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._console_errors: list[str] = []
        self._failed_requests: list[str] = []
        self._screenshot_dir = Path("data/screenshots")
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

    def launch(self, cdp_url: str | None = None) -> None:
        self._pw = sync_playwright().start()
        if cdp_url:
            self._browser = self._pw.chromium.connect_over_cdp(cdp_url)
            log.info("Connected to existing browser via CDP: %s", cdp_url)
        else:
            launcher = getattr(self._pw, self._browser_type)
            self._browser = launcher.launch(headless=self._headless)
            log.info("Launched %s browser", self._browser_type)
        self._page = self._browser.new_page()
        self._setup_listeners()

    def _setup_listeners(self) -> None:
        if not self._page:
            return
        self._page.on("console", lambda msg: self._console_errors.append(
            f"[{msg.type}] {msg.text}"
        ) if msg.type in ("error", "warning") else None)
        self._page.on("requestfailed", lambda req: self._failed_requests.append(
            f"{req.method} {req.url} — {req.failure}"
        ))

    def navigate(self, url: str, wait_for: str = "domcontentloaded") -> str:
        self._ensure_page()
        self._console_errors.clear()
        self._failed_requests.clear()
        # Reject data: and javascript: URLs
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Unsafe URL rejected: {url}")
        self._page.goto(url, wait_until=wait_for, timeout=30_000)
        log.info("Navigated to: %s", url)
        return f"Navigated to {url}"

    def read_page(self) -> str:
        self._ensure_page()
        from browser.page_inspector import extract_text_from_html
        html = self._page.content()
        return extract_text_from_html(html)[:5000]

    def get_title(self) -> str:
        self._ensure_page()
        return self._page.title()

    def click(self, selector: str) -> str:
        self._ensure_page()
        self._page.click(selector, timeout=10_000)
        return f"Clicked: {selector}"

    def fill(self, selector: str, value: str) -> str:
        self._ensure_page()
        self._page.fill(selector, value, timeout=10_000)
        return f"Filled {selector}"

    def screenshot(self, name: str = "") -> str:
        self._ensure_page()
        ts = int(time.time())
        fname = f"{name or 'screenshot'}_{ts}.png"
        path = str(self._screenshot_dir / fname)
        self._page.screenshot(path=path, full_page=False)
        return path

    def evaluate(self, js: str) -> Any:
        self._ensure_page()
        return self._page.evaluate(js)

    def wait_for_selector(self, selector: str, timeout: int = 10_000) -> bool:
        self._ensure_page()
        try:
            self._page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    def get_console_errors(self) -> list[str]:
        return list(self._console_errors)

    def get_failed_requests(self) -> list[str]:
        return list(self._failed_requests)

    def current_url(self) -> str:
        return self._page.url if self._page else ""

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._browser = None
        self._page = None
        self._pw = None
        log.info("Browser closed")

    def _ensure_page(self) -> None:
        if not self._page:
            raise RuntimeError("Browser not launched. Call launch() first.")
