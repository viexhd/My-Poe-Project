"""League detection and the shared league picker."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poe_qol.trade.leagues import (  # noqa: E402
    AUTO, LeagueDirectory, is_auto, parse_leagues, pick_latest,
)

SAMPLE = {"result": [
    {"id": "Covens", "realm": "pc", "text": "Covens"},
    {"id": "Hardcore Covens", "realm": "pc", "text": "Hardcore Covens"},
    {"id": "SSF Covens", "realm": "pc", "text": "SSF Covens"},
    {"id": "Standard", "realm": "pc", "text": "Standard"},
    {"id": "Hardcore", "realm": "pc", "text": "Hardcore"},
    {"id": "Covens", "realm": "xbox", "text": "Covens"},
]}


class PickLatestTests(unittest.TestCase):
    def test_parse_keeps_pc_order(self):
        self.assertEqual(parse_leagues(SAMPLE),
                         ["Covens", "Hardcore Covens", "SSF Covens",
                          "Standard", "Hardcore"])

    def test_latest_is_softcore_challenge_league(self):
        self.assertEqual(pick_latest(parse_leagues(SAMPLE)), "Covens")
        self.assertEqual(pick_latest(["Hardcore Covens", "Covens"]), "Covens")
        self.assertEqual(pick_latest(["Standard", "Hardcore"]), "Standard")
        self.assertEqual(pick_latest([]), "Standard")

    def test_auto_values(self):
        for v in (None, "", "auto", " AUTO "):
            self.assertTrue(is_auto(v))
        self.assertFalse(is_auto("Covens"))


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_offline_uses_saved_list(self):
        cache = self.tmp / "leagues.json"
        cache.write_text(json.dumps({"leagues": ["Covens", "Standard"],
                                     "fetched_at": time.time() - 99999}))
        d = LeagueDirectory(cache, timeout=0.01)
        import poe_qol.trade.leagues as L
        orig = L.urllib.request.urlopen
        L.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
        try:
            self.assertEqual(d.refresh(), ["Covens", "Standard"])
        finally:
            L.urllib.request.urlopen = orig
        self.assertEqual(d.latest, "Covens")
        self.assertEqual(d.resolve(AUTO), "Covens")
        self.assertEqual(d.resolve("Hardcore Covens"), "Hardcore Covens")

    def test_nothing_saved_falls_back_to_standard(self):
        d = LeagueDirectory(self.tmp / "none.json")
        self.assertEqual(d.resolve(None), "Standard")


class LeagueBoxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from poe_qol.core.config import ConfigStore
        import poe_qol.ui.league as UL
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(ROOT / "config", self.tmp / "config",
                        ignore=shutil.ignore_patterns("user.yaml"))
        self.cfg = ConfigStore(self.tmp)
        d = LeagueDirectory(self.tmp / "leagues.json")
        d.leagues = ["Covens", "Hardcore Covens", "Standard", "Hardcore"]
        self._old = UL._service
        UL._service = UL.LeagueService(d)
        self.addCleanup(setattr, UL, "_service", self._old)
        self.svc = UL._service

    def _box(self, key="trade.league"):
        from poe_qol.ui.league import LeagueBox
        return LeagueBox(self.cfg, key)

    def test_auto_shows_latest_first(self):
        self.cfg.set("trade.league", "auto")
        b = self._box()
        self.assertEqual(b.itemText(0), "Latest (Covens)")
        self.assertEqual(b.league(), "Covens")
        self.assertEqual(b.value(), AUTO)

    def test_ended_league_switches_to_latest(self):
        self.cfg.set("trade.league", "Mirage")
        b = self._box()
        self.assertEqual(b.value(), AUTO)
        self.assertEqual(b.league(), "Covens")

    def test_saved_latest_becomes_auto_and_follows_new_league(self):
        self.cfg.set("trade.league", "Covens")
        b = self._box()
        self.assertEqual(b.value(), AUTO)
        seen = []
        b.league_changed.connect(seen.append)
        self.svc.directory.leagues = ["Rapture", "Hardcore Rapture", "Standard"]
        self.svc.updated.emit()
        self.assertEqual(b.league(), "Rapture")
        self.assertEqual(seen, ["Rapture"])

    def test_picking_a_fixed_league_is_saved(self):
        b = self._box()
        b.setCurrentIndex(b.findData("Hardcore Covens"))
        self.assertEqual(b.league(), "Hardcore Covens")
        self.assertEqual(self.cfg.get("trade.league"), "Hardcore Covens")

    def test_unknown_league_kept_while_list_is_unknown(self):
        self.svc.directory.leagues = []
        self.cfg.set("trade.league", "Mirage")
        b = self._box()
        self.assertEqual(b.league(), "Mirage")


if __name__ == "__main__":
    unittest.main()
