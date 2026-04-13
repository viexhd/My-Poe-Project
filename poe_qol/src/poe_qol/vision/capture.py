"""Screen capture helper around mss. Returns BGR ndarrays so OpenCV
can consume them directly."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import mss  # type: ignore
except Exception:  # pragma: no cover
    mss = None


@dataclass
class Region:
    left: int
    top: int
    width: int
    height: int

    def as_dict(self) -> dict:
        return {"left": self.left, "top": self.top,
                "width": self.width, "height": self.height}


class Capture:
    def __init__(self, monitor_index: int = 1):
        self.monitor_index = monitor_index
        self._sct = mss.mss() if mss else None

    def grab(self, region: Region | None = None) -> np.ndarray:
        if not self._sct:
            raise RuntimeError("mss not available")
        if region is None:
            mon = self._sct.monitors[self.monitor_index]
        else:
            mon = region.as_dict()
        raw = self._sct.grab(mon)
        # BGRA -> BGR
        img = np.asarray(raw)[:, :, :3]
        return img
