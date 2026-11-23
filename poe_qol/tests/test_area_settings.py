"""Area-select settings (config/default.yaml `area_select:` section) and
the Qt controller that wires gesture -> selection -> overlay -> transfer.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from poe_qol.area_select.settings import AreaSelectSettings  # noqa: E402
from poe_qol.core.config import ConfigStore  # noqa: E402


def _tmp_config() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="tc_area_"))
    shutil.copytree(ROOT / "config", tmp / "config",
                    ignore=shutil.ignore_patterns("user.yaml"))
    return tmp


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _tmp_config()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cfg = ConfigStore(self.tmp)

    def test_shipped_defaults(self) -> None:
        s = AreaSelectSettings.load(self.cfg)
        self.assertTrue(s.enabled)
        self.assertEqual(s.modifier, "alt")
        self.assertEqual(s.transfer_mode, "manual")
        self.assertFalse(s.experimental.acknowledged)
        self.assertEqual(s.grids, ("macros.inventory_dump",))
        self.assertTrue(s.overlay.visible)
        self.assertFalse(s.debug)

    def test_invalid_values_are_clamped(self) -> None:
        self.cfg.set("area_select.overlay.fill_opacity", 7)
        self.cfg.set("area_select.overlay.border_px", 0)
        self.cfg.set("area_select.transfer_mode", "turbo")
        self.cfg.set("area_select.modifier", "ctrl")   # would hijack Ctrl-clicks
        self.cfg.set("area_select.experimental.click_delay_ms", 0)
        s = AreaSelectSettings.load(self.cfg)
        self.assertEqual(s.overlay.fill_opacity, 1.0)
        self.assertEqual(s.overlay.border_px, 1)
        self.assertEqual(s.transfer_mode, "manual")
        self.assertEqual(s.modifier, "alt")
        self.assertGreaterEqual(s.experimental.click_delay_ms, 20)

    def test_experimental_mode_without_acknowledgement_runs_manual(self) -> None:
        self.cfg.set("area_select.transfer_mode", "experimental")
        s = AreaSelectSettings.load(self.cfg)
        self.assertEqual(s.transfer_mode, "experimental")
        self.assertEqual(s.effective_mode, "manual")
        self.cfg.set("area_select.experimental.acknowledged", True)
        self.assertEqual(AreaSelectSettings.load(self.cfg).effective_mode,
                         "experimental")

    def test_save_persists_to_user_yaml(self) -> None:
        s = AreaSelectSettings.load(self.cfg)
        s = s.replace(modifier="ctrl+alt", debug=True)
        s.save(self.cfg)
        data = yaml.safe_load((self.tmp / "config" / "user.yaml").read_text())
        self.assertEqual(data["area_select"]["modifier"], "ctrl+alt")
        self.assertTrue(data["area_select"]["debug"])
        again = AreaSelectSettings.load(ConfigStore(self.tmp))
        self.assertEqual(again.modifier, "ctrl+alt")


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class ControllerTests(unittest.TestCase):
    """Drive the controller with synthetic hook events (no real hook)."""

    def setUp(self) -> None:
        from poe_qol.area_select.grid import GridGeometry
        from poe_qol.core.state import AppState
        self.app = _qapp()
        self.tmp = _tmp_config()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cfg = ConfigStore(self.tmp)
        self.state = AppState()
        self.geom = GridGeometry(origin=(1000.0, 500.0), cell=(50.0, 50.0),
                                 cols=12, rows=5)
        self.focused = True

    def _controller(self, **kw):
        from poe_qol.area_select.controller import AreaSelectController
        c = AreaSelectController(
            self.cfg, self.state, sender=None, start_hook=False,
            geometry_provider=lambda ns: self.geom,
            focus_provider=lambda: self.focused,
            capture_provider=lambda geom: None,
            **kw)
        self.addCleanup(c.shutdown)
        return c

    def _pump(self):
        self.app.processEvents()

    def _drag(self, c, x0, y0, x1, y1):
        from poe_qol.area_select.gesture import MouseEvent
        alt = frozenset({"alt"})
        c.gate.handle_mouse(MouseEvent("down", x0, y0, alt))
        c.gate.handle_mouse(MouseEvent("move", (x0 + x1) // 2, (y0 + y1) // 2, alt))
        c.gate.handle_mouse(MouseEvent("up", x1, y1, alt))
        self._pump()

    def test_manual_flow_highlights_then_ticks_off(self) -> None:
        from poe_qol.area_select.gesture import MouseEvent
        c = self._controller()
        self._drag(c, 990, 490, 1060, 560)
        self.assertEqual(c.plan.slots, ((0, 0), (1, 0), (1, 1), (0, 1)))
        model = c.overlay_model
        self.assertEqual(len([m for m in model.marks if m.kind == "pending"]), 4)
        self.assertIn("4", model.label)
        c.gate.handle_mouse(MouseEvent("down", 1000, 500, frozenset({"ctrl"})))
        self._pump()
        self.assertEqual(len([m for m in c.overlay_model.marks
                              if m.kind == "pending"]), 3)

    def test_live_drag_model_counts_slots(self) -> None:
        from poe_qol.area_select.gesture import MouseEvent
        c = self._controller()
        alt = frozenset({"alt"})
        c.gate.handle_mouse(MouseEvent("down", 990, 490, alt))
        c.gate.handle_mouse(MouseEvent("move", 1110, 560, alt))
        self._pump()
        m = c.overlay_model
        self.assertIsNotNone(m.drag_rect)
        self.assertEqual(len(m.marks), 6)
        self.assertIn("6", m.label)

    def test_escape_cancel_clears_overlay(self) -> None:
        from poe_qol.area_select.gesture import KeyEvent, MouseEvent
        c = self._controller()
        c.gate.handle_mouse(MouseEvent("down", 990, 490, frozenset({"alt"})))
        c.gate.handle_key(KeyEvent("esc", True))
        self._pump()
        self.assertIsNone(c.plan)
        self.assertIsNone(c.overlay_model.drag_rect)
        self.assertEqual(c.overlay_model.marks, ())

    def test_empty_slots_skipped_when_detection_available(self) -> None:
        from poe_qol.area_select.occupancy import SlotStats

        def fake_occ(geom, slots):
            return {s: SlotStats(0, 0, s != (0, 1)) for s in slots}
        c = self._controller(occupancy_provider=fake_occ)
        self._drag(c, 990, 490, 1060, 560)
        self.assertNotIn((0, 1), c.plan.slots)
        self.assertEqual(len(c.plan.slots), 3)

    def test_disabled_feature_ignores_gesture(self) -> None:
        from poe_qol.area_select.gesture import MouseEvent
        self.cfg.set("area_select.enabled", False)
        c = self._controller()
        self.assertFalse(c.gate.handle_mouse(
            MouseEvent("down", 990, 490, frozenset({"alt"}))))

    def test_experimental_mode_uses_injected_strategy(self) -> None:
        self.cfg.set("area_select.transfer_mode", "experimental")
        self.cfg.set("area_select.experimental.acknowledged", True)
        started = []

        class _Fake:
            MODE = "experimental"
            active = False

            def start(self, plan, listener):
                started.append(plan)

            def cancel(self, reason):
                pass

            def user_clicked(self, *a):
                pass

            def user_moved(self, *a):
                pass

        c = self._controller(strategy_factory=lambda mode: _Fake())
        self._drag(c, 990, 490, 1060, 560)
        self.assertEqual(len(started), 1)
        self.assertEqual(len(started[0].slots), 4)

    def test_manual_mode_never_imports_experimental_module(self) -> None:
        sys.modules.pop("poe_qol.experimental.bulk_ctrl_click", None)
        c = self._controller()
        self._drag(c, 990, 490, 1060, 560)
        self.assertNotIn("poe_qol.experimental.bulk_ctrl_click", sys.modules)


class OverlayPaintTests(unittest.TestCase):
    def test_overlay_paints_model_offscreen(self) -> None:
        from PySide6.QtGui import QImage
        from poe_qol.area_select.grid import Rect
        from poe_qol.area_select.overlay_model import OverlayModel, SlotMark
        from poe_qol.area_select.settings import OverlaySettings
        from poe_qol.ui.area_select_overlay import AreaSelectOverlay
        _qapp()
        ov = AreaSelectOverlay(OverlaySettings())
        ov.set_frame(Rect(0, 0, 400, 300), dpr=1.0)
        ov.set_model(OverlayModel(
            drag_rect=Rect(10, 10, 200, 150),
            marks=(SlotMark(Rect(20, 20, 70, 70), "occupied", None),
                   SlotMark(Rect(70, 20, 120, 70), "empty", None),
                   SlotMark(Rect(120, 20, 170, 70), "pending", 1)),
            label="3 slots · 2 items", label_pos=(200, 150)))
        img = QImage(400, 300, QImage.Format.Format_ARGB32)
        img.fill(0)
        ov.render(img)
        ov.close()


class SlotSelectorOverlayTests(unittest.TestCase):
    """The Inventory tab overlay now shares grid.resolve_geometry."""

    def test_overlay_covers_grid_and_paints(self) -> None:
        from PySide6.QtGui import QImage
        from poe_qol.ui.slot_selector import _OverlayWindow
        _qapp()
        tmp = _tmp_config()
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = ConfigStore(tmp)
        cfg.set("macros.inventory_dump.grid.origin", [1000, 500])
        cfg.set("macros.inventory_dump.grid.cell_size", [50, 50])
        ov = _OverlayWindow(cfg, "macros.inventory_dump")
        ov.refresh([(0, 0), (4, 11)])
        g = ov.geometry()
        dpr = ov._dpr
        self.assertAlmostEqual(g.x() * dpr, 971, delta=dpr)
        self.assertAlmostEqual(g.width() * dpr, 608, delta=2 * dpr)
        img = QImage(g.width(), g.height(), QImage.Format.Format_ARGB32)
        img.fill(0)
        ov.render(img)
        ov.close()


@unittest.skipUnless(sys.platform.startswith("win"), "Win32 hook")
class HookSmokeTests(unittest.TestCase):
    def test_hook_installs_and_removes(self) -> None:
        from poe_qol.input.mouse_hook import LowLevelInputHook, modifiers_down
        hook = LowLevelInputHook(lambda ev: False, lambda ev: False)
        self.assertTrue(hook.start(), hook.error)
        self.assertTrue(hook.running)
        hook.stop()
        self.assertFalse(hook.running)
        self.assertIsInstance(modifiers_down(), frozenset)

    def test_foreground_matcher_returns_bool(self) -> None:
        from poe_qol.vision.window import ForegroundMatcher
        m = ForegroundMatcher("Path of Exile")
        self.assertIsInstance(m(), bool)


class SettingsWidgetTests(unittest.TestCase):
    def test_widget_builds_and_saves(self) -> None:
        from poe_qol.ui.area_select_widget import AreaSelectWidget
        _qapp()
        tmp = _tmp_config()
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = ConfigStore(tmp)
        w = AreaSelectWidget(cfg, controller=None)
        w.enabled_cb.setChecked(False)
        data = yaml.safe_load((tmp / "config" / "user.yaml").read_text())
        self.assertFalse(data["area_select"]["enabled"])
        w.close()


if __name__ == "__main__":
    unittest.main()
