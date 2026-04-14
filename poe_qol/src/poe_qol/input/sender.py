"""Low-level keyboard / mouse simulation.

Uses pydirectinput so DirectInput games (PoE) accept the events.
Falls back to pyautogui if pydirectinput is unavailable so the module
remains importable in a headless CI environment.
"""
from __future__ import annotations

import random
import time

try:
    import pydirectinput as _di  # type: ignore
    _BACKEND = "pydirectinput"
except Exception:  # pragma: no cover – fallback for CI / non-Windows
    _di = None
    _BACKEND = "stub"


class InputSender:
    def __init__(self, pre_click_settle_ms: int = 30, click_jitter_px: int = 0):
        self.pre_click_settle_ms = pre_click_settle_ms
        self.click_jitter_px = click_jitter_px

    # ---------- keyboard ----------
    def press(self, key: str) -> None:
        if _di:
            _di.press(key)

    def key_down(self, key: str) -> None:
        if _di:
            _di.keyDown(key)

    def key_up(self, key: str) -> None:
        if _di:
            _di.keyUp(key)

    # ---------- mouse ----------
    def move_to(self, x: int, y: int) -> None:
        if self.click_jitter_px:
            x += random.randint(-self.click_jitter_px, self.click_jitter_px)
            y += random.randint(-self.click_jitter_px, self.click_jitter_px)
        if _di:
            _di.moveTo(x, y)

    def click(self, x: int, y: int, button: str = "left") -> None:
        self.move_to(x, y)
        time.sleep(self.pre_click_settle_ms / 1000)
        if _di:
            _di.click(button=button)

    @property
    def backend(self) -> str:
        return _BACKEND
