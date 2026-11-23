"""What the area-select overlay draws, as plain data.

Built by the controller, painted by ``ui/area_select_overlay.py``.
Coordinates are physical screen pixels.

Mark kinds:
    occupied / empty / unknown   live drag, by item detection result
    pending                      in the plan, still to be clicked
    done                         in the plan, already clicked
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from .grid import GridGeometry, Rect, Slot
from .occupancy import SlotStats
from .selection import Selection
from .transfer import TransferPlan


@dataclass(frozen=True)
class SlotMark:
    rect: Rect
    kind: str
    index: Optional[int] = None      # 1-based click order, plan marks only


@dataclass(frozen=True)
class OverlayModel:
    drag_rect: Optional[Rect] = None
    marks: tuple[SlotMark, ...] = ()
    label: str = ""
    label_pos: Optional[tuple[float, float]] = None
    debug_bounds: tuple[Rect, ...] = ()

    @property
    def empty(self) -> bool:
        return self.drag_rect is None and not self.marks and not self.label


EMPTY = OverlayModel()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def drag_model(rect: Rect, selection: Optional[Selection],
               grids: Mapping[str, GridGeometry],
               occupancy: Mapping[str, Mapping[Slot, SlotStats]],
               debug: bool = False) -> OverlayModel:
    marks: list[SlotMark] = []
    label = "0 slots"
    if selection is not None:
        geom = grids[selection.grid]
        occ = occupancy.get(selection.grid) or {}
        items = 0
        known = bool(occ)
        for s in selection.slots:
            st = occ.get(s)
            if st is None:
                kind = "unknown"
            elif st.occupied:
                kind = "occupied"
                items += 1
            else:
                kind = "empty"
            marks.append(SlotMark(geom.slot_rect(s), kind))
        label = _plural(len(selection.slots), "slot")
        if known:
            label += f" · {_plural(items, 'item')}"
    bounds = tuple(g.bounds() for g in grids.values()) if debug else ()
    return OverlayModel(drag_rect=rect, marks=tuple(marks), label=label,
                        label_pos=(rect.right, rect.bottom),
                        debug_bounds=bounds)


def plan_model(plan: TransferPlan, remaining: Sequence[Slot], mode: str,
               debug: bool = False) -> OverlayModel:
    left = set(remaining)
    marks = tuple(
        SlotMark(plan.geometry.slot_rect(s),
                 "pending" if s in left else "done",
                 i + 1 if s in left else None)
        for i, s in enumerate(plan.slots))
    total = len(plan.slots)
    done = total - len(left)
    if mode == "manual":
        label = f"Ctrl-click the highlighted slots · {len(left)} of {total} left"
    else:
        label = f"Transferring {done}/{total} · Esc to stop"
    b = plan.geometry.bounds()
    return OverlayModel(marks=marks, label=label, label_pos=(b.right, b.bottom),
                        debug_bounds=(b,) if debug else ())
