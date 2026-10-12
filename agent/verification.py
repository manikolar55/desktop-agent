"""Post-task verification helpers."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def verify_browser_state(url: str, expected_text: str | None = None) -> dict[str, Any]:
    """
    Check that the browser is at the expected URL and optionally contains expected text.
    Returns a result dict with 'passed', 'url', 'errors', 'notes'.
    """
    try:
        from browser.manager import get_browser_manager
        bm = get_browser_manager()
        current_url = bm.current_url()
        page_text = bm.read_page()
        errors = bm.get_console_errors()

        passed = True
        notes = []

        if url and url not in current_url:
            passed = False
            notes.append(f"Expected URL containing '{url}', got '{current_url}'")

        if expected_text and expected_text.lower() not in page_text.lower():
            passed = False
            notes.append(f"Expected text '{expected_text}' not found on page")

        if errors:
            notes.append(f"Console errors: {errors[:3]}")

        return {"passed": passed, "url": current_url, "errors": errors, "notes": notes}
    except Exception as exc:
        return {"passed": False, "url": "", "errors": [str(exc)], "notes": ["Browser verification failed"]}


def verify_file_written(path: str, expected_content: str | None = None) -> dict[str, Any]:
    import os
    if not os.path.exists(path):
        return {"passed": False, "notes": [f"File not found: {path}"]}
    if expected_content:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        if expected_content not in content:
            return {"passed": False, "notes": [f"Expected content not in {path}"]}
    return {"passed": True, "notes": [f"File verified: {path}"]}
