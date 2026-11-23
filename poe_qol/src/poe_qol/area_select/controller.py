"""Qt glue for the Alt+drag area selection.

    OS hook thread                       Qt main thread
    ──────────────                       ──────────────
    LowLevelInputHook ─► GestureGate ─► (signals) ─► AreaSelectController
                          swallow?                    ├─ resolve_selection
                                                      ├─ occupancy (optional)
                                                      ├─ overlay model → overlay
                                                      └─ TransferStrategy
                                                           manual | experimental

Everything the hook thread touches (settings, geometry cache, focus
matcher, the gate) is either immutable or swapped atomically; Qt objects
are only touched on the main thread via queued signals.

The constructor accepts providers so tests (and other front-ends) can
drive the controller without a real hook, window or screen.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .gesture import GestureGate, KeyEvent, MouseEvent  # noqa: F401  (re-export)
from .grid import GridGeometry, Rect, Slot, load_geometry
from .occupancy import OccupancyThresholds, SlotStats, capture_grid, classify_slots
from .overlay_model import EMPTY, OverlayModel, drag_model, plan_model
from .selection import resolve_selection
from .settings import AreaSelectSettings
from .transfer import ManualTransfer, TransferPlan, TransferStrategy, order_slots

log = logging.getLogger("poe_qol.area_select")

GeometryProvider = Callable[[str], GridGeometry]
OccupancyProvider = Callable[[GridGeometry, list], Optional[Mapping[Slot, SlotStats]]]


class AreaSelectController(QObject):
    overlay_changed = Signal()
    status_changed = Signal(str)

    # hook thread -> main thread (queued; run on the Qt thread)
    _sig_start = Signal(int, int)
    _sig_update = Signal(object)
    _sig_end = Signal(object)
    _sig_cancel = Signal(str)
    _sig_click = Signal(int, int, object)
    _sig_key = Signal(str)
    # transfer worker -> main thread
    _sig_progress = Signal(int, int, int, object)   # run_id, done, total, remaining
    _sig_finished = Signal(int, str, str)           # run_id, status, message

    def __init__(self, cfg: Any, state: Any, sender: Any = None, *,
                 start_hook: bool = True,
                 geometry_provider: Optional[GeometryProvider] = None,
                 focus_provider: Optional[Callable[[], bool]] = None,
                 capture_provider: Optional[Callable[[GridGeometry], Any]] = None,
                 occupancy_provider: Optional[OccupancyProvider] = None,
                 strategy_factory: Optional[Callable[[str], TransferStrategy]] = None,
                 overlay_factory: Optional[Callable[[], Any]] = None,
                 modifier_state: Optional[Callable[[], frozenset]] = None,
                 window_provider: Optional[Callable[[], Any]] = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.state = state
        self.sender = sender
        self.settings = AreaSelectSettings.load(cfg)
        self._geometry_provider = geometry_provider or (lambda ns: load_geometry(cfg, ns))
        self._focus = focus_provider or self._default_focus()
        self._capture = capture_provider or capture_grid
        self._occupancy_provider = occupancy_provider
        self._strategy_factory = strategy_factory or self._default_strategy
        self._overlay_factory = overlay_factory
        self._modifier_state = modifier_state or self._default_modifier_state()
        self._window_provider = window_provider or self._default_window

        self._geoms: dict[str, GridGeometry] = {}
        self._window_rect = None   # game window, cached for overlay placement
        self._occ: dict[str, dict[Slot, SlotStats]] = {}
        self.plan: Optional[TransferPlan] = None
        self._remaining: tuple[Slot, ...] = ()
        self._strategy: Optional[TransferStrategy] = None
        self._run_id = 0      # tags transfer callbacks; stale runs are ignored
        self.overlay_model: OverlayModel = EMPTY
        self._overlay = None
        self._hook = None

        self.gate = GestureGate(
            self, enabled=self._gesture_enabled,
            modifier=lambda: self.settings.modifier_keys,
            game_focused=self._focus,
            start_allowed=self._start_allowed)

        for sig, slot in ((self._sig_start, self._on_drag_start),
                          (self._sig_update, self._on_drag_update),
                          (self._sig_end, self._on_drag_end),
                          (self._sig_cancel, self._on_drag_cancel),
                          (self._sig_click, self._on_click),
                          (self._sig_key, self._on_key),
                          (self._sig_progress, self._on_progress),
                          (self._sig_finished, self._on_finished)):
            sig.connect(slot)

        self._geom_timer = QTimer(self)
        self._geom_timer.timeout.connect(self.refresh_geometry)
        self._geom_timer.start(500)
        self._focus_timer = QTimer(self)        # runs only while dragging
        self._focus_timer.timeout.connect(self._check_focus)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(lambda: self._cancel_strategy("timeout"))
        self.refresh_geometry()

        # start_hook=False: never install the OS hook (tests, other
        # front-ends feeding the gate themselves). Otherwise the hook
        # runs exactly while the feature is enabled.
        self._use_hook = start_hook
        self._sync_hook()

    # ---- defaults (real Windows environment) ----
    def _inv_window_cfg(self) -> tuple[str, Optional[str]]:
        ns = self.settings.grids[0] if self.settings.grids else "macros.inventory_dump"
        return (self.cfg.get(f"{ns}.window.title_pattern", "Path of Exile"),
                self.cfg.get(f"{ns}.window.class_pattern"))

    def _default_focus(self) -> Callable[[], bool]:
        from ..vision.window import ForegroundMatcher
        return ForegroundMatcher(*self._inv_window_cfg())

    def _default_window(self) -> Any:
        try:
            from ..vision.window import find_window
            return find_window(*self._inv_window_cfg())
        except Exception:
            return None

    @staticmethod
    def _default_modifier_state() -> Callable[[], frozenset]:
        from ..input.mouse_hook import modifiers_down
        return modifiers_down

    def _default_strategy(self, mode: str) -> TransferStrategy:
        if mode != "experimental":
            return ManualTransfer()
        # Lazy import: the experimental package is never loaded unless
        # the user picked and acknowledged that mode.
        from ..experimental.bulk_ctrl_click import ExperimentalCtrlClickTransfer
        required = self.settings.modifier_keys
        return ExperimentalCtrlClickTransfer(
            self.sender, settings=self.settings.experimental,
            is_allowed=self._transfer_allowed,
            game_focused=self._focus,
            modifier_held=lambda: bool(self._modifier_state() & required))

    # ---- lifecycle ----
    def start_hook(self) -> bool:
        from ..input.mouse_hook import LowLevelInputHook
        if self._hook is None:
            self._hook = LowLevelInputHook(self.gate.handle_mouse,
                                           self.gate.handle_key)
        ok = self._hook.start()
        if not ok:
            self._status(f"Area select unavailable: {self._hook.error}")
        return ok

    def stop_hook(self) -> None:
        if self._hook is not None:
            self._hook.stop()

    def _sync_hook(self) -> None:
        if not self._use_hook:
            return
        running = self._hook is not None and self._hook.running
        if self.settings.enabled and not running:
            self.start_hook()
        elif not self.settings.enabled and running:
            self.stop_hook()

    def shutdown(self) -> None:
        self._geom_timer.stop()
        self._focus_timer.stop()
        self._clear_timer.stop()
        if self._hook is not None:
            self._hook.stop()
        self._cancel_strategy("shutdown")
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None

    def reload_settings(self) -> None:
        self.settings = AreaSelectSettings.load(self.cfg)
        if self._overlay is not None:
            self._overlay.set_settings(self.settings.overlay)
        self.refresh_geometry()
        if not self.settings.enabled:
            self.gate.cancel("disabled")
            self._cancel_strategy("disabled")
        self._sync_hook()

    def refresh_geometry(self) -> None:
        """Re-resolve grid geometry + game window (every 500 ms, at drag
        start and on settings changes). Skipped while disabled."""
        if not self.settings.enabled and self._geoms:
            return
        try:
            self._window_rect = self._window_provider()
        except Exception:
            self._window_rect = None
        geoms: dict[str, GridGeometry] = {}
        for ns in self.settings.grids:
            try:
                geoms[ns] = self._geometry_provider(ns)
            except Exception:
                log.debug("grid %s unavailable", ns, exc_info=True)
        self._geoms = geoms          # atomic swap, read by the hook thread

    @property
    def geometries(self) -> dict[str, GridGeometry]:
        return dict(self._geoms)

    # ---- gate callbacks (hook thread: emit only) ----
    def _gesture_enabled(self) -> bool:
        return (self.settings.enabled
                and bool(self.cfg.get("app.global_enabled", True))
                and not self.state.stop_event.is_set())

    def _transfer_allowed(self) -> bool:
        return (bool(self.cfg.get("app.global_enabled", True))
                and not self.state.stop_event.is_set())

    def _start_allowed(self, x: int, y: int) -> bool:
        m = self.settings.start_margin_px
        return any(g.bounds().expanded(m).contains(x, y)
                   for g in self._geoms.values())

    def on_drag_start(self, x, y):
        self._sig_start.emit(x, y)

    def on_drag_update(self, rect):
        self._sig_update.emit(rect)

    def on_drag_end(self, rect):
        self._sig_end.emit(rect)

    def on_drag_cancel(self, reason):
        self._sig_cancel.emit(reason)

    def on_user_click(self, x, y, modifiers):
        if self._strategy is not None:
            self._sig_click.emit(x, y, modifiers)

    def on_user_move(self, x, y):
        s = self._strategy          # direct call: must stay cheap
        if s is not None:
            s.user_moved(x, y)

    def on_user_key(self, key):
        s = self._strategy
        if key == "esc" and s is not None:
            if not isinstance(s, ManualTransfer):
                # Stop a click loop *now*, before the game handles Esc
                # (which may close the inventory). cancel() is thread-safe.
                s.cancel("escape")
            self._sig_key.emit(key)

    # ---- main thread ----
    def _on_drag_start(self, x: int, y: int) -> None:
        self._cancel_strategy("new selection")
        self._set_model(EMPTY)
        self.refresh_geometry()
        self._occ = self._detect_occupancy() if self.settings.detect_items else {}
        self._focus_timer.start(100)
        self._debug("drag start at (%d, %d)", x, y)

    def _on_drag_update(self, rect: Rect) -> None:
        sel = resolve_selection(rect, self._geoms, self.settings.click_threshold_px)
        self._set_model(drag_model(rect, sel, self._geoms, self._occ,
                                   self.settings.debug))

    def _on_drag_cancel(self, reason: str) -> None:
        self._focus_timer.stop()
        self._set_model(EMPTY)
        self._status(f"Selection cancelled ({reason})")

    def _on_drag_end(self, rect: Rect) -> None:
        self._focus_timer.stop()
        sel = resolve_selection(rect, self._geoms, self.settings.click_threshold_px)
        if sel is None:
            self._set_model(EMPTY)
            self._status("Nothing selected")
            return
        slots = list(sel.slots)
        occ = self._occ.get(sel.grid) or {}
        if self.settings.skip_empty and occ:
            slots = [s for s in slots if s not in occ or occ[s].occupied]
        if not slots:
            self._set_model(EMPTY)
            self._status("All selected slots look empty")
            return
        plan = TransferPlan(sel.grid, self._geoms[sel.grid],
                            tuple(order_slots(slots, self.settings.order)))
        self._debug("selected %d slots on %s: %s", len(plan.slots), sel.grid,
                    plan.slots)
        prev = self._strategy
        if prev is not None and prev.active:
            self._set_model(EMPTY)
            self._status("Previous transfer is still stopping; try again")
            return
        mode = self.settings.effective_mode
        if self.settings.transfer_mode == "experimental" and mode == "manual":
            self._status("Experimental mode not acknowledged: using manual mode")
        self.plan = plan
        self._remaining = plan.slots
        self._run_id += 1
        self._strategy = self._strategy_factory(mode)
        self._strategy.start(plan, _RunListener(self, self._run_id))
        if mode == "manual" and self.settings.manual_clear_after_s > 0 \
                and self.plan is not None:
            self._clear_timer.start(self.settings.manual_clear_after_s * 1000)

    def _on_click(self, x: int, y: int, modifiers: frozenset) -> None:
        if self._strategy is not None:
            self._strategy.user_clicked(x, y, modifiers)

    def _on_key(self, key: str) -> None:
        if key == "esc":
            self._cancel_strategy("escape")

    def _on_progress(self, run_id: int, done: int, total: int,
                     remaining: tuple) -> None:
        if run_id != self._run_id or self.plan is None:
            return
        self._remaining = tuple(remaining)
        mode = self._strategy.MODE if self._strategy else "manual"
        self._set_model(plan_model(self.plan, self._remaining, mode,
                                   self.settings.debug))
        self._status(f"{done}/{total} slots")

    def _on_finished(self, run_id: int, status: str, message: str) -> None:
        if run_id != self._run_id:
            return
        self._clear_timer.stop()
        self.plan = None
        self._remaining = ()
        self._strategy = None
        self._set_model(EMPTY)
        self._status(f"{status}: {message}")
        log.info("area transfer %s: %s", status, message)

    def _cancel_strategy(self, reason: str) -> None:
        """Stop the current transfer. Manual mode finishes synchronously;
        the experimental worker finishes on its own thread, so its plan
        is dropped here and its late callbacks are ignored (run_id). The
        strategy object is kept until it is inactive, so a new
        experimental run can't overlap a stopping one."""
        s = self._strategy
        if s is None:
            return
        s.cancel(reason)
        if self.plan is not None:
            self._run_id += 1
            self._clear_timer.stop()
            self.plan = None
            self._remaining = ()
            self._set_model(EMPTY)
            self._status(f"Transfer stopped ({reason})")

    def _check_focus(self) -> None:
        if self.gate.dragging and not self._focus():
            self.gate.cancel("focus")

    def _detect_occupancy(self) -> dict[str, dict[Slot, SlotStats]]:
        out: dict[str, dict[Slot, SlotStats]] = {}
        thr = OccupancyThresholds(self.settings.occupancy_std_min,
                                  self.settings.occupancy_mean_min)
        for ns, geom in self._geoms.items():
            try:
                if self._occupancy_provider is not None:
                    res = self._occupancy_provider(geom, geom.all_slots())
                else:
                    shot = self._capture(geom)
                    res = (classify_slots(shot[0], shot[1], geom,
                                          geom.all_slots(), thr)
                           if shot is not None else None)
            except Exception:
                log.debug("occupancy detection failed", exc_info=True)
                res = None
            if res:
                out[ns] = dict(res)
                if self.settings.debug:
                    for s, st in sorted(res.items()):
                        log.info("occupancy %s %s mean=%.1f std=%.1f -> %s",
                                 ns, s, st.mean, st.std,
                                 "item" if st.occupied else "empty")
        return out

    # ---- output ----
    def _set_model(self, model: OverlayModel) -> None:
        self.overlay_model = model
        self.overlay_changed.emit()
        if not self.settings.overlay.visible:
            if self._overlay is not None:
                self._overlay.set_model(EMPTY)
            return
        if self._overlay is None:
            if model.empty:
                return
            self._overlay = self._make_overlay()
            if self._overlay is None:
                return
        if not model.empty:
            self._place_overlay()
        self._overlay.set_model(model)

    def _make_overlay(self):
        try:
            if self._overlay_factory is not None:
                return self._overlay_factory()
            from ..ui.area_select_overlay import AreaSelectOverlay
            return AreaSelectOverlay(self.settings.overlay)
        except Exception:
            log.exception("area-select overlay unavailable")
            return None

    def _place_overlay(self) -> None:
        """Cover the game window (or the screen) with the overlay."""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        dpr = float(screen.devicePixelRatio()) if screen else 1.0
        win = self._window_rect
        if win is not None:
            frame = Rect(win.left, win.top, win.right, win.bottom)
        elif screen is not None:
            g = screen.geometry()
            frame = Rect(g.x() * dpr, g.y() * dpr,
                         (g.x() + g.width()) * dpr, (g.y() + g.height()) * dpr)
        else:
            return
        self._overlay.set_frame(frame, dpr)

    def _status(self, text: str) -> None:
        self.status_changed.emit(text)

    def _debug(self, msg: str, *args) -> None:
        if self.settings.debug:
            log.info(msg, *args)


class _RunListener:
    """TransferListener for one run; forwards to the controller's
    queued signals tagged with the run id (safe from any thread)."""

    def __init__(self, ctl: AreaSelectController, run_id: int) -> None:
        self._ctl = ctl
        self._run_id = run_id

    def on_progress(self, done, total, remaining):
        self._ctl._sig_progress.emit(self._run_id, done, total, remaining)

    def on_finished(self, status, message):
        self._ctl._sig_finished.emit(self._run_id, status, message)
