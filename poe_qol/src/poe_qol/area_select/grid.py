"""Inventory grid mapping: screen coordinates <-> (row, col) slots.

Pure geometry. All coordinates are *physical* screen pixels, the same
space the Win32 mouse hook, GetCursorPos and the input sender use.

Calibration lives in a config section such as ``macros.inventory_dump``
(written by the Calibrate dialog)::

    grid:
      origin: [x, y]          # centre of slot (0, 0)
      cell_size: [w, h]       # slot pitch, may be fractional
      cols: 12
      rows: 5
      bounds: null            # optional [left, top, right, bottom] outer
                              # edges; overrides origin + cell_size
    origin_relative_to_window:  # optional, wins when the window is found
      anchor: top_right
      offset: [dx, dy]
      window_size: [w, h]     # window size at calibration time; enables
                              # scaling when the resolution changes
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional

Slot = tuple[int, int]   # (row, col), 0-indexed


@dataclass(frozen=True)
class Rect:
    left: float
    top: float
    right: float
    bottom: float

    @classmethod
    def from_points(cls, x0: float, y0: float, x1: float, y1: float) -> "Rect":
        """Rectangle spanned by two corners, in any drag direction."""
        return cls(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    def expanded(self, margin: float) -> "Rect":
        return Rect(self.left - margin, self.top - margin,
                    self.right + margin, self.bottom + margin)

    def translated(self, dx: float, dy: float) -> "Rect":
        return Rect(self.left + dx, self.top + dy,
                    self.right + dx, self.bottom + dy)


@dataclass(frozen=True)
class GridGeometry:
    origin: tuple[float, float]   # centre of slot (0, 0)
    cell: tuple[float, float]     # (w, h) slot pitch
    cols: int
    rows: int

    def __post_init__(self) -> None:
        if self.cols < 1 or self.rows < 1:
            raise ValueError(f"grid needs at least 1x1 slots, got "
                             f"{self.cols}x{self.rows}")
        if self.cell[0] <= 0 or self.cell[1] <= 0:
            raise ValueError(f"cell size must be positive, got {self.cell}")

    @classmethod
    def from_bounds(cls, bounds: Rect, cols: int, rows: int) -> "GridGeometry":
        cw = bounds.width / cols
        ch = bounds.height / rows
        return cls(origin=(bounds.left + cw / 2, bounds.top + ch / 2),
                   cell=(cw, ch), cols=cols, rows=rows)

    # ---- per slot ----
    def slot_center(self, slot: Slot) -> tuple[float, float]:
        r, c = slot
        return (self.origin[0] + c * self.cell[0],
                self.origin[1] + r * self.cell[1])

    def slot_rect(self, slot: Slot) -> Rect:
        cx, cy = self.slot_center(slot)
        hw, hh = self.cell[0] / 2, self.cell[1] / 2
        return Rect(cx - hw, cy - hh, cx + hw, cy + hh)

    def all_slots(self) -> list[Slot]:
        return [(r, c) for r in range(self.rows) for c in range(self.cols)]

    # ---- whole grid ----
    def bounds(self) -> Rect:
        hw, hh = self.cell[0] / 2, self.cell[1] / 2
        return Rect(self.origin[0] - hw, self.origin[1] - hh,
                    self.origin[0] - hw + self.cols * self.cell[0],
                    self.origin[1] - hh + self.rows * self.cell[1])

    def slot_at(self, x: float, y: float) -> Optional[Slot]:
        """Slot whose cell contains the point, or None outside the grid."""
        b = self.bounds()
        if not b.contains(x, y):
            return None
        c = min(self.cols - 1, int((x - b.left) // self.cell[0]))
        r = min(self.rows - 1, int((y - b.top) // self.cell[1]))
        return (r, c)

    def slots_in_rect(self, rect: Rect) -> list[Slot]:
        """Slots whose *centre* lies inside ``rect`` (inclusive), in
        row-major order. Only the overlapping index range is scanned."""
        ox, oy = self.origin
        cw, ch = self.cell
        c0 = max(0, math.ceil((rect.left - ox) / cw))
        c1 = min(self.cols - 1, math.floor((rect.right - ox) / cw))
        r0 = max(0, math.ceil((rect.top - oy) / ch))
        r1 = min(self.rows - 1, math.floor((rect.bottom - oy) / ch))
        if c0 > c1 or r0 > r1:
            return []
        return [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]


def resolve_geometry(section: Mapping[str, Any],
                     window: Any = None) -> GridGeometry:
    """Build the live geometry from a calibrated config section.

    ``window`` is a ``vision.window.WindowRect`` (or None when the game
    window was not found). Resolution order:

    1. ``origin_relative_to_window`` when a window is given. If the
       calibration recorded ``window_size``, offset and cell size are
       scaled by the window-height ratio (PoE scales its UI by height).
    2. ``grid.bounds`` (outer edges, absolute).
    3. ``grid.origin`` + ``grid.cell_size`` (absolute).
    """
    grid = section.get("grid") or {}
    cols = int(grid.get("cols", 12))
    rows = int(grid.get("rows", 5))
    cw, ch = (float(v) for v in grid.get("cell_size", (53, 55)))

    rel = section.get("origin_relative_to_window")
    if rel and window is not None:
        scale = 1.0
        size = rel.get("window_size")
        if size and float(size[1]) > 0 and window.height > 0:
            scale = window.height / float(size[1])
        ax, ay = window.anchor(rel.get("anchor", "top_left"))
        dx, dy = (float(v) for v in rel.get("offset", (0, 0)))
        return GridGeometry(origin=(ax + dx * scale, ay + dy * scale),
                            cell=(cw * scale, ch * scale),
                            cols=cols, rows=rows)

    bounds = grid.get("bounds")
    if bounds:
        return GridGeometry.from_bounds(Rect(*(float(v) for v in bounds)),
                                        cols=cols, rows=rows)

    ox, oy = (float(v) for v in grid.get("origin", (0, 0)))
    return GridGeometry(origin=(ox, oy), cell=(cw, ch), cols=cols, rows=rows)


def load_geometry(cfg: Any, namespace: str) -> GridGeometry:
    """Resolve the geometry of ``namespace`` (e.g. ``macros.inventory_dump``)
    against the current game window, if one is found."""
    section = cfg.get(namespace) or {}
    window = None
    if section.get("origin_relative_to_window"):
        try:
            from ..vision.window import find_window
            win_cfg = section.get("window") or {}
            window = find_window(win_cfg.get("title_pattern", "Path of Exile"),
                                 win_cfg.get("class_pattern"))
        except Exception:
            window = None
    return resolve_geometry(section, window)
