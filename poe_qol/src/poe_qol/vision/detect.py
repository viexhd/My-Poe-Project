"""Detection primitives built on OpenCV.

Kept deliberately small — three building blocks that every macro can
compose:
    * match_template  → (x, y, score) of best match or None
    * pixel_is        → True if a pixel is close enough to an RGB value
    * find_all        → all matches above threshold (for grid anchors)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def match_template(haystack: np.ndarray, template: np.ndarray,
                   threshold: float = 0.86) -> Optional[tuple[int, int, float]]:
    if haystack is None or template is None:
        return None
    res = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < threshold:
        return None
    h, w = template.shape[:2]
    cx, cy = max_loc[0] + w // 2, max_loc[1] + h // 2
    return (cx, cy, float(max_val))


def find_all(haystack: np.ndarray, template: np.ndarray,
             threshold: float = 0.86) -> list[tuple[int, int, float]]:
    res = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    h, w = template.shape[:2]
    out = [(int(x + w // 2), int(y + h // 2), float(res[y, x]))
           for x, y in zip(xs, ys)]
    return out


def pixel_is(img: np.ndarray, x: int, y: int,
             expected_bgr: tuple[int, int, int], tol: int = 10) -> bool:
    b, g, r = img[y, x]
    eb, eg, er = expected_bgr
    return (abs(int(b) - eb) <= tol
            and abs(int(g) - eg) <= tol
            and abs(int(r) - er) <= tol)


def load_template(path: str | Path) -> Optional[np.ndarray]:
    p = Path(path)
    if not p.exists():
        return None
    return cv2.imread(str(p), cv2.IMREAD_COLOR)
