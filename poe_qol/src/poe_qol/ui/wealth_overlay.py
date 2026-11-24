"""Small always-on-top "divine per hour" overlay.

Frameless, translucent, draggable. It only *displays* a number, sends
no input to the game and reads no screen, clipboard or log data, so
GGG's overlay rules don't restrict it. Works over the game in windowed
or windowed-fullscreen mode (not exclusive fullscreen).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

from ..economy.wealth_rate import RateReading
from .text import capitalise

try:  # design tokens from the theme (fallbacks keep this importable)
    from .styles import ACCENT, BG_0, FG_1, FG_2, LINE_STRONG
except Exception:  # pragma: no cover
    BG_0, LINE_STRONG, ACCENT, FG_1, FG_2 = (
        "#0D0A0B", "#4A363C", "#D9B25A", "#BEB0A4", "#85776E")


def _fmt(v: float, digits: int = 2) -> str:
    return f"{v:,.{digits}f}"


class WealthOverlay(QWidget):
    refresh_requested = Signal()
    hide_requested = Signal()
    moved = Signal(QPoint)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("Divine Per Hour")
        self._drag_from: QPoint | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        self._headline = QLabel("— div/h")
        self._headline.setStyleSheet(
            f"color:{ACCENT}; font-size:20px; font-weight:600; background:transparent;")
        self._detail = QLabel("")
        self._detail.setStyleSheet(
            f"color:{FG_1}; font-size:11px; background:transparent;")
        self._source = QLabel("Wealthy Exile CSV")
        self._source.setStyleSheet(
            f"color:{FG_2}; font-size:10px; background:transparent;")
        for w in (self._headline, self._detail, self._source):
            lay.addWidget(w)
        self.setToolTip("Drag To Move · Right-Click For Options")

    # ---- content ----
    def show_reading(self, r: RateReading) -> None:
        if r.divine_per_hour is not None:
            self._headline.setText(f"{_fmt(r.divine_per_hour)} div/h")
        elif r.chaos_per_hour is not None:
            self._headline.setText(f"{_fmt(r.chaos_per_hour, 0)} c/h")
        else:
            self._headline.setText("— div/h")
        bits: list[str] = []
        if r.divine_per_hour is not None and r.chaos_per_hour is not None:
            bits.append(f"≈ {_fmt(r.chaos_per_hour, 0)} c/h")
        if r.span_minutes:
            bits.append(f"{r.snapshots_used} exports, {r.span_minutes:.0f} min apart")
        if r.latest_at:
            bits.append(f"latest {r.latest_at:%H:%M}")
        if r.message:
            bits.append(r.message)
        self._detail.setText(capitalise(" · ".join(bits)))
        if r.source:
            self._source.setText(r.source)
        self.adjustSize()

    def headline_text(self) -> str:
        return self._headline.text()

    def detail_text(self) -> str:
        return self._detail.text()

    # ---- painting / interaction ----
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(BG_0)
        bg.setAlpha(225)
        p.setBrush(bg)
        p.setPen(QPen(QColor(LINE_STRONG), 1))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = (e.globalPosition().toPoint()
                               - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag_from is not None:
            self.move(e.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        if self._drag_from is not None:
            self._drag_from = None
            self.moved.emit(self.pos())

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        menu = QMenu(self)
        refresh = QAction("Refresh Now", menu)
        refresh.triggered.connect(self.refresh_requested.emit)
        hide = QAction("Hide Overlay", menu)
        hide.triggered.connect(self.hide_requested.emit)
        menu.addAction(refresh)
        menu.addAction(hide)
        menu.exec(e.globalPos())
