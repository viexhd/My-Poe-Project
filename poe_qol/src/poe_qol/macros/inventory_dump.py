"""Grid-dump macros.

This file defines:
    * `GridDumpMacro` – generic Ctrl-click sweep over a 2-D grid.
       Subclasses pick the config namespace (`CFG_PATH`) and hotkey
       names; everything else (origin resolution, slot selection,
       focus-clicks, vision anchor, slot profiles) is shared.
    * `InventoryDumpMacro`  – CFG_PATH = macros.inventory_dump

Originally derived from `inventory.ahk` + `poe mini project/autoclicker.cpp`.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Iterable

import yaml

from ..engine.macro import Macro
from ..engine.registry import register

# vision imports are deferred inside _resolve_origin so this module
# stays importable without opencv/numpy installed (headless CI).


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------

def grid_points(origin, cell, cols, rows) -> list[list[tuple[int, int]]]:
    ox, oy = origin
    cw, ch = cell
    # Round at use time (cell size may be a float after full-grid
    # calibration) so cumulative drift stays sub-pixel.
    return [[(int(round(ox + c * cw)), int(round(oy + r * ch)))
             for c in range(cols)]
            for r in range(rows)]


def build_serpentine(origin, cell, cols, rows) -> list[tuple[int, int, tuple[int, int]]]:
    mat = grid_points(origin, cell, cols, rows)
    out: list[tuple[int, int, tuple[int, int]]] = []
    for c in range(cols):
        r_iter = range(rows) if c % 2 == 0 else range(rows - 1, -1, -1)
        for r in r_iter:
            out.append((r, c, mat[r][c]))
    return out


def build_row_major(origin, cell, cols, rows) -> list[tuple[int, int, tuple[int, int]]]:
    mat = grid_points(origin, cell, cols, rows)
    return [(r, c, mat[r][c]) for r in range(rows) for c in range(cols)]


def filter_selected(points, selected: Iterable[tuple[int, int]]):
    sel = {tuple(p) for p in selected}
    if not sel:
        return points
    return [p for p in points if (p[0], p[1]) in sel]


def load_slot_profile(profile_dir: Path, name: str) -> list[tuple[int, int]]:
    p = profile_dir / f"{name}.yaml"
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text()) or {}
    return [tuple(s) for s in data.get("slots") or []]


# ---------------------------------------------------------------------------
# Generic grid-dump macro
# ---------------------------------------------------------------------------

class GridDumpMacro(Macro):
    """Generic dump macro.  Subclass and set NAME, CFG_PATH, HOTKEYS."""
    NAME = "grid_dump"
    CFG_PATH = "macros.grid_dump"
    HOTKEYS: dict[str, str] = {}

    def _k(self, *parts: str) -> str:
        return ".".join((self.CFG_PATH, *parts))

    # ---- public API ----
    def on_hotkey(self, action: str) -> None:
        if action == "left":
            self.start(lambda: self._sweep("left"))
        elif action == "right":
            self.start(lambda: self._sweep("right"))

    def trigger(self, button: str = "left") -> None:
        """Programmatic trigger (used by UI Dump button)."""
        self.start(lambda: self._sweep(button))

    # ---- helpers ----
    def _resolve_origin(self) -> tuple[int, int]:
        """Resolution order: template match -> window-relative -> absolute."""
        fallback = tuple(self.cfg.get(self._k("grid", "origin"), [0, 0]))

        # 1. template match
        tpl_name = self.cfg.get(self._k("anchor_template"))
        if tpl_name:
            try:
                from ..vision.capture import Capture
                from ..vision.detect import load_template, match_template
                root = Path(self.cfg.get("vision.template_dir",
                                         "assets/templates"))
                tpl = load_template(root / tpl_name)
                if tpl is None:
                    self.log.warning("anchor template %s not found", tpl_name)
                else:
                    cap = Capture(self.cfg.get("vision.default_monitor", 1))
                    frame = cap.grab()
                    hit = match_template(
                        frame, tpl,
                        self.cfg.get("vision.match_threshold", 0.86))
                    if hit:
                        self.log.info("anchor matched at %s (score %.2f)",
                                      hit[:2], hit[2])
                        return (hit[0], hit[1])
            except Exception:
                self.log.exception("template anchor failed")

        # 2. window-relative
        rel = self.cfg.get(self._k("origin_relative_to_window"))
        if rel:
            try:
                from ..vision.window import find_window
                rect = find_window(
                    self.cfg.get(self._k("window", "title_pattern"),
                                 "Path of Exile"),
                    self.cfg.get(self._k("window", "class_pattern")),
                )
                if rect is not None:
                    ax, ay = rect.anchor(rel.get("anchor", "top_left"))
                    dx, dy = rel.get("offset", [0, 0])
                    resolved = (ax + int(dx), ay + int(dy))
                    self.log.info("window-relative origin: anchor=%s "
                                  "rect=(%d,%d-%d,%d) -> %s",
                                  rel.get("anchor"),
                                  rect.left, rect.top, rect.right, rect.bottom,
                                  resolved)
                    return resolved
                self.log.warning("PoE window not found; using absolute origin")
            except Exception:
                self.log.exception("window-relative origin failed")

        # 3. absolute fallback
        return fallback  # type: ignore[return-value]

    def _effective_selection(self) -> list[tuple[int, int]]:
        prof_name = self.cfg.get(self._k("active_slot_profile"))
        if prof_name:
            prof_dir = Path(self.cfg.get(self._k("slot_profile_dir"),
                                         "config/slot_profiles"))
            slots = load_slot_profile(prof_dir, prof_name)
            if slots:
                return slots
            self.log.warning("slot profile %r has no slots; falling back",
                             prof_name)
        return [tuple(s) for s in
                (self.cfg.get(self._k("selected_slots")) or [])]

    def _focus_window(self, first_point: tuple[int, int]) -> None:
        """Click the first slot N times (no modifier) to bring PoE to
        the foreground before the real sweep begins. Configurable via
        `<CFG_PATH>.focus_clicks` / `focus_click_delay_ms` (set 0 to
        skip)."""
        n = int(self.cfg.get(self._k("focus_clicks"), 2))
        if n <= 0:
            return
        delay_ms = int(self.cfg.get(self._k("focus_click_delay_ms"), 50))
        x, y = first_point
        for _ in range(n):
            if self.should_abort():
                return
            self.sender.click(x, y, button="left")
            # Interruptible sleep: unblocks the moment emergency_stop
            # (F12) fires so the sweep aborts instantly instead of
            # racing out the remaining delay.
            if self._stop.wait(delay_ms / 1000.0):
                return

    # ---- core ----
    def _sweep(self, button: str) -> None:
        origin = self._resolve_origin()
        cell = tuple(self.cfg.get(self._k("grid", "cell_size"), [53, 55]))
        cols = self.cfg.get(self._k("grid", "cols"), 12)
        rows = self.cfg.get(self._k("grid", "rows"), 5)
        pattern = self.cfg.get(self._k("grid", "pattern"), "serpentine")
        modifier = self.cfg.get(self._k("modifier"), "ctrl")
        lo, hi = self.cfg.get(self._k("click_delay_ms"), [30, 80])

        builder = build_serpentine if pattern == "serpentine" else build_row_major
        points = builder(origin, cell, cols, rows)
        selected = self._effective_selection()
        points = filter_selected(points, selected)
        total = len(points)
        if total == 0:
            self.log.info("no slots to click (empty selection?)")
            return

        self.log.info("[%s] sweep %s: %d of %d slots (pattern=%s, selection=%s)",
                      self.NAME, button, total, cols * rows, pattern,
                      "profile/manual" if selected else "all")

        # Focus PoE first by clicking the first target slot a couple of times.
        first_xy = points[0][2]
        self._focus_window(first_xy)
        if self.should_abort():
            return

        if modifier:
            self.sender.key_down(modifier)
        try:
            for i, (_r, _c, (x, y)) in enumerate(points, start=1):
                if self.should_abort():
                    self.log.warning("sweep aborted at %d/%d", i, total)
                    break
                self.sender.click(x, y, button=button)
                # Interruptible sleep so F12 aborts mid-delay.
                if self._stop.wait(random.randint(lo, hi) / 1000.0):
                    self.log.warning("sweep aborted at %d/%d", i, total)
                    break
        finally:
            if modifier:
                # Always release the modifier, even on abort, so the
                # user doesn't end up with a stuck Ctrl key.
                self.sender.key_up(modifier)


# ---------------------------------------------------------------------------
# Concrete: player inventory
# ---------------------------------------------------------------------------

@register
class InventoryDumpMacro(GridDumpMacro):
    NAME = "inventory_dump"
    CFG_PATH = "macros.inventory_dump"
    HOTKEYS = {
        "left":  "macros.inventory_dump.hotkeys.left",
        "right": "macros.inventory_dump.hotkeys.right",
    }
