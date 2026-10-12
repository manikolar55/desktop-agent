"""macOS computer-control adapter — NOT YET IMPLEMENTED.

Status: not_yet_implemented
Required work:
- Accessibility permissions via TCC (Privacy & Security → Accessibility)
- Screen recording permission for screen capture
- Implement using pyobjc / Quartz / AppKit
- AppleScript or Accessibility API for window enumeration
- Keychain integration for credentials
- Proper code signing for distribution
"""

from __future__ import annotations

from computer.base import ComputerControlProvider, WindowInfo


class MacOSAdapter(ComputerControlProvider):
    def platform_name(self) -> str:
        return "macos"

    def list_windows(self) -> list[WindowInfo]:
        raise NotImplementedError("macOS adapter not yet implemented")

    def find_window(self, title_fragment: str) -> WindowInfo | None:
        raise NotImplementedError("macOS adapter not yet implemented")

    def focus_window(self, window: WindowInfo) -> bool:
        raise NotImplementedError("macOS adapter not yet implemented")

    def capture_screen(self) -> bytes:
        raise NotImplementedError("macOS adapter not yet implemented")

    def send_keys(self, keys: str) -> None:
        raise NotImplementedError("macOS adapter not yet implemented")

    def move_mouse(self, x: int, y: int) -> None:
        raise NotImplementedError("macOS adapter not yet implemented")

    def click_mouse(self, x: int, y: int, button: str = "left") -> None:
        raise NotImplementedError("macOS adapter not yet implemented")
