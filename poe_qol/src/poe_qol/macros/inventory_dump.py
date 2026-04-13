"""Inventory sweep – Ctrl-click every selected slot in the inventory.

Source: `inventory.ahk` + `poe mini project/autoclicker.cpp`.

Pipeline:
    1. resolve origin   (vision anchor or config fallback)
    2. build point grid (serpentine or row_major, by (row, col))
    3. filter by `selected_slots` (empty = all)
    4. walk with the configured modifier held, random delay between clicks

All numbers (grid dims, cell size, origin, modifier, delays, selected
slots, slot profile) live in config. Nothing is hard-coded.
"""
from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Iterable

import yaml

from ..engine.macro import Macro
from ..engine.registry import register

# NOTE: vision imports are deferred to `_resolve_origin` so this macro
# can still be loaded in environments where opencv/numpy aren't
# installed (e.g. headless CI).


# ---------------------------------------------------------------------------
# Grid helpers – now (row, col)-indexed so the slot selector can speak
# directly in grid coordinates.
# ---------------------------------------------------------------------------

def grid_points(origin, cell, cols, rows) -> list[list[tuple[int, int]]]:
    """Return a 2-D [row][col] matrix of screen coordinates."""
    ox, oy = origin
    cw, ch = cell
    return [[(ox + c * cw, oy + r * ch) for c in range(cols)]
            for r in range(rows)]


def build_serpentine(origin, cell, cols, rows) -> list[tuple[int, int, int]]:
    """Yield (row, col, (x,y)) in serpentine order – original AHK pattern."""
    mat = grid_points(origin, cell, cols, rows)
    out: list[tuple[int, int, int]] = []
    for c in range(cols):
        r_iter = range(rows) if c % 2 == 0 else range(rows - 1, -1, -1)
        for r in r_iter:
            out.append((r, c, mat[r][c]))  # type: ignore[list-item]
    return out


def build_row_major(origin, cell, cols, rows) -> list[tuple[int, int, int]]:
    mat = grid_points(origin, cell, cols, rows)
    return [(r, c, mat[r][c]) for r in range(rows) for c in range(cols)]  # type: ignore[list-item]


def filter_selected(points, selected: Iterable[tuple[int, int]]):
    """Keep only points whose (row, col) appears in `selected`.
    Empty `selected` means 'keep everything' (original behavior)."""
    sel = {tuple(p) for p in selected}
    if not sel:
        return points
    return [p for p in points if (p[0], p[1]) in sel]


# ---------------------------------------------------------------------------
# Slot profile loader
# ---------------------------------------------------------------------------

def load_slot_profile(profile_dir: Path, name: str) -> list[tuple[int, int]]:
    p = profile_dir / f"{name}.yaml"
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text()) or {}
    return [tuple(s) for s in data.get("slots") or []]


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------

@register
class InventoryDumpMacro(Macro):
    NAME = "inventory_dump"
    HOTKEYS = {
        "left":  "macros.inventory_dump.hotkeys.left",
        "right": "macros.inventory_dump.hotkeys.right",
    }

    def on_hotkey(self, action: str) -> None:
        if action == "left":
            self.start(lambda: self._sweep("left"))
        elif action == "right":
            self.start(lambda: self._sweep("right"))

    # ---- helpers ----
    def _resolve_origin(self) -> tuple[int, int]:
        tpl_name = self.cfg.get("macros.inventory_dump.anchor_template")
        fallback = tuple(self.cfg.get("macros.inventory_dump.grid.origin",
                                      [1988, 612]))
        if not tpl_name:
            return fallback  # type: ignore[return-value]
        try:
            from ..vision.capture import Capture
            from ..vision.detect import load_template, match_template
        except Exception:
            self.log.warning("vision deps unavailable; using origin")
            return fallback  # type: ignore[return-value]
        root = Path(self.cfg.get("vision.template_dir", "assets/templates"))
        tpl = load_template(root / tpl_name)
        if tpl is None:
            self.log.warning("anchor template %s not found; using origin", tpl_name)
            return fallback  # type: ignore[return-value]
        try:
            cap = Capture(self.cfg.get("vision.default_monitor", 1))
            frame = cap.grab()
            hit = match_template(frame, tpl,
                                 self.cfg.get("vision.match_threshold", 0.86))
            if hit:
                self.log.info("anchor matched at %s (score %.2f)", hit[:2], hit[2])
                return (hit[0], hit[1])
        except Exception:
            self.log.exception("anchor detection failed")
        return fallback  # type: ignore[return-value]

    def _effective_selection(self) -> list[tuple[int, int]]:
        """Resolve which slots to click: active slot profile wins; else
        the inline `selected_slots`; else empty = all."""
        prof_name = self.cfg.get("macros.inventory_dump.active_slot_profile")
        if prof_name:
            prof_dir = Path(self.cfg.get(
                "macros.inventory_dump.slot_profile_dir",
                "config/slot_profiles"))
            slots = load_slot_profile(prof_dir, prof_name)
            if slots:
                return slots
            self.log.warning("slot profile %r has no slots; falling back",
                             prof_name)
        return [tuple(s) for s in
                (self.cfg.get("macros.inventory_dump.selected_slots") or [])]

    # ---- core ----
    def _sweep(self, button: str) -> None:
        origin = self._resolve_origin()
        cell = tuple(self.cfg.get("macros.inventory_dump.grid.cell_size",
                                  [53, 55]))
        cols = self.cfg.get("macros.inventory_dump.grid.cols", 12)
        rows = self.cfg.get("macros.inventory_dump.grid.rows", 5)
        pattern = self.cfg.get("macros.inventory_dump.grid.pattern",
                               "serpentine")
        modifier = self.cfg.get("macros.inventory_dump.modifier", "ctrl")
        lo, hi = self.cfg.get("macros.inventory_dump.click_delay_ms", [30, 80])

        builder = build_serpentine if pattern == "serpentine" else build_row_major
        points = builder(origin, cell, cols, rows)
        selected = self._effective_selection()
        points = filter_selected(points, selected)
        total = len(points)
        if total == 0:
            self.log.info("no slots to click (empty selection?)")
            return

        self.log.info("sweep %s: %d of %d slots (pattern=%s, selection=%s)",
                      button, total, cols * rows, pattern,
                      "profile" if selected else "all")

        if modifier:
            self.sender.key_down(modifier)
        try:
            for i, (_r, _c, (x, y)) in enumerate(points, start=1):
                if self.should_abort():
                    self.log.warning("sweep aborted at %d/%d", i, total)
                    break
                self.sender.click(x, y, button=button)
                time.sleep(random.randint(lo, hi) / 1000.0)
        finally:
            if modifier:
                self.sender.key_up(modifier)
