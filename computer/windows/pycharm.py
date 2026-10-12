"""PyCharm window detection and project verification on Windows."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from computer.windows.adapter import WindowsAdapter

log = logging.getLogger(__name__)


class PyCharmFinder:
    def __init__(self) -> None:
        self._adapter = WindowsAdapter()

    def find_pycharm_window(self, project_name: str = "") -> dict | None:
        """
        Find a visible PyCharm window. If project_name is given, match it against
        the window title (PyCharm shows the project name in the title bar).
        Returns a dict with window info or None.
        """
        windows = self._adapter.list_windows()
        for w in windows:
            title = w.title
            if "PyCharm" not in title:
                continue
            if project_name and project_name.lower() not in title.lower():
                continue
            log.info("Found PyCharm window: '%s' (hwnd=%d)", title, w.hwnd)
            return {
                "title": title,
                "hwnd": w.hwnd,
                "pid": w.pid,
                "x": w.x,
                "y": w.y,
                "width": w.width,
                "height": w.height,
            }
        return None

    def is_pycharm_running(self, project_path: str = "") -> bool:
        """Check if any PyCharm process is running."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq pycharm64.exe", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            running = "pycharm64.exe" in result.stdout.lower()
            if running and project_path:
                # Check the window title includes the last folder name as a proxy
                folder = Path(project_path).name
                window = self.find_pycharm_window(folder)
                return window is not None
            return running
        except Exception as exc:
            log.debug("PyCharm check failed: %s", exc)
            return False

    def focus_pycharm(self, project_name: str = "") -> bool:
        window_info = self.find_pycharm_window(project_name)
        if not window_info:
            return False
        from computer.base import WindowInfo
        w = WindowInfo(
            title=window_info["title"],
            process_name="pycharm64.exe",
            hwnd=window_info["hwnd"],
            pid=window_info["pid"],
        )
        return self._adapter.focus_window(w)
