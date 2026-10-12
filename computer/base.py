"""Platform-agnostic computer-control interface."""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class WindowInfo:
    title: str
    process_name: str
    hwnd: int = 0
    pid: int = 0
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


class ComputerControlProvider(ABC):
    """Base interface for OS-level computer control."""

    @abstractmethod
    def list_windows(self) -> list[WindowInfo]: ...

    @abstractmethod
    def find_window(self, title_fragment: str) -> Optional[WindowInfo]: ...

    @abstractmethod
    def focus_window(self, window: WindowInfo) -> bool: ...

    @abstractmethod
    def capture_screen(self) -> bytes: ...

    @abstractmethod
    def send_keys(self, keys: str) -> None: ...

    @abstractmethod
    def move_mouse(self, x: int, y: int) -> None: ...

    @abstractmethod
    def click_mouse(self, x: int, y: int, button: str = "left") -> None: ...

    @abstractmethod
    def platform_name(self) -> str: ...


class PlatformAdapter:
    """Factory that returns the correct platform implementation."""

    @staticmethod
    def create() -> ComputerControlProvider:
        os_name = platform.system()
        if os_name == "Windows":
            from computer.windows.adapter import WindowsAdapter
            return WindowsAdapter()
        if os_name == "Darwin":
            from computer.macos.adapter import MacOSAdapter  # type: ignore[import]
            return MacOSAdapter()
        raise NotImplementedError(f"No computer-control adapter for platform: {os_name}")
