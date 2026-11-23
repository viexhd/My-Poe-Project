"""In-app trade browser + Map Search "open pre-filled" flow.

The browser shows the real pathofexile.com/trade; the user logs in there
themselves. Twice Corrupted only *navigates* it to a ``?q=`` search URL
(the same link format Awakened PoE Trade opens, see
renderer/src/web/price-check/trade/TradeListing.vue). No trade API call
is made by the app and cookies are never read.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poe_qol.ui.trade_browser import is_allowed_url  # noqa: E402


class AllowListTests(unittest.TestCase):
    def test_allowed(self) -> None:
        for url in ("https://www.pathofexile.com/trade/search/Mirage?q=%7B%7D",
                    "https://pathofexile.com/login",
                    "https://www.pathofexile.com/oauth/authorize?x=1"):
            self.assertTrue(is_allowed_url(url), url)

    def test_steam_sign_in_only(self) -> None:
        self.assertTrue(is_allowed_url(
            "https://steamcommunity.com/openid/login?openid.mode=checkid_setup"))
        self.assertFalse(is_allowed_url("https://steamcommunity.com/market/"))
        self.assertFalse(is_allowed_url("http://steamcommunity.com/openid/login"))

    def test_blocked(self) -> None:
        for url in ("http://www.pathofexile.com/trade",       # not https
                    "https://pathofexile.com.evil.example/",   # lookalike
                    "https://evilpathofexile.com/",
                    "https://poe.ninja/",
                    "javascript:alert(1)",
                    "file:///C:/Windows/win.ini",
                    ""):
            self.assertFalse(is_allowed_url(url), url)


def _qapp():
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    return QApplication.instance() or QApplication([])


class MapSearchOpenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _qapp()
        cls.tmp = Path(tempfile.mkdtemp(prefix="tc_ms_"))
        shutil.copytree(ROOT / "config", cls.tmp / "config",
                        ignore=shutil.ignore_patterns("user.yaml"))
        cls._cwd = os.getcwd()
        os.chdir(cls.tmp)

    @classmethod
    def tearDownClass(cls) -> None:
        os.chdir(cls._cwd)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_default_url_mode_makes_no_api_call(self) -> None:
        from poe_qol.core.config import ConfigStore
        self.assertEqual(ConfigStore(self.tmp).get("trade.url_mode"), "copy")

    def test_open_trade_hands_prefilled_url_to_app_browser(self) -> None:
        from poe_qol.core.config import ConfigStore
        from poe_qol.ui.map_search_widget import MapSearchWidget
        opened: list[str] = []
        cfg = ConfigStore(self.tmp)
        cfg.set("trade.league", "Mirage")
        w = MapSearchWidget(cfg, open_in_app=opened.append)
        w.open_btn.click()
        self.assertEqual(len(opened), 1)
        url = opened[0]
        self.assertTrue(url.startswith(
            "https://www.pathofexile.com/trade/search/Mirage?q="), url)
        self.assertTrue(is_allowed_url(url))
        payload = urllib.parse.unquote(url.split("?q=", 1)[1])
        self.assertIn('"query"', payload)
        w.close()


if __name__ == "__main__":
    unittest.main()
