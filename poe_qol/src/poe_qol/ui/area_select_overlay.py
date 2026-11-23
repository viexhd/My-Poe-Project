"""Click-through overlay for the Alt+drag area selection.

Paints an ``OverlayModel`` (selection rectangle, slot marks, count
label). It never takes focus or mouse input (Qt
``WindowTransparentForInput``), so the game keeps receiving the cursor,
and on Windows 10 2004+ it excludes itself from screen capture
(``SetWindowDisplayAffinity``) so item detection never sees our own
highlights. Hidden whenever there is nothing to draw.

The model is in physical screen pixels; the overlay divides by the
device pixel ratio so highlights line up under Windows display scaling.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..area_select.grid import Rect
from ..area_select.overlay_model import EMPTY, OverlayModel
from ..area_select.settings import OverlaySettings
from .styles import ACCENT, BG_0, FG_0, FG_2, INFO, SUCCESS

WDA_EXCLUDEFROMCAPTURE = 0x11


def _c(hex_: str, alpha: int) -> QColor:
    c = QColor(hex_)
    c.setAlpha(alpha)
    return c


class AreaSelectOverlay(QWidget):
    def __init__(self, settings: OverlaySettings) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("Area select overlay")
        self._settings = settings
        self._model: OverlayModel = EMPTY
        self._frame = Rect(0, 0, 1, 1)
        self._dpr = 1.0
        self._affinity_set = False

    # ---- configuration ----
    def set_settings(self, settings: OverlaySettings) -> None:
        self._settings = settings
        self.update()

    def set_frame(self, frame: Rect, dpr: float) -> None:
        """Cover ``frame`` (physical px) on a screen with ``dpr``."""
        self._dpr = dpr or 1.0
        d = self._dpr
        x, y = int(frame.left / d), int(frame.top / d)
        # Paint relative to where the window actually lands (whole px).
        self._frame = frame.translated(x * d - frame.left, y * d - frame.top)
        self.setGeometry(x, y,
                         max(1, int(round(frame.width / d))),
                         max(1, int(round(frame.height / d))))

    def set_model(self, model: OverlayModel) -> None:
        self._model = model
        if model.empty:
            self.hide()
            return
        if not self.isVisible():
            self.show()
            self._exclude_from_capture()
        self.update()

    def _exclude_from_capture(self) -> None:
        if self._affinity_set or not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            ctypes.windll.user32.SetWindowDisplayAffinity(
                int(self.winId()), WDA_EXCLUDEFROMCAPTURE)
            self._affinity_set = True
        except Exception:
            pass

    # ---- painting ----
    def _local(self, r: Rect) -> QRectF:
        d = self._dpr
        return QRectF((r.left - self._frame.left) / d, (r.top - self._frame.top) / d,
                      r.width / d, r.height / d)

    def paintEvent(self, _e) -> None:  # noqa: N802
        m = self._model
        if m.empty:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        for b in m.debug_bounds:
            p.setPen(QPen(_c(INFO, 200), 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self._local(b))

        for mark in m.marks:
            r = self._local(mark.rect).adjusted(2, 2, -2, -2)
            if mark.kind == "empty":
                pen = QPen(_c(FG_2, 200), 1, Qt.PenStyle.DashLine)
                brush = _c(FG_2, 25)
            elif mark.kind == "done":
                pen = QPen(_c(SUCCESS, 160), 1)
                brush = _c(SUCCESS, 35)
            elif mark.kind == "pending":
                pen = QPen(_c(ACCENT, 240), 2)
                brush = _c(ACCENT, 60)
            else:                       # occupied / unknown
                pen = QPen(_c(ACCENT, 230), 2)
                brush = _c(ACCENT, 90 if mark.kind == "occupied" else 55)
            p.setPen(pen)
            p.setBrush(brush)
            p.drawRoundedRect(r, 4, 4)
            if mark.index is not None:
                p.setPen(_c(FG_0, 230))
                f = QFont(p.font())
                f.setPointSizeF(max(7.0, r.height() / 4.5))
                f.setBold(True)
                p.setFont(f)
                p.drawText(r.adjusted(3, 1, 0, 0),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                           str(mark.index))

        if m.drag_rect is not None:
            s = self._settings
            p.setPen(QPen(_c(ACCENT, 255), s.border_px))
            p.setBrush(_c(ACCENT, int(round(s.fill_opacity * 255))))
            p.drawRect(self._local(m.drag_rect))

        if m.label and m.label_pos is not None:
            self._draw_label(p, m.label, m.label_pos)
        p.end()

    def _draw_label(self, p: QPainter, text: str, pos: tuple[float, float]) -> None:
        f = QFont(p.font())
        f.setPointSizeF(10)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 16
        h = fm.height() + 8
        x = (pos[0] - self._frame.left) / self._dpr + 8
        y = (pos[1] - self._frame.top) / self._dpr + 8
        x = min(max(0.0, x), self.width() - w)    # keep on screen
        y = min(max(0.0, y), self.height() - h)
        box = QRectF(x, y, w, h)
        p.setPen(QPen(_c(ACCENT, 220), 1))
        p.setBrush(_c(BG_0, 225))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor(FG_0))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
