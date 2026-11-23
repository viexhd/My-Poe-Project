"""Optional empty / occupied slot detection from a screenshot.

Heuristic, no game data is read: an empty PoE inventory cell is dark
and nearly flat; an item's art is brighter and/or textured. For each
slot the centre of the cell (``inset`` trimmed from each side, which
skips grid lines and stack-size digits in the corner) is converted to
luminance and judged by its mean and standard deviation.

Needs numpy (and mss for ``capture_grid``), both in the ``vision``
extra. Without them detection reports nothing and every slot is
treated as "unknown", so the feature still works.

Tune ``area_select.occupancy.std_min`` / ``mean_min`` with debug mode
on: the per-slot statistics are written to the log.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .grid import GridGeometry, Slot

log = logging.getLogger("poe_qol.area_select.occupancy")


@dataclass(frozen=True)
class OccupancyThresholds:
    std_min: float = 14.0     # luminance std-dev at/above which a slot is occupied
    mean_min: float = 70.0    # mean luminance at/above which a slot is occupied
    inset: float = 0.2        # fraction trimmed from each side of the cell


@dataclass(frozen=True)
class SlotStats:
    mean: float
    std: float
    occupied: bool


def classify_slots(image: Any, image_origin: tuple[int, int],
                   geometry: GridGeometry, slots: Iterable[Slot],
                   thresholds: OccupancyThresholds) -> dict[Slot, SlotStats]:
    """Classify ``slots`` using a BGR ``image`` whose top-left pixel is
    at screen position ``image_origin``. Slots not fully inside the
    image are left out (unknown) rather than guessed."""
    import numpy as np

    h, w = image.shape[:2]
    ix, iy = image_origin
    out: dict[Slot, SlotStats] = {}
    for slot in slots:
        r = geometry.slot_rect(slot)
        dx = r.width * thresholds.inset
        dy = r.height * thresholds.inset
        x0 = int(round(r.left + dx - ix))
        x1 = int(round(r.right - dx - ix))
        y0 = int(round(r.top + dy - iy))
        y1 = int(round(r.bottom - dy - iy))
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h or x1 <= x0 or y1 <= y0:
            continue
        patch = image[y0:y1, x0:x1, :3].astype(np.float32)
        lum = patch[..., 0] * 0.114 + patch[..., 1] * 0.587 + patch[..., 2] * 0.299
        mean = float(lum.mean())
        std = float(lum.std())
        occupied = std >= thresholds.std_min or mean >= thresholds.mean_min
        out[slot] = SlotStats(mean, std, occupied)
    return out


def capture_grid(geometry: GridGeometry) -> Optional[tuple[Any, tuple[int, int]]]:
    """Screenshot of the grid area as ``(bgr_image, (left, top))``, or
    None when screen capture is unavailable."""
    try:
        from ..vision.capture import Capture, Region
    except Exception:
        return None
    b = geometry.bounds()
    left, top = int(b.left), int(b.top)
    region = Region(left, top, int(round(b.width)) + 1, int(round(b.height)) + 1)
    try:
        return Capture().grab(region), (left, top)
    except Exception:
        log.debug("grid capture failed", exc_info=True)
        return None
