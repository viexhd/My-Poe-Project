"""Tiny pub-sub used as the single source of truth for runtime state.

UI, hotkeys, and macros all read/write through AppState so there is
exactly one place to log transitions and enforce invariants (like the
global kill-switch).
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable


Listener = Callable[[str, Any], None]


class AppState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._values: dict[str, Any] = {}
        self._listeners: dict[str, list[Listener]] = defaultdict(list)
        # stop_event is the kill-switch every running macro checks.
        self.stop_event = threading.Event()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._values[key] = value
            listeners = list(self._listeners[key]) + list(self._listeners["*"])
        for l in listeners:
            try:
                l(key, value)
            except Exception:  # never let a listener kill the bus
                import logging
                logging.getLogger("poe_qol").exception("listener error")

    def on(self, key: str, listener: Listener) -> None:
        with self._lock:
            self._listeners[key].append(listener)

    def emergency_stop(self) -> None:
        self.stop_event.set()
        self.set("global_enabled", False)

    def clear_emergency(self) -> None:
        self.stop_event.clear()
