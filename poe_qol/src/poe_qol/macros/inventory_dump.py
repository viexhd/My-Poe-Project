"""Inventory sweep – Ctrl-click every slot in the player inventory.

Source: `inventory.ahk` + `poe mini project/autoclicker.cpp`.

Improvements:
    * grid origin / size / dims all come from config (no hard-coded
      1988/612/53/55/12/5).
    * pattern is selectable (serpentine matches original, row_major
      is simpler to reason about).
    * optional vision anchor: if `anchor_template` is set, we run
      template matching on the current frame to locate the first slot
      and use that as origin — makes it resolution-independent.
    * single re-entrancy guard shared with other macros via AppState.
"""
from __future__ import annotations

import random
import time
from pathlib import Path

from ..engine.macro import Macro
from ..engine.registry import register

# NOTE: vision imports are deferred to `_resolve_origin` so this macro
# can still be loaded in environments where opencv/numpy aren't
# installed (e.g. headless CI).


def build_serpentine(origin, cell, cols, rows) -> list[tuple[int, int]]:
    ox, oy = origin
    cw, ch = cell
    pts: list[tuple[int, int]] = []
    for c in range(cols):
        x = ox + c * cw
        col_range = range(rows) if c % 2 == 0 else range(rows - 1, -1, -1)
        for r in col_range:
            pts.append((x, oy + r * ch))
    return pts


def build_row_major(origin, cell, cols, rows) -> list[tuple[int, int]]:
    ox, oy = origin
    cw, ch = cell
    return [(ox + c * cw, oy + r * ch) for r in range(rows) for c in range(cols)]


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

    # ---- internals ----
    def _resolve_origin(self) -> tuple[int, int]:
        """If a template is configured and matches, use it — else fall
        back to the explicit origin from config."""
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
        total = len(points)
        self.log.info("sweep %s: %d slots (%s)", button, total, pattern)

        if modifier:
            self.sender.key_down(modifier)
        try:
            for i, (x, y) in enumerate(points, start=1):
                if self.should_abort():
                    self.log.warning("sweep aborted at %d/%d", i, total)
                    break
                self.sender.click(x, y, button=button)
                time.sleep(random.randint(lo, hi) / 1000.0)
        finally:
            if modifier:
                self.sender.key_up(modifier)
