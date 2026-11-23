"""Build Twice Corrupted's brand assets from ``assets/brand/icon.svg``.

Outputs (into ``poe_qol/assets/`` by default):

    app_icon.png          512×512, loaded by the app at runtime
    app_icon_1024.png     master render
    app_icon.ico          16–256 px multi-size icon for Windows
    banner.png            1600×400 README header
    social_preview.png    1280×640 GitHub social preview
                          (upload manually: repo Settings → Social preview)

Art direction ("scarlet rot & gilt"): an original two-layer crimson bloom
of blade-curved petals in a cracked gold ring. It is inspired by the mood
of Elden Ring's Malenia but uses no FromSoftware or GGG artwork, names,
logos or likenesses.

Only Qt is needed (QtSvg ships with PySide6), so there's no Pillow.

    python -m poe_qol.tools.build_brand            # write into poe_qol/assets
    python -m poe_qol.tools.build_brand --out DIR
"""
from __future__ import annotations

import argparse
import os
import random
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QGuiApplication, QImage, QLinearGradient,
    QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parents[3] / "assets"
ICON_SVG = ASSETS / "brand" / "icon.svg"
FONTS_DIR = ASSETS / "brand" / "fonts"   # bundled OFL fonts (+ licences)
TITLE_FAMILY = "Six Caps"       # SixCaps.ttf, Vernon Adams, SIL OFL 1.1
SUBTITLE_FAMILY = "Almendra"    # Almendra-Regular.ttf, Ana Sanfelippo, SIL OFL 1.1
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# Palette (kept in sync with ui/styles.py)
OBSIDIAN = "#0A0708"
ROT_DEEP = "#1A0A0E"
ROT = "#B3122E"
EMBER = "#E0482F"
GILT_HI = "#F2DE9F"
GILT = "#C9A24A"
GILT_LO = "#8A6524"
BONE = "#E8DCCB"
ASH = "#A8968A"

TITLE = "TWICE CORRUPTED"
SUBTITLE = "A quality-of-life companion for Path of Exile"

_loaded_families: set[str] | None = None


def load_brand_fonts() -> set[str]:
    """Register the bundled banner fonts with Qt (needs a QGuiApplication).
    Returns the font families now available from FONTS_DIR."""
    global _loaded_families
    if _loaded_families is None:
        from PySide6.QtGui import QFontDatabase
        fams: set[str] = set()
        for ttf in sorted(FONTS_DIR.glob("*.ttf")):
            fid = QFontDatabase.addApplicationFont(str(ttf))
            if fid < 0:
                raise OSError(f"Qt could not load font {ttf.name}")
            fams.update(QFontDatabase.applicationFontFamilies(fid))
        _loaded_families = fams
    return set(_loaded_families)


def _blank(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    return img


def render_svg(path: str | Path, size: int, element: str | None = None) -> QImage:
    """Render ``path`` (or one element of it) into a square image."""
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        raise ValueError(f"invalid SVG: {path}")
    img = _blank(size, size)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if element:
        renderer.render(p, element, QRectF(0, 0, size, size))
    else:
        renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def _png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba.data())


def write_ico(path: str | Path, images: list[QImage]) -> None:
    """Write a multi-size .ico with PNG-compressed entries (Vista+)."""
    blobs = [_png_bytes(i) for i in images]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for img, blob in zip(images, blobs):
        w = 0 if img.width() >= 256 else img.width()
        h = 0 if img.height() >= 256 else img.height()
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    Path(path).write_bytes(header + entries + b"".join(blobs))


# ---------------------------------------------------------------------------
# Banner / social preview
# ---------------------------------------------------------------------------

_PETAL = None


def _petal_path() -> QPainterPath:
    """Same blade-curved petal as the icon, unit length ~1."""
    global _PETAL
    if _PETAL is None:
        s = 1 / 372
        p = QPainterPath(QPointF(0, -58 * s))
        p.cubicTo(64 * s, -140 * s, 96 * s, -250 * s, 22 * s, -372 * s)
        p.cubicTo(10 * s, -338 * s, -30 * s, -306 * s, -46 * s, -252 * s)
        p.cubicTo(-66 * s, -182 * s, -42 * s, -112 * s, 0, -58 * s)
        _PETAL = p
    return _PETAL


def _background(p: QPainter, w: int, h: int, mist_at: QPointF) -> None:
    g = QLinearGradient(0, 0, w, 0)
    g.setColorAt(0, QColor(OBSIDIAN))
    g.setColorAt(0.65, QColor(ROT_DEEP))
    g.setColorAt(1, QColor(OBSIDIAN))
    p.fillRect(0, 0, w, h, g)
    mist = QRadialGradient(mist_at, max(w, h) * 0.38)
    c = QColor(ROT); c.setAlphaF(0.38)
    mist.setColorAt(0, c)
    c2 = QColor(ROT); c2.setAlphaF(0)
    mist.setColorAt(1, c2)
    p.fillRect(0, 0, w, h, mist)


def _drifting_petals(p: QPainter, w: int, h: int, seed: int, count: int,
                     keep_clear: QRectF | None = None,
                     x_from: float = 0.0) -> None:
    """Scatter petals, skipping ``keep_clear`` (the text block)."""
    rnd = random.Random(seed)
    base = _petal_path()
    p.setPen(Qt.PenStyle.NoPen)
    placed = 0
    while placed < count:
        x = rnd.uniform(w * x_from, w)
        y = rnd.uniform(0, h)
        if keep_clear is not None and keep_clear.adjusted(-24, -24, 24, 24).contains(x, y):
            continue
        placed += 1
        size = rnd.uniform(10, 34)
        col = QColor(rnd.choice((ROT, EMBER, "#C21F3A", "#F57A48")))
        col.setAlphaF(rnd.uniform(0.25, 0.75))
        p.save()
        p.translate(x, y)
        p.rotate(rnd.uniform(0, 360))
        p.scale(size, size)
        p.fillPath(base, QBrush(col))
        p.restore()


def _gilt_text(p: QPainter, text: str, font: QFont, x: float, baseline: float,
               shadow: bool = True) -> float:
    path = QPainterPath()
    path.addText(QPointF(x, baseline), font, text)
    rect = path.boundingRect()
    if shadow:
        sh = QColor(0, 0, 0, 160)
        p.fillPath(path.translated(3, 4), sh)
    g = QLinearGradient(0, rect.top(), 0, rect.bottom())
    g.setColorAt(0, QColor(GILT_HI))
    g.setColorAt(0.55, QColor(GILT))
    g.setColorAt(1, QColor(GILT_LO))
    p.fillPath(path, QBrush(g))
    return rect.width()


def _title_font(px: int) -> QFont:
    load_brand_fonts()
    f = QFont()
    f.setFamilies([TITLE_FAMILY])
    f.setPixelSize(px)
    # Six Caps is very condensed; a little tracking keeps it legible.
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, px * 0.05)
    return f


def _subtitle_font(px: int) -> QFont:
    load_brand_fonts()
    f = QFont()
    f.setFamilies([SUBTITLE_FAMILY])
    f.setPixelSize(px)
    return f


def _rule(p: QPainter, x1: float, x2: float, y: float) -> None:
    g = QLinearGradient(x1, 0, x2, 0)
    g.setColorAt(0, QColor(GILT))
    fade = QColor(GILT); fade.setAlphaF(0)
    g.setColorAt(1, fade)
    p.setPen(QPen(QBrush(g), 2))
    p.drawLine(QPointF(x1 + 18, y), QPointF(x2, y))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(GILT_HI))
    d = QPainterPath()
    d.moveTo(x1, y - 7); d.lineTo(x1 + 7, y); d.lineTo(x1, y + 7); d.lineTo(x1 - 7, y)
    d.closeSubpath()
    p.drawPath(d)


def render_banner(width: int = 1600, height: int = 400) -> QImage:
    img = _blank(width, height)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    _background(p, width, height, QPointF(width * 0.83, height * 0.5))

    renderer = QSvgRenderer(str(ICON_SVG))
    icon = height * 0.62
    ix, iy = height * 0.19, (height - icon) / 2
    tx = ix + icon + 54
    text_block = QRectF(tx, height * 0.18, width * 0.70 - tx, height * 0.70)

    # Large faded bloom bleeding off the right edge, clear of the title.
    p.setOpacity(0.32)
    renderer.render(p, "bloom", QRectF(width - 330, -70, 540, 540))
    p.setOpacity(1.0)
    _drifting_petals(p, width, height, seed=7, count=22,
                     keep_clear=text_block, x_from=0.3)
    renderer.render(p, QRectF(ix, iy, icon, icon))

    _gilt_text(p, TITLE, _title_font(int(height * 0.36)), tx, height * 0.56)
    _rule(p, tx + 4, width * 0.74, height * 0.64)
    p.setPen(QColor(BONE))
    p.setFont(_subtitle_font(int(height * 0.088)))
    p.drawText(QPointF(tx + 2, height * 0.80), SUBTITLE)
    p.end()
    return img


def render_social_preview(width: int = 1280, height: int = 640) -> QImage:
    img = _blank(width, height)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    _background(p, width, height, QPointF(width * 0.5, height * 0.36))
    icon = height * 0.46
    clear_icon = QRectF((width - icon) / 2, height * 0.08, icon, icon)
    clear_text = QRectF(width * 0.12, height * 0.58, width * 0.76, height * 0.34)
    rnd_count, placed = 34, 0
    for seed in range(11, 200):
        if placed >= rnd_count:
            break
        rnd = random.Random(seed)
        x, y = rnd.uniform(0, width), rnd.uniform(0, height)
        if clear_icon.adjusted(-30, -30, 30, 30).contains(x, y) or                 clear_text.contains(x, y):
            continue
        placed += 1
        p.save()
        p.translate(x, y)
        p.rotate(rnd.uniform(0, 360))
        size = rnd.uniform(10, 30)
        p.scale(size, size)
        col = QColor(rnd.choice((ROT, EMBER, "#C21F3A", "#F57A48")))
        col.setAlphaF(rnd.uniform(0.25, 0.7))
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(_petal_path(), QBrush(col))
        p.restore()
    renderer = QSvgRenderer(str(ICON_SVG))
    renderer.render(p, QRectF((width - icon) / 2, height * 0.08, icon, icon))

    font = _title_font(int(height * 0.24))
    path = QPainterPath()
    path.addText(QPointF(0, 0), font, TITLE)
    tw = path.boundingRect().width()
    _gilt_text(p, TITLE, font, (width - tw) / 2, height * 0.80)
    p.setPen(QColor(BONE))
    p.setFont(_subtitle_font(int(height * 0.055)))
    rect = QRectF(0, height * 0.83, width, height * 0.10)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, SUBTITLE)
    p.end()
    return img


def build_all(out_dir: str | Path = ASSETS) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save(img: QImage, name: str) -> None:
        path = out / name
        if not img.save(str(path), "PNG"):
            raise OSError(f"could not write {path}")
        written.append(path)

    save(render_svg(ICON_SVG, 1024), "app_icon_1024.png")
    save(render_svg(ICON_SVG, 512), "app_icon.png")
    ico = out / "app_icon.ico"
    write_ico(ico, [render_svg(ICON_SVG, s) for s in ICO_SIZES])
    written.append(ico)
    save(render_banner(), "banner.png")
    save(render_social_preview(), "social_preview.png")
    return written


def ensure_fonts() -> None:
    """Qt's headless 'offscreen' platform on Windows has no font database
    unless pointed at one; without it banner text renders as boxes."""
    if (os.environ.get("QT_QPA_PLATFORM") == "offscreen"
            and "QT_QPA_FONTDIR" not in os.environ and sys.platform == "win32"):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        os.environ["QT_QPA_FONTDIR"] = str(Path(windir) / "Fonts")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ASSETS), help="output folder")
    args = ap.parse_args(argv)
    ensure_fonts()
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    for path in build_all(args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
