"""Line icons for the sidebar and buttons.

Simple original 24×24 stroke drawings, rendered from inline SVG so they
can be recoloured per state (idle / hover / selected) without shipping
image files. ``icon(name, color)`` returns a QIcon.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

_PATHS: dict[str, str] = {
    # four rounded tiles
    "home": '<rect x="3" y="3" width="7.5" height="7.5" rx="2"/>'
            '<rect x="13.5" y="3" width="7.5" height="7.5" rx="2"/>'
            '<rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/>'
            '<rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2"/>',
    # a bag grid
    "inventory": '<rect x="3" y="5" width="18" height="15" rx="2.5"/>'
                 '<path d="M3 12.5h18M9 5v15M15 5v15"/>'
                 '<path d="M8.5 5V3.5h7V5"/>',
    # stacked map sheets
    "maps": '<path d="M12 3 3 7.5l9 4.5 9-4.5z"/>'
            '<path d="m3 12 9 4.5 9-4.5"/><path d="m3 16.5 9 4.5 9-4.5"/>',
    # dashed box with a cursor
    "select": '<path d="M4 4h3M10 4h3M16 4h4v4M20 11v2M4 4v4M4 11v3M4 17v3h3'
              'M10 20h2"/><path d="m14 14 7 2.6-3 1.2-1.3 3.2z"/>',
    # magnifier
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/>',
    # swap arrows
    "flip": '<path d="M4 8h14l-3.5-3.5"/><path d="M20 16H6l3.5 3.5"/>',
    # price tag
    "tag": '<path d="M3 12V4.5A1.5 1.5 0 0 1 4.5 3H12l9 9-9 9z"/>'
           '<circle cx="8" cy="8" r="1.6"/>',
    # rising chart
    "wealth": '<path d="M3 20h18"/><path d="m4 15 5-5 4 4 7-7"/>'
              '<path d="M15 7h5v5"/>',
    # globe
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>'
             '<path d="M12 3c2.8 3 2.8 15 0 18M12 3c-2.8 3-2.8 15 0 18"/>',
    # info
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/>'
            '<path d="M12 7.5v.5"/>',
    # refresh
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    # power
    "power": '<path d="M12 3v8"/><path d="M6.4 6.6a8 8 0 1 0 11.2 0"/>',
    # target crosshair (calibrate)
    "target": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/>'
              '<path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    # eye (overlay)
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5'
           ' 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    # external link
    "external": '<path d="M14 4h6v6"/><path d="M20 4 11 13"/>'
                '<path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    # copy
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/>'
            '<path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    # folder
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2'
              'H5a2 2 0 0 1-2-2z"/>',
    # clipboard
    "clipboard": '<rect x="5" y="4.5" width="14" height="16.5" rx="2"/>'
                 '<rect x="9" y="2.5" width="6" height="4" rx="1"/>',
    # stop
    "stop": '<rect x="5" y="5" width="14" height="14" rx="3"/>',
}


def names() -> list[str]:
    return sorted(_PATHS)


def _svg(name: str, color: str, stroke: float) -> bytes:
    body = _PATHS[name]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode()


@lru_cache(maxsize=256)
def pixmap(name: str, color: str, size: int = 20, stroke: float = 1.9,
           dpr: float = 2.0) -> QPixmap:
    from PySide6.QtSvg import QSvgRenderer
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    r = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, *, checked_color: str | None = None,
         size: int = 20) -> QIcon:
    """QIcon in ``color``; optionally a different colour when checked."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(name, checked_color or color, size),
                 QIcon.Mode.Normal, QIcon.State.On)
    return ic


ICON_SIZE = QSize(20, 20)
