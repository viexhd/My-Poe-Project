"""Auto-presses the life-flask key at a randomised cadence.

Source: `Life Flask.ahk`.

Improvements over the original:
    * interval min/max come from config (no magic numbers).
    * hard-guarded by global kill-switch.
    * uses `threading.Event.wait()` instead of `SetTimer`, so toggling
      off never leaves a pending timer to fire.
"""
from __future__ import annotations

import random

from ..engine.macro import Macro
from ..engine.registry import register


@register
class LifeFlaskMacro(Macro):
    NAME = "life_flask"
    HOTKEYS = {"toggle": "macros.life_flask.hotkey"}

    def on_hotkey(self, action: str) -> None:
        if action != "toggle":
            return
        if self.running:
            self.log.info("life-flask OFF")
            self.stop()
        else:
            self.log.info("life-flask ON")
            self.start(self._loop)

    def _loop(self) -> None:
        key = self.cfg.get("macros.life_flask.key", "1")
        lo, hi = self.cfg.get("macros.life_flask.interval_ms", [4000, 5000])
        while not self.should_abort():
            if not self.cfg.get("app.global_enabled", True):
                break
            self.sender.press(key)
            wait_s = random.randint(lo, hi) / 1000.0
            # `.wait(timeout)` returns True if stop event was set — abort fast
            if self._stop.wait(wait_s):
                break
