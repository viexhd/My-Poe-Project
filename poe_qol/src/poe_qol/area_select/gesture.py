"""Gesture gate: turns raw global mouse / key events into a drag.

Runs on the OS hook thread, so every method must be quick and must not
touch Qt. For each event it returns whether the event is *swallowed*
(kept from the game):

* left-button down with exactly the selection modifier held, the game
  focused, the feature enabled and the press inside (or near) a grid:
  swallowed, starts a drag. Anywhere else, Alt+click reaches the game
  as usual (e.g. picking up ground loot with labels shown).
* the matching button up: swallowed (the game never saw the down).
* mouse moves: never swallowed, the cursor must keep moving.
* Esc during a drag: swallowed and cancels the drag. Esc at any other
  time reaches the game.
* injected events (SendInput, i.e. our own experimental clicks): ignored.

Listener callbacks are invoked synchronously on the calling thread.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol

from .grid import Rect
from .selection import DragSelector

MODIFIERS = ("ctrl", "alt", "shift")
_ALIASES = {"control": "ctrl", "ctl": "ctrl", "menu": "alt", "option": "alt"}


def parse_modifier(spec: str) -> frozenset[str]:
    """``"ctrl+alt"`` -> ``frozenset({"ctrl", "alt"})``."""
    parts = [p.strip().lower() for p in (spec or "").split("+") if p.strip()]
    keys = frozenset(_ALIASES.get(p, p) for p in parts)
    if not keys or not keys <= set(MODIFIERS):
        raise ValueError(f"not a modifier combination: {spec!r}")
    return keys


@dataclass(frozen=True)
class MouseEvent:
    kind: Literal["down", "up", "move"]   # left button only
    x: int
    y: int
    modifiers: frozenset[str] = field(default_factory=frozenset)
    injected: bool = False


@dataclass(frozen=True)
class KeyEvent:
    key: str           # "esc" or a lower-case key name
    down: bool
    injected: bool = False


class GestureListener(Protocol):
    def on_drag_start(self, x: int, y: int) -> None: ...
    def on_drag_update(self, rect: Rect) -> None: ...
    def on_drag_end(self, rect: Rect) -> None: ...
    def on_drag_cancel(self, reason: str) -> None: ...
    def on_user_click(self, x: int, y: int, modifiers: frozenset[str]) -> None: ...
    def on_user_move(self, x: int, y: int) -> None: ...
    def on_user_key(self, key: str) -> None: ...


class GestureGate:
    def __init__(self, listener: GestureListener, *,
                 enabled: Callable[[], bool],
                 modifier: Callable[[], frozenset[str]],
                 game_focused: Callable[[], bool],
                 start_allowed: Callable[[int, int], bool]) -> None:
        self._l = listener
        self._enabled = enabled
        self._modifier = modifier
        self._focused = game_focused
        self._start_allowed = start_allowed
        self._sel = DragSelector()
        self._lock = threading.RLock()
        self._swallow_up = False      # we ate a down; eat its up too
        self._swallow_esc_up = False

    @property
    def dragging(self) -> bool:
        return self._sel.active

    # ---- mouse ----
    def handle_mouse(self, ev: MouseEvent) -> bool:
        if ev.injected:
            return False
        with self._lock:
            if ev.kind == "move":
                if self._sel.active:
                    if not self._focused():
                        self._cancel_locked("focus")
                        return False
                    rect = self._sel.move(ev.x, ev.y)
                    if rect is not None:
                        self._l.on_drag_update(rect)
                else:
                    self._l.on_user_move(ev.x, ev.y)
                return False

            if ev.kind == "down":
                if self._sel.active:           # stray second down
                    return True
                if self._should_start(ev):
                    self._sel.press(ev.x, ev.y)
                    self._swallow_up = True
                    self._l.on_drag_start(ev.x, ev.y)
                    return True
                self._l.on_user_click(ev.x, ev.y, ev.modifiers)
                return False

            # "up"
            if self._sel.active:
                rect = self._sel.release(ev.x, ev.y)
                self._swallow_up = False
                if rect is not None:
                    self._l.on_drag_end(rect)
                return True
            if self._swallow_up:
                self._swallow_up = False
                return True
            return False

    def _should_start(self, ev: MouseEvent) -> bool:
        try:
            return (ev.modifiers == self._modifier()
                    and self._enabled()
                    and self._focused()
                    and self._start_allowed(ev.x, ev.y))
        except Exception:
            return False

    # ---- keyboard ----
    def handle_key(self, ev: KeyEvent) -> bool:
        if ev.injected:
            return False
        with self._lock:
            if ev.key == "esc":
                if ev.down and self._sel.active:
                    self._cancel_locked("escape")
                    self._swallow_esc_up = True
                    return True
                if not ev.down and self._swallow_esc_up:
                    self._swallow_esc_up = False
                    return True
            if ev.down:
                self._l.on_user_key(ev.key)
            return False

    # ---- external ----
    def cancel(self, reason: str) -> None:
        """Abort an active drag (thread-safe). The button-up that
        follows is still swallowed."""
        with self._lock:
            if self._sel.active:
                self._cancel_locked(reason)

    def _cancel_locked(self, reason: str) -> None:
        self._sel.cancel()
        self._l.on_drag_cancel(reason)
