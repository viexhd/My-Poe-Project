"""Global hotkey router.

Wraps the `keyboard` library so the rest of the app only deals with
string hotkey names coming from config. Registered hotkeys are stored
so we can re-bind at runtime (UI edit → unregister old → register new).
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("poe_qol.hotkeys")

try:
    import keyboard as _kb  # type: ignore
except Exception:  # pragma: no cover
    _kb = None


class HotkeyRouter:
    def __init__(self) -> None:
        self._bindings: dict[str, tuple[str, Callable]] = {}  # name -> (combo, cb)
        self._handles: dict[str, object] = {}

    def bind(self, name: str, combo: str, callback: Callable[[], None]) -> None:
        """Register (or re-register) a named hotkey."""
        if not combo:
            return
        self.unbind(name)
        self._bindings[name] = (combo, callback)
        if _kb:
            try:
                h = _kb.add_hotkey(combo, callback, suppress=False)
                self._handles[name] = h
                log.info("bound %s -> %s", name, combo)
            except Exception:
                log.exception("failed binding %s=%s", name, combo)

    def unbind(self, name: str) -> None:
        if name in self._handles and _kb:
            try:
                _kb.remove_hotkey(self._handles[name])
            except Exception:
                pass
        self._handles.pop(name, None)
        self._bindings.pop(name, None)

    def unbind_all(self) -> None:
        for n in list(self._bindings):
            self.unbind(n)
