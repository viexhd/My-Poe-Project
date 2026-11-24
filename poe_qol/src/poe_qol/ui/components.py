"""Reusable dashboard building blocks.

The app's look: a sidebar, then pages made of large rounded cards with
big numbers and short labels. Explanations live behind a small round
"?" badge (:class:`HelpBadge`) beside the thing they explain, so the
pages stay light on words.

    Page        – title + "?" + optional actions, then a scrollable body
    Card        – rounded surface; ``card(title, help)`` adds a header row
    StatCard    – small label, big value, optional caption
    Switch      – a pill toggle (a QCheckBox, so the usual API works)
    HelpBadge   – the "?"; hover or click shows the explanation
    field()     – a small label (with "?") stacked above an input
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt,
    Property,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLayout, QLayoutItem, QScrollArea,
    QSizePolicy, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from . import styles as S


# ---- "?" help badge ------------------------------------------------------

class HelpBadge(QToolButton):
    """Small round "?" that explains the control next to it.

    Hover shows the text as a tooltip; clicking shows it immediately
    (handy on touchpads, where hovering is awkward).
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HelpBadge")
        self.setText("?")
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.set_help(text)
        self.clicked.connect(self._show)

    def set_help(self, text: str) -> None:
        self.help_text = text
        self.setToolTip(f"<div style='max-width:320px'>{text}</div>")
        self.setAccessibleName("Help")
        self.setAccessibleDescription(_plain(text))

    def _show(self) -> None:
        QToolTip.showText(self.mapToGlobal(QPoint(self.width() + 4, 0)),
                          self.toolTip(), self)


def _plain(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html)


def with_help(widget: QWidget, text: str, *, stretch: bool = False) -> QWidget:
    """``widget`` followed by a "?" badge, as one row widget."""
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(widget, 1 if stretch else 0)
    row.addWidget(HelpBadge(text), 0, Qt.AlignmentFlag.AlignVCenter)
    if not stretch:
        row.addStretch(1)
    return host


# ---- cards ---------------------------------------------------------------

class Card(QFrame):
    """Rounded surface. ``variant`` = "", "danger" or "gilt"."""

    def __init__(self, parent: QWidget | None = None, *, variant: str = "",
                 padding: int = 20, spacing: int = 14) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        if variant:
            self.setProperty("variant", variant)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding - 2, padding, padding)
        self.body.setSpacing(spacing)


def card(title: str | None = None, help: str | None = None, *,
         variant: str = "", right: QWidget | QLayout | None = None,
         icon: str | None = None, padding: int = 20
         ) -> tuple[Card, QVBoxLayout]:
    """A Card with an optional "Title (?) ........ [right]" header.

    Returns ``(card, body_layout)``; add content to the layout.
    """
    c = Card(variant=variant, padding=padding)
    if title or right is not None:
        head = QHBoxLayout()
        head.setSpacing(8)
        if icon:
            from .icons import pixmap
            ic = QLabel()
            ic.setPixmap(pixmap(icon, S.FG_1, 18))
            head.addWidget(ic)
        if title:
            t = QLabel(title)
            t.setObjectName("CardTitle")
            head.addWidget(t)
        if help:
            head.addWidget(HelpBadge(help))
        head.addStretch(1)
        if isinstance(right, QLayout):
            head.addLayout(right)
        elif right is not None:
            head.addWidget(right)
        c.body.addLayout(head)
    return c, c.body


class StatCard(Card):
    """LABEL (?) / big value / caption."""

    def __init__(self, label: str, value: str = "—", *, help: str | None = None,
                 sub: str = "", hero: bool = False, variant: str = "",
                 icon: str | None = None, accent: str | None = None) -> None:
        super().__init__(variant=variant, spacing=6)
        head = QHBoxLayout()
        head.setSpacing(8)
        if icon:
            from .icons import pixmap
            ic = QLabel()
            ic.setPixmap(pixmap(icon, accent or S.FG_2, 16))
            head.addWidget(ic)
        self.label = QLabel(label.upper())
        self.label.setObjectName("StatLabel")
        head.addWidget(self.label)
        if help:
            self.help = HelpBadge(help)
            head.addWidget(self.help)
        head.addStretch(1)
        self.body.addLayout(head)

        self.value = QLabel(value)
        self.value.setObjectName("HeroValue" if hero else "StatValue")
        self.value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        if accent and not hero:
            self.value.setStyleSheet(f"color:{accent};")
        self.body.addWidget(self.value)

        self.sub = QLabel(sub)
        self.sub.setObjectName("StatSub")
        self.sub.setWordWrap(True)
        self.sub.setVisible(bool(sub))
        self.body.addWidget(self.sub)
        self.body.addStretch(1)

    def set(self, value: str, sub: str | None = None,
            color: str | None = None) -> None:
        self.value.setText(value)
        if color is not None:
            self.value.setStyleSheet(f"color:{color};" if color else "")
        if sub is not None:
            self.sub.setText(sub)
            self.sub.setVisible(bool(sub))


class Tile(Card):
    """A clickable card: icon, title, one short line."""

    from PySide6.QtCore import Signal as _Signal
    clicked = _Signal()

    def __init__(self, title: str, line: str, icon_name: str) -> None:
        super().__init__(padding=18, spacing=8)
        self.setObjectName("Tile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        from .icons import pixmap
        ic = QLabel()
        ic.setPixmap(pixmap(icon_name, S.ACCENT, 26))
        self.body.addWidget(ic)
        t = QLabel(title)
        t.setObjectName("CardTitle")
        self.body.addWidget(t)
        c = QLabel(line)
        c.setObjectName("StatSub")
        c.setWordWrap(True)
        self.body.addWidget(c)
        self.body.addStretch(1)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(e)


# ---- switch --------------------------------------------------------------

class Switch(QCheckBox):
    """Pill toggle. Still a QCheckBox: ``toggled``, ``setChecked``,
    ``stateChanged`` and ``isChecked`` behave as usual."""

    _W, _H = 44, 24

    def __init__(self, text: str = "", parent: QWidget | None = None, *,
                 big: bool = False) -> None:
        super().__init__(text, parent)
        self._big = big
        self._pos = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)
        if big:
            f = self.font()
            f.setPointSizeF(f.pointSizeF() * 1.1)
            f.setWeight(f.Weight.DemiBold)
            self.setFont(f)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        if not self.isVisible():
            self._pos = 1.0 if on else 0.0
            self.update()
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def showEvent(self, e) -> None:  # noqa: N802
        self._pos = 1.0 if self.isChecked() else 0.0
        super().showEvent(e)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        tw = fm.horizontalAdvance(self.text()) + 12 if self.text() else 0
        return QSize(self._W + tw + 2, max(self._H, fm.height()) + 4)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = (self.height() - self._H) / 2
        track = QRectF(1, y, self._W, self._H)
        on = QColor(S.ACCENT)
        off = QColor(S.BG_3)
        t = self._pos
        col = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            col.setAlpha(110)
        p.setPen(QPen(QColor(S.LINE_STRONG), 1) if t < 0.5 else Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(track, self._H / 2, self._H / 2)
        d = self._H - 6
        x = track.left() + 3 + (self._W - d - 6) * t
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1A1200") if t > 0.5 else QColor(S.FG_1))
        p.drawEllipse(QRectF(x, y + 3, d, d))
        if self.text():
            p.setPen(QColor(S.FG_0 if self.isEnabled() else S.FG_2))
            p.setFont(self.font())
            r = self.rect().adjusted(self._W + 12, 0, 0, 0)
            p.drawText(r, int(Qt.AlignmentFlag.AlignVCenter
                              | Qt.AlignmentFlag.AlignLeft), self.text())
        if self.hasFocus():
            p.setPen(QPen(QColor(S.ACCENT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(-2, -2, 2, 2),
                              self._H / 2 + 2, self._H / 2 + 2)


# ---- fields --------------------------------------------------------------

def field(label: str, widget: QWidget, help: str | None = None) -> QWidget:
    """A small label (+ "?") stacked above ``widget``."""
    host = QWidget()
    v = QVBoxLayout(host)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)
    head = QHBoxLayout()
    head.setSpacing(6)
    lab = QLabel(label)
    lab.setObjectName("FieldLabel")
    lab.setBuddy(widget)
    head.addWidget(lab)
    if help:
        head.addWidget(HelpBadge(help))
    head.addStretch(1)
    v.addLayout(head)
    if widget.layout() is not None:      # a row of controls in a QWidget
        widget.layout().setContentsMargins(0, 0, 0, 0)
    v.addWidget(widget)
    return host


def caption(text: str, role: str = "caption") -> QLabel:
    lab = QLabel(text)
    lab.setProperty("role", role)
    lab.setWordWrap(True)
    return lab


def hrow(*items, spacing: int = 12, stretch_last: bool = False) -> QHBoxLayout:
    """Lay ``items`` out in a row. An ``int`` item is a stretch factor
    for the widget before it; ``None`` inserts a stretch."""
    row = QHBoxLayout()
    row.setSpacing(spacing)
    for it in items:
        if it is None:
            row.addStretch(1)
        elif isinstance(it, QLayout):
            row.addLayout(it)
        else:
            row.addWidget(it)
    if stretch_last:
        row.addStretch(1)
    return row


# ---- page ----------------------------------------------------------------

class Page(QWidget):
    """Title (?) ......... [actions], then the body.

    The body scrolls when the window is too short for it, so cards keep
    their size instead of being squashed.
    """

    def __init__(self, title: str, help: str | None = None, *,
                 scroll: bool = True) -> None:
        super().__init__()
        self.setObjectName("PageBody")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.title = QLabel(title)
        self.title.setObjectName("PageTitle")
        head.addWidget(self.title)
        if help:
            self.help = HelpBadge(help)
            head.addWidget(self.help, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(10)
        head.addLayout(self.actions)
        outer.addLayout(head)

        self._content = QWidget()
        self._content.setObjectName("PageBody")
        self.body = QVBoxLayout(self._content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(18)
        if scroll:
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            sa.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            sa.setWidget(self._content)
            outer.addWidget(sa, 1)
        else:
            outer.addWidget(self._content, 1)

    def add_action(self, w: QWidget) -> None:
        self.actions.addWidget(w)

    def set_footer(self, w: QWidget) -> None:
        """Pin ``w`` under the scrolling body (always visible)."""
        self.layout().addWidget(w)


def expanding(w: QWidget) -> QWidget:
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return w


# ---- responsive card row -------------------------------------------------

class CardRow(QWidget):
    """Cards in one row that wrap to more rows when each would get
    narrower than ``min_w`` (e.g. 4 across → 2 × 2 in a small window)."""

    def __init__(self, widgets: list[QWidget], *, min_w: int = 190,
                 spacing: int = 18) -> None:
        super().__init__()
        from PySide6.QtWidgets import QGridLayout
        self._widgets = list(widgets)
        self._min_w = min_w
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(spacing)
        self._grid.setVerticalSpacing(spacing)
        self._place(len(self._widgets))

    def _place(self, cols: int) -> None:
        if cols == self._cols:
            return
        for w in self._widgets:
            self._grid.removeWidget(w)
        for c in range(max(self._cols, cols)):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
        for i, w in enumerate(self._widgets):
            self._grid.addWidget(w, i // cols, i % cols)
        self._cols = cols
        self.updateGeometry()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        n = len(self._widgets)
        sp = self._grid.horizontalSpacing()
        cols = max(1, min(n, (self.width() + sp) // (self._min_w + sp)))
        if cols < n and cols > 1 and n % cols:     # avoid a lone straggler
            cols = max(1, (n + 1) // 2) if n <= 4 else cols
        self._place(cols)


# ---- flow layout ---------------------------------------------------------

class FlowLayout(QLayout):
    """Lays widgets out left to right, wrapping onto new lines (chips)."""

    def __init__(self, parent: QWidget | None = None, *, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return self._do(QRect(0, 0, w, 0), dry=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do(rect, dry=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _do(self, rect: QRect, *, dry: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            w = it.widget()
            if w is not None and w.isHidden():
                continue
            hint = it.sizeHint()
            hint.setWidth(min(hint.width(), rect.width()))
            if x + hint.width() > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + self._sp
                line_h = 0
            if not dry:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._sp
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()
