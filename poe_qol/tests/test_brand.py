"""Brand assets: icon/banner rendering, multi-size .ico, theme contrast.

The art is original ("scarlet rot" bloom + cracked gilt ring). It is
inspired by the mood of Elden Ring's Malenia but uses no FromSoftware
or GGG assets, names or likenesses.
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ICON_SVG = ROOT / "assets" / "brand" / "icon.svg"


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _contrast(a: str, b: str) -> float:
    def lum(h: str) -> float:
        rgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
               for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class IconSourceTests(unittest.TestCase):
    def test_svg_is_self_contained(self) -> None:
        text = ICON_SVG.read_text(encoding="utf-8")
        self.assertIn("<svg", text)
        self.assertNotIn("<image", text)       # no embedded/linked bitmaps
        self.assertNotIn("http://www.w3.org/1999/xlink\" xlink:href=\"http", text)


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _qapp()

    def test_icon_renders_with_transparent_rounded_corners(self) -> None:
        from poe_qol.tools.build_brand import render_svg
        img = render_svg(ICON_SVG, 256)
        self.assertEqual((img.width(), img.height()), (256, 256))
        self.assertEqual(img.pixelColor(1, 1).alpha(), 0)          # corner
        self.assertEqual(img.pixelColor(128, 128).alpha(), 255)    # centre
        c = img.pixelColor(128, 60)                                 # petals
        self.assertGreater(c.red(), c.blue())

    def test_ico_contains_all_sizes(self) -> None:
        from poe_qol.tools.build_brand import ICO_SIZES, render_svg, write_ico
        out = Path(tempfile.mkdtemp(prefix="tc_ico_")) / "x.ico"
        write_ico(out, [render_svg(ICON_SVG, s) for s in ICO_SIZES])
        data = out.read_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", data, 0)
        self.assertEqual((reserved, kind, count), (0, 1, len(ICO_SIZES)))
        sizes = []
        for i in range(count):
            w, h = struct.unpack_from("<BB", data, 6 + 16 * i)
            sizes.append(w or 256)
            size, offset = struct.unpack_from("<II", data, 6 + 16 * i + 8)
            self.assertEqual(data[offset:offset + 8], b"\x89PNG\r\n\x1a\n")
            self.assertLessEqual(offset + size, len(data))
        self.assertEqual(sorted(sizes), sorted(ICO_SIZES))

    def test_build_all_outputs(self) -> None:
        from PySide6.QtGui import QImage
        from poe_qol.tools.build_brand import build_all
        out = Path(tempfile.mkdtemp(prefix="tc_brand_"))
        files = build_all(out)
        expect = {"app_icon.png": (512, 512), "app_icon_1024.png": (1024, 1024),
                  "banner.png": (1600, 400), "social_preview.png": (1280, 640)}
        for name, size in expect.items():
            img = QImage(str(out / name))
            self.assertFalse(img.isNull(), name)
            self.assertEqual((img.width(), img.height()), size, name)
        self.assertTrue((out / "app_icon.ico").exists())
        self.assertEqual({p.name for p in files} >= set(expect) | {"app_icon.ico"},
                         True)

    def test_bundled_banner_fonts(self) -> None:
        from poe_qol.tools import build_brand as bb
        fonts = ROOT / "assets" / "brand" / "fonts"
        for f in ("SixCaps.ttf", "SixCaps-OFL.txt",
                  "Almendra-Regular.ttf", "Almendra-OFL.txt"):
            self.assertTrue((fonts / f).exists(), f)   # OFL: licence ships too
        families = bb.load_brand_fonts()
        self.assertIn("Six Caps", families)
        self.assertIn("Almendra", families)
        self.assertEqual(bb.TITLE_FAMILY, "Six Caps")
        self.assertEqual(bb.SUBTITLE_FAMILY, "Almendra")
        self.assertFalse(hasattr(bb, "TAGLINE"))       # tagline removed

    def test_runtime_icon_is_found(self) -> None:
        from poe_qol.ui.branding import resolve_icon_path
        p = resolve_icon_path(ROOT)
        self.assertIsNotNone(p)
        self.assertTrue(p.name.startswith("app_icon"))


class ThemeContrastTests(unittest.TestCase):
    def test_text_and_accents_are_readable(self) -> None:
        from poe_qol.ui import styles as s
        self.assertGreaterEqual(_contrast(s.FG_0, s.BG_1), 7.0)
        self.assertGreaterEqual(_contrast(s.FG_1, s.BG_1), 4.5)
        self.assertGreaterEqual(_contrast(s.ACCENT, s.BG_0), 4.5)
        self.assertGreaterEqual(_contrast(s.ROT_HI, s.BG_0), 3.0)   # large text / UI
        self.assertGreaterEqual(_contrast(s.BG_0, s.ACCENT), 4.5)   # dark text on gold


if __name__ == "__main__":
    unittest.main()
