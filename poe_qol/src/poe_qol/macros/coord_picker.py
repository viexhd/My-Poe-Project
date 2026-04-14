"""Developer utility: capture cursor coordinates on demand.

Source: `getcoords.ahk`.  Writes to a JSON file so captured points
survive across sessions and can be pasted into a profile.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..engine.macro import Macro
from ..engine.registry import register

try:
    import pydirectinput as _di  # type: ignore
except Exception:  # pragma: no cover
    _di = None


@register
class CoordPickerMacro(Macro):
    NAME = "coord_picker"
    HOTKEYS = {
        "capture": "macros.coord_picker.hotkeys.capture",
        "show":    "macros.coord_picker.hotkeys.show",
    }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._points: list[tuple[int, int]] = []
        self._load()

    def on_hotkey(self, action: str) -> None:
        if action == "capture":
            self._capture()
        elif action == "show":
            self._show()

    def _path(self) -> Path:
        return Path(self.cfg.get("macros.coord_picker.save_to",
                                 "logs/coords.json"))

    def _load(self) -> None:
        p = self._path()
        if p.exists():
            try:
                self._points = [tuple(pt) for pt in json.loads(p.read_text())]
            except Exception:
                self._points = []

    def _save(self) -> None:
        p = self._path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._points))

    def _capture(self) -> None:
        if not _di:
            self.log.warning("input backend missing; cannot read cursor")
            return
        x, y = _di.position()
        self._points.append((x, y))
        self._save()
        self.log.info("captured #%d -> (%d, %d)", len(self._points), x, y)

    def _show(self) -> None:
        if not self._points:
            self.log.info("no coords captured")
            return
        for i, (x, y) in enumerate(self._points, 1):
            self.log.info("%d: (%d, %d)", i, x, y)
