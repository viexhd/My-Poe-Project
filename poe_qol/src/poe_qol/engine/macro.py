"""Macro base class.

Every macro subclass declares:
    NAME           – unique key, matches config path `macros.<NAME>`
    HOTKEYS        – {'action': 'config.path.to.hotkey'}
    on_hotkey()    – dispatch by action name
    run()          – optional long-running loop (start() will thread it)

The base class provides:
    * cooperative stop via `self._stop` or the global kill-switch
    * re-entrancy guard (prevents F1 spam from starting two sweeps)
    * convenient handles to config, state, sender, logger
"""
from __future__ import annotations

import logging
import threading
from abc import ABC
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.config import ConfigStore
    from ..core.state import AppState
    from ..input.sender import InputSender


class Macro(ABC):
    NAME: str = "base"
    HOTKEYS: dict[str, str] = {}

    def __init__(self, cfg: "ConfigStore", state: "AppState",
                 sender: "InputSender") -> None:
        self.cfg = cfg
        self.state = state
        self.sender = sender
        self.log = logging.getLogger(f"poe_qol.macros.{self.NAME}")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Optional progress tuple (current, total) set by the sweep
        # loop so the UI status bar can render "Inventory 5/60".
        self.progress: tuple[int, int] | None = None

    # ---- lifecycle ----
    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get(f"macros.{self.NAME}.enabled", False))

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def guard(self) -> bool:
        """Return True if this macro is allowed to fire right now."""
        if not self.cfg.get("app.global_enabled", True):
            return False
        if not self.enabled:
            return False
        if self.state.stop_event.is_set():
            return False
        if self.running:
            return False
        return True

    def start(self, target) -> None:
        """Run `target` on a worker thread with a stop guard."""
        if not self.guard():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._wrap, args=(target,), daemon=True,
            name=f"macro-{self.NAME}",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _wrap(self, target) -> None:
        try:
            target()
        except Exception:
            self.log.exception("macro crashed")

    # ---- convenience ----
    def should_abort(self) -> bool:
        return self._stop.is_set() or self.state.stop_event.is_set()

    # ---- overridable ----
    def on_hotkey(self, action: str) -> None:  # pragma: no cover
        raise NotImplementedError
