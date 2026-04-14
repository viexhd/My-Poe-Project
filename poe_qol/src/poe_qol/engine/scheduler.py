"""Wires macros to hotkeys and owns their lifecycle."""
from __future__ import annotations

import logging

from ..core.config import ConfigStore
from ..core.state import AppState
from ..input.hotkeys import HotkeyRouter
from ..input.sender import InputSender
from .macro import Macro
from .registry import discover

log = logging.getLogger("poe_qol.scheduler")


class Scheduler:
    def __init__(self, cfg: ConfigStore, state: AppState,
                 sender: InputSender, hotkeys: HotkeyRouter) -> None:
        self.cfg = cfg
        self.state = state
        self.sender = sender
        self.hotkeys = hotkeys
        self.macros: dict[str, Macro] = {}

    def load(self) -> None:
        classes = discover()
        for name, cls in classes.items():
            self.macros[name] = cls(self.cfg, self.state, self.sender)
            log.info("loaded macro: %s", name)
        self._bind_hotkeys()

    def _bind_hotkeys(self) -> None:
        # App-level keys
        self.hotkeys.bind(
            "emergency_stop",
            self.cfg.get("hotkeys.emergency_stop", "f12"),
            self.emergency_stop,
        )
        self.hotkeys.bind(
            "toggle_global",
            self.cfg.get("hotkeys.toggle_global", "pause"),
            self.toggle_global,
        )
        # Per-macro keys
        for name, macro in self.macros.items():
            for action, cfg_path in macro.HOTKEYS.items():
                combo = self.cfg.get(cfg_path)
                if not combo:
                    continue
                key = f"{name}:{action}"
                self.hotkeys.bind(
                    key, combo,
                    lambda m=macro, a=action: m.on_hotkey(a),
                )

    # ---- actions exposed to the UI / hotkeys ----
    def emergency_stop(self) -> None:
        log.warning("EMERGENCY STOP")
        # Signal every macro to abort cooperatively. `Macro._stop` is
        # the per-sweep flag that the interruptible waits inside the
        # sweep loop poll, so this takes effect immediately.
        for m in self.macros.values():
            m.stop()
        # Release every modifier a running sweep might have been
        # holding down. Without this, Ctrl stays pressed after F12
        # and the user's next normal click is a Ctrl+click.
        for k in ("ctrl", "shift", "alt"):
            try:
                self.sender.key_up(k)
            except Exception:
                log.exception("failed to release %s on emergency stop", k)
        # Trip the global kill-switch + flip master off so nothing new
        # starts. The UI master checkbox clears both when re-checked,
        # which is how the user resumes.
        self.state.emergency_stop()
        self.cfg.set("app.global_enabled", False)

    def toggle_global(self) -> None:
        cur = self.cfg.get("app.global_enabled", True)
        self.cfg.set("app.global_enabled", not cur)
        self.state.set("global_enabled", not cur)
        log.info("global_enabled -> %s", not cur)

    def shutdown(self) -> None:
        for m in self.macros.values():
            m.stop()
        self.hotkeys.unbind_all()
