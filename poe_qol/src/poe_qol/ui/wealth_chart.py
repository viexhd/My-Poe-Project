"""Wealth over time: a line (Total) or bars (Hourly), painted by hand so
the app needs no QtCharts. Hover shows the nearest point."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from . import styles as S


def _nice(v: float) -> str:
    a = abs(v)
    if a >= 10_000:
        return f"{v / 1000:,.0f}k"
    if a >= 1000:
        return f"{v / 1000:,.1f}k"
    if a >= 100:
        return f"{v:,.0f}"
    return f"{v:,.1f}"


class WealthChart(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self._points: list[tuple[float, float]] = []
        self._mode = "total"
        self._unit = "div"
        self._empty = "No syncs in this range yet."

    def set_data(self, points: list[tuple[float, float]], *, mode: str,
                 unit: str, empty: str = "") -> None:
        self._points = sorted(points)
        self._mode = mode
        self._unit = unit
        if empty:
            self._empty = empty
        self.update()

    def points(self) -> list[tuple[float, float]]:
        return list(self._points)

    # ---- geometry ----
    def _plot(self) -> QRectF:
        return QRectF(56, 24, max(10, self.width() - 72), max(10, self.height() - 52))

    def _ranges(self):
        xs = [p[0] for p in self._points]
        ys = [p[1] for p in self._points]
        x0, x1 = min(xs), max(xs)
        if x1 - x0 < 60:
            x0, x1 = x0 - 1800, x1 + 1800
        if self._mode == "hourly":
            # half a slot of room so the outer bars stay inside the plot
            half = (x1 - x0) / max(1, len(xs) - 1) / 2
            x0, x1 = x0 - half, x1 + half
        y0, y1 = min(ys), max(ys)
        if self._mode == "hourly":
            y0, y1 = min(y0, 0.0), max(y1, 0.0)
        if y1 - y0 < 1e-9:
            pad = abs(y1) * 0.05 or 1.0
            y0, y1 = y0 - pad, y1 + pad
        pad = (y1 - y0) * 0.08
        if self._mode != "hourly" or y0 < 0:
            y0 -= pad
        y1 += pad
        return x0, x1, y0, y1

    def _map(self, x: float, y: float, r: QRectF, rg) -> QPointF:
        x0, x1, y0, y1 = rg
        return QPointF(r.left() + (x - x0) / (x1 - x0) * r.width(),
                       r.bottom() - (y - y0) / (y1 - y0) * r.height())

    # ---- painting ----
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot()
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() * 0.85))
        p.setFont(f)
        if not self._points:
            p.setPen(QColor(S.FG_2))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty)
            return
        rg = self._ranges()
        x0, x1, y0, y1 = rg

        # grid + y labels
        for i in range(5):
            y = y0 + (y1 - y0) * i / 4
            pt = self._map(x0, y, r, rg)
            p.setPen(QPen(QColor(S.LINE), 1))
            p.drawLine(QPointF(r.left(), pt.y()), QPointF(r.right(), pt.y()))
            p.setPen(QColor(S.FG_2))
            p.drawText(QRectF(0, pt.y() - 9, r.left() - 8, 18),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       _nice(y))
        # x labels
        span = x1 - x0
        fmt = "%H:%M" if span <= 36 * 3600 else "%d %b"
        for i in range(5):
            x = x0 + span * i / 4
            pt = self._map(x, y0, r, rg)
            p.drawText(QRectF(pt.x() - 40, r.bottom() + 6, 80, 18),
                       Qt.AlignmentFlag.AlignHCenter,
                       datetime.fromtimestamp(x).strftime(fmt))
        p.drawText(QRectF(0, 0, r.left() - 8, 16), Qt.AlignmentFlag.AlignRight,
                   self._unit if self._mode == "total" else f"{self._unit}/h")

        if self._mode == "hourly":
            zero = self._map(x0, 0.0, r, rg).y()
            p.setPen(QPen(QColor(S.LINE_STRONG), 1))
            p.drawLine(QPointF(r.left(), zero), QPointF(r.right(), zero))
            n = len(self._points)
            w = max(3.0, min(28.0, r.width() / max(1, n) * 0.6))
            p.setPen(Qt.PenStyle.NoPen)
            for x, y in self._points:
                pt = self._map(x, y, r, rg)
                p.setBrush(QColor(S.SUCCESS if y >= 0 else S.DANGER))
                top, bot = sorted((pt.y(), zero))
                p.drawRoundedRect(QRectF(pt.x() - w / 2, top, w, max(1.0, bot - top)),
                                  2, 2)
            return

        path = QPainterPath()
        pts = [self._map(x, y, r, rg) for x, y in self._points]
        path.moveTo(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        area = QPainterPath(path)
        area.lineTo(QPointF(pts[-1].x(), r.bottom()))
        area.lineTo(QPointF(pts[0].x(), r.bottom()))
        area.closeSubpath()
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        top = QColor(S.ACCENT); top.setAlpha(70)
        bot = QColor(S.ACCENT); bot.setAlpha(0)
        grad.setColorAt(0, top)
        grad.setColorAt(1, bot)
        p.fillPath(area, grad)
        p.setPen(QPen(QColor(S.ACCENT), 2))
        p.drawPath(path)
        p.setBrush(QColor(S.ACCENT))
        p.setPen(Qt.PenStyle.NoPen)
        for pt in pts if len(pts) <= 60 else pts[-1:]:
            p.drawEllipse(pt, 3, 3)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self._points:
            return
        r, rg = self._plot(), self._ranges()
        x = e.position().x()
        best = min(self._points, key=lambda pt: abs(self._map(*pt, r, rg).x() - x))
        when = datetime.fromtimestamp(best[0]).strftime("%a %d %b %H:%M")
        unit = self._unit if self._mode == "total" else f"{self._unit}/h"
        sign = "+" if self._mode == "hourly" and best[1] > 0 else ""
        QToolTip.showText(e.globalPosition().toPoint(),
                          f"{when}\n{sign}{best[1]:,.2f} {unit}", self)
