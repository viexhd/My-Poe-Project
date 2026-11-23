"""Selection state: the drag rectangle and what it selects.

``DragSelector`` is a tiny state machine (idle -> dragging -> idle).
``resolve_selection`` turns a finished rectangle into slots on one of
the configured grids.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from .grid import GridGeometry, Rect, Slot


class DragSelector:
    def __init__(self) -> None:
        self._start: Optional[tuple[float, float]] = None
        self._rect: Optional[Rect] = None

    @property
    def active(self) -> bool:
        return self._start is not None

    @property
    def rect(self) -> Optional[Rect]:
        return self._rect

    def press(self, x: float, y: float) -> None:
        self._start = (x, y)
        self._rect = Rect(x, y, x, y)

    def move(self, x: float, y: float) -> Optional[Rect]:
        if self._start is None:
            return None
        self._rect = Rect.from_points(*self._start, x, y)
        return self._rect

    def release(self, x: float, y: float) -> Optional[Rect]:
        rect = self.move(x, y)
        self._start = None
        self._rect = None
        return rect

    def cancel(self) -> None:
        self._start = None
        self._rect = None


@dataclass(frozen=True)
class Selection:
    grid: str                    # config namespace of the grid
    slots: tuple[Slot, ...]      # row-major
    rect: Rect
    is_click: bool               # a click (no real drag) on one slot


def resolve_selection(rect: Rect, grids: Mapping[str, GridGeometry],
                      click_threshold_px: float) -> Optional[Selection]:
    """Slots selected by ``rect``.

    A rectangle no bigger than ``click_threshold_px`` in both directions
    counts as a click and selects the slot under it. Otherwise the grid
    with the most slot centres inside the rectangle wins (ties: first
    configured grid).
    """
    if rect.width <= click_threshold_px and rect.height <= click_threshold_px:
        x, y = rect.center
        for name, geom in grids.items():
            slot = geom.slot_at(x, y)
            if slot is not None:
                return Selection(name, (slot,), rect, True)
        return None

    best: Optional[Selection] = None
    for name, geom in grids.items():
        slots = geom.slots_in_rect(rect)
        if slots and (best is None or len(slots) > len(best.slots)):
            best = Selection(name, tuple(slots), rect, False)
    return best
