"""EXPERIMENTAL, NOT GGG-COMPLIANT: Ctrl-click every selected slot.

One Alt+drag gesture produces one Ctrl+click per selected slot (up to
``max_slots``). GGG's rules allow one game action per key press, so this
breaks them; it exists for the owner's personal use only, behind an
explicit acknowledgement (``area_select.experimental.acknowledged``).
See docs/COMPLIANCE_REVIEW.md §7.

Safety rails (all covered by tests/test_area_transfer.py):

* refuses to run unless acknowledged,
* waits for the selection modifier (Alt) to be released first, so the
  game never receives Ctrl+Alt+click; gives up after a timeout,
* checks before every click: F12 / master switch, game focus, Esc /
  new gesture (``cancel``), and real mouse movement by the player,
* always releases Ctrl, even on error,
* fixed minimum delay between clicks (no randomisation: this is not
  meant to look human).
"""
from __future__ import annotations

import math
import threading
import time
from typing import Callable, Optional

from ..area_select.settings import MIN_CLICK_DELAY_MS, ExperimentalSettings
from ..area_select.transfer import TransferListener, TransferPlan, TransferStrategy

_POLL_S = 0.02


class ExperimentalCtrlClickTransfer(TransferStrategy):
    MODE = "experimental"
    GGG_COMPLIANT = False
    DESCRIPTION = ("EXPERIMENTAL: Ctrl-clicks every selected slot for you. "
                   "Many game actions per gesture: breaks GGG's macro rules.")

    def __init__(self, sender, *, settings: ExperimentalSettings,
                 is_allowed: Callable[[], bool],
                 game_focused: Callable[[], bool],
                 modifier_held: Callable[[], bool],
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 run_async: bool = True) -> None:
        self.sender = sender
        self.settings = settings
        self._is_allowed = is_allowed
        self._focused = game_focused
        self._modifier_held = modifier_held
        self._sleep = sleep
        self._clock = clock
        self._run_async = run_async
        self._cancel = threading.Event()
        self._cancel_reason = ""
        self._user_took_over = threading.Event()
        self._last_target: Optional[tuple[int, int]] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def active(self) -> bool:
        return self._running

    @property
    def cursor_target(self) -> Optional[tuple[int, int]]:
        """Where this run last moved the cursor (None before the first click)."""
        return self._last_target

    # ---- interface ----
    def start(self, plan: TransferPlan, listener: TransferListener) -> None:
        if not self.settings.acknowledged:
            listener.on_finished(
                "error", "Experimental transfer has not been acknowledged "
                         "in the Area Select tab.")
            return
        if self._running:
            listener.on_finished("error", "A transfer is already running.")
            return
        self._cancel.clear()
        self._user_took_over.clear()
        self._last_target = None
        self._running = True
        if self._run_async:
            self._thread = threading.Thread(
                target=self._run, args=(plan, listener), daemon=True,
                name="area-select-experimental")
            self._thread.start()
        else:
            self._run(plan, listener)

    def cancel(self, reason: str) -> None:
        self._cancel_reason = reason
        self._cancel.set()

    def user_moved(self, x: int, y: int) -> None:
        tgt = self._last_target
        if self._running and tgt is not None:
            if math.hypot(x - tgt[0], y - tgt[1]) > self.settings.abort_move_px:
                self._user_took_over.set()

    # ---- worker ----
    def _stop_reason(self) -> Optional[tuple[str, str]]:
        if self._cancel.is_set():
            return ("cancelled", self._cancel_reason or "cancelled")
        if not self._is_allowed():
            return ("aborted", "emergency stop / master switch off")
        if not self._focused():
            return ("aborted", "game lost focus")
        if self._user_took_over.is_set():
            return ("aborted", "mouse moved by the player")
        return None

    def _wait_modifier_release(self) -> bool:
        deadline = self._clock() + self.settings.modifier_release_timeout_ms / 1000
        while self._modifier_held():
            if self._clock() >= deadline or self._cancel.is_set():
                return False
            self._sleep(_POLL_S)
        return True

    def _run(self, plan: TransferPlan, listener: TransferListener) -> None:
        points = plan.points()[: self.settings.max_slots]
        slots = list(plan.slots[: len(points)])
        total = len(points)
        status, message = "done", f"Transferred {total} slots"
        try:
            if not self._wait_modifier_release():
                status, message = ("cancelled", self._cancel_reason) \
                    if self._cancel.is_set() else \
                    ("aborted", "selection modifier still held")
                return
            stop = self._stop_reason()
            if stop:
                status, message = stop
                return
            delay = max(MIN_CLICK_DELAY_MS, self.settings.click_delay_ms) / 1000
            self.sender.key_down("ctrl")
            try:
                for i, (x, y) in enumerate(points):
                    if i:
                        self._sleep(delay)
                        stop = self._stop_reason()
                        if stop:
                            status, message = stop
                            break
                    self._last_target = (x, y)
                    self.sender.click(x, y)
                    listener.on_progress(i + 1, total, tuple(slots[i + 1:]))
            finally:
                self.sender.key_up("ctrl")
        except Exception as e:  # pragma: no cover - defensive
            status, message = "error", f"{type(e).__name__}: {e}"
        finally:
            self._running = False
            listener.on_finished(status, message)
