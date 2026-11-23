"""Compliance + branding guarantees for Twice Corrupted.

GGG's macro rules (https://www.pathofexile.com/developer/docs) forbid
timer-driven input and more than one game action per key press. These
tests pin the decisions recorded in docs/COMPLIANCE_REVIEW.md §2.1:

* no timer / bulk-click macros are registered,
* the Inventory / Map Stash tabs only highlight slots (no Dump action),
* shipped config carries no hotkeys for the retired macros,
* the product is called "Twice Corrupted" and shows GGG's disclaimer.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

RETIRED = {"life_flask", "inventory_dump", "map_stash_dump"}
DISCLAIMER = ("This product isn't affiliated with or endorsed by "
              "Grinding Gear Games in any way.")


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class RegistryTests(unittest.TestCase):
    def test_retired_macros_are_not_registered(self) -> None:
        from poe_qol.engine.registry import discover
        names = set(discover())
        self.assertFalse(names & RETIRED, f"still registered: {names & RETIRED}")
        self.assertIn("coord_picker", names)


class DefaultConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        from poe_qol.core.config import ConfigStore
        # Read the shipped defaults only (no profile, no user overrides).
        self.cfg = ConfigStore.__new__(ConfigStore)
        import yaml
        self.cfg._data = yaml.safe_load(
            (ROOT / "config" / "default.yaml").read_text(encoding="utf-8"))

    def test_no_life_flask_section(self) -> None:
        self.assertIsNone(self.cfg.get("macros.life_flask"))

    def test_slot_grids_have_no_input_hotkeys(self) -> None:
        for ns in ("macros.inventory_dump", "macros.map_stash_dump"):
            self.assertIsNone(self.cfg.get(f"{ns}.hotkeys"), ns)
            self.assertIsNone(self.cfg.get(f"{ns}.modifier"), ns)
            # Grid geometry is still needed by overlay + calibration.
            self.assertIsNotNone(self.cfg.get(f"{ns}.grid.cols"), ns)

    def test_profiles_do_not_reference_retired_macros(self) -> None:
        import yaml
        for p in (ROOT / "config" / "profiles").glob("*.yaml"):
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            macros = (data.get("macros") or {})
            self.assertFalse(set(macros) & RETIRED, p.name)


class BrandingTests(unittest.TestCase):
    def test_app_name(self) -> None:
        import poe_qol
        self.assertEqual(poe_qol.APP_NAME, "Twice Corrupted")
        self.assertEqual(poe_qol.DISCLAIMER, DISCLAIMER)


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import shutil
        import tempfile
        cls._app = _qapp()
        cls.tmp = Path(tempfile.mkdtemp(prefix="tc_ui_"))
        shutil.copytree(ROOT / "config", cls.tmp / "config",
                        ignore=shutil.ignore_patterns("user.yaml"))
        cls._cwd = os.getcwd()
        os.chdir(cls.tmp)

    @classmethod
    def tearDownClass(cls) -> None:
        import shutil
        os.chdir(cls._cwd)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _window(self):
        from poe_qol.core.config import ConfigStore
        from poe_qol.core.state import AppState
        from poe_qol.engine.scheduler import Scheduler
        from poe_qol.input.hotkeys import HotkeyRouter
        from poe_qol.input.sender import InputSender
        from poe_qol.ui.main_window import MainWindow
        cfg = ConfigStore(self.tmp)
        sch = Scheduler(cfg, AppState(), InputSender(), HotkeyRouter())
        sch.load()
        self.addCleanup(sch.shutdown)
        return MainWindow(cfg, sch.state, sch)

    def test_window_title_is_product_name(self) -> None:
        win = self._window()
        self.assertEqual(win.windowTitle(), "Twice Corrupted")
        win.close()

    def test_slot_tabs_offer_overlay_but_no_dump(self) -> None:
        from PySide6.QtWidgets import QPushButton
        from poe_qol.ui.slot_selector import SlotSelector
        win = self._window()
        selectors = win.findChildren(SlotSelector)
        self.assertEqual(len(selectors), 2)
        for sel in selectors:
            labels = [b.text() for b in sel.findChildren(QPushButton)]
            self.assertFalse([t for t in labels if "dump" in t.lower()], labels)
            self.assertTrue([t for t in labels if "overlay" in t.lower()], labels)
        win.close()

    def test_about_shows_disclaimer(self) -> None:
        win = self._window()
        self.assertIn(DISCLAIMER, win.about_text())
        win.close()


if __name__ == "__main__":
    unittest.main()
