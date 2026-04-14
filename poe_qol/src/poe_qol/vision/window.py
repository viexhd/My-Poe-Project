"""Locate the Path of Exile game window on Windows.

Uses ctypes so no extra dependency is required. Returns None on
non-Windows platforms or if the window isn't found, so callers can
fall back to absolute screen coordinates gracefully.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import re
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class WindowRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def anchor(self, name: str) -> tuple[int, int]:
        """Return the absolute screen coord of a named anchor."""
        if name == "top_left":
            return (self.left, self.top)
        if name == "top_right":
            return (self.right, self.top)
        if name == "bottom_left":
            return (self.left, self.bottom)
        if name == "bottom_right":
            return (self.right, self.bottom)
        if name == "center":
            return ((self.left + self.right) // 2,
                    (self.top + self.bottom) // 2)
        raise ValueError(f"unknown anchor: {name!r}")


def find_window(title_pattern: Optional[str] = "Path of Exile",
                class_pattern: Optional[str] = None
                ) -> Optional[WindowRect]:
    """Return the rect of the first window matching either pattern."""
    if not sys.platform.startswith("win"):
        return None

    user32 = ctypes.windll.user32
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes  = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes  = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.IsWindowVisible.argtypes = [wt.HWND]

    title_re = re.compile(title_pattern, re.IGNORECASE) if title_pattern else None
    class_re = re.compile(class_pattern, re.IGNORECASE) if class_pattern else None

    found: list[WindowRect] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        user32.GetClassNameW(hwnd, buf, 512)
        cls = buf.value
        ok = False
        if title_re and title and title_re.search(title):
            ok = True
        if class_re and cls and class_re.search(cls):
            ok = True
        if ok:
            rect = wt.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                # skip zero-size ghost windows
                if rect.right - rect.left > 100 and rect.bottom - rect.top > 100:
                    found.append(WindowRect(rect.left, rect.top,
                                            rect.right, rect.bottom))
                    return False  # stop enumerating
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return found[0] if found else None
