"""Windows computer-control adapter using win32 and pywinauto."""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

from computer.base import ComputerControlProvider, WindowInfo

log = logging.getLogger(__name__)

try:
    import win32gui
    import win32process
    import win32con
    import win32api
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False
    log.warning("pywin32 not available — window enumeration disabled")

try:
    import pyautogui
    pyautogui.FAILSAFE = False   # LLM-generated coords can be (0,0); fail-safe causes crashes
    pyautogui.PAUSE = 0.05
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    _PYAUTOGUI_AVAILABLE = False


class WindowsAdapter(ComputerControlProvider):
    def platform_name(self) -> str:
        return "windows"

    def list_windows(self) -> list[WindowInfo]:
        if not _WIN32_AVAILABLE:
            return []
        windows: list[WindowInfo] = []

        def _callback(hwnd: int, _: object) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                windows.append(WindowInfo(
                    title=title,
                    process_name="",
                    hwnd=hwnd,
                    pid=pid,
                    x=rect[0],
                    y=rect[1],
                    width=rect[2] - rect[0],
                    height=rect[3] - rect[1],
                ))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_callback, None)
        return windows

    def find_window(self, title_fragment: str) -> Optional[WindowInfo]:
        for w in self.list_windows():
            if title_fragment.lower() in w.title.lower():
                return w
        return None

    def focus_window(self, window: WindowInfo) -> bool:
        if not _WIN32_AVAILABLE:
            return False
        try:
            hwnd = window.hwnd
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            # Windows blocks SetForegroundWindow unless we share the foreground thread.
            try:
                import win32process
                import win32api
                fg = win32gui.GetForegroundWindow()
                fg_tid = win32process.GetWindowThreadProcessId(fg)[0]
                my_tid = win32api.GetCurrentThreadId()
                if fg_tid and fg_tid != my_tid:
                    win32process.AttachThreadInput(fg_tid, my_tid, True)
                    win32gui.SetForegroundWindow(hwnd)
                    win32process.AttachThreadInput(fg_tid, my_tid, False)
                else:
                    win32gui.SetForegroundWindow(hwnd)
            except Exception:
                win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception as exc:
            log.error("focus_window failed: %s", exc)
            # Fallback: use pyautogui to click the window's title bar
            if _PYAUTOGUI_AVAILABLE:
                try:
                    import pyautogui
                    pyautogui.click(window.x + window.width // 2, window.y + 8)
                    return True
                except Exception:
                    pass
            return False

    def capture_screen(self) -> bytes:
        if not _PYAUTOGUI_AVAILABLE:
            return b""
        import io
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def send_keys(self, keys: str) -> None:
        if _PYAUTOGUI_AVAILABLE:
            pyautogui.typewrite(keys, interval=0.02)

    def move_mouse(self, x: int, y: int) -> None:
        if _PYAUTOGUI_AVAILABLE:
            pyautogui.moveTo(x, y, duration=0.2)

    def click_mouse(self, x: int, y: int, button: str = "left") -> None:
        if _PYAUTOGUI_AVAILABLE:
            pyautogui.click(x, y, button=button)

    def open_application(self, executable: str) -> bool:
        import os
        # For Chrome specifically, try full Windows install paths before bare name.
        if executable.lower() in ("chrome.exe", "chrome"):
            candidates = [
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
            for c in candidates:
                if os.path.exists(c):
                    executable = c
                    break
        try:
            subprocess.Popen(executable, shell=True)
            return True
        except Exception as exc:
            log.error("open_application failed: %s", exc)
            return False
