"""Selection state + gesture gating for the Alt+drag area selection.

The gesture gate decides, per raw mouse / key event, whether the event
is swallowed (kept away from the game) and drives the drag state.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poe_qol.area_select.gesture import (  # noqa: E402
    GestureGate, KeyEvent, MouseEvent, parse_modifier,
)
from poe_qol.area_select.grid import GridGeometry, Rect  # noqa: E402
from poe_qol.area_select.selection import (  # noqa: E402
    DragSelector, resolve_selection,
)

INV = GridGeometry(origin=(1000.0, 500.0), cell=(50.0, 50.0), cols=12, rows=5)
STASH = GridGeometry(origin=(100.0, 200.0), cell=(50.0, 50.0), cols=12, rows=6)
ALT = frozenset({"alt"})


class DragSelectorTests(unittest.TestCase):
    def test_press_move_release(self) -> None:
        s = DragSelector()
        self.assertFalse(s.active)
        s.press(10, 10)
        self.assertTrue(s.active)
        s.move(50, 60)
        self.assertEqual(s.rect, Rect(10, 10, 50, 60))
        r = s.release(70, 80)
        self.assertEqual(r, Rect(10, 10, 70, 80))
        self.assertFalse(s.active)

    def test_reverse_direction(self) -> None:
        s = DragSelector()
        s.press(100, 100)
        self.assertEqual(s.release(20, 30), Rect(20, 30, 100, 100))

    def test_cancel(self) -> None:
        s = DragSelector()
        s.press(1, 1)
        s.move(5, 5)
        s.cancel()
        self.assertFalse(s.active)
        self.assertIsNone(s.rect)


class ResolveSelectionTests(unittest.TestCase):
    grids = {"inventory": INV, "stash": STASH}

    def test_drag_picks_grid_with_most_slots(self) -> None:
        sel = resolve_selection(Rect(990, 490, 1060, 560), self.grids,
                                click_threshold_px=6)
        self.assertEqual(sel.grid, "inventory")
        self.assertEqual(sel.slots, ((0, 0), (0, 1), (1, 0), (1, 1)))
        self.assertFalse(sel.is_click)

    def test_click_selects_slot_under_point(self) -> None:
        sel = resolve_selection(Rect(1101, 549, 1103, 551), self.grids,
                                click_threshold_px=6)
        self.assertTrue(sel.is_click)
        self.assertEqual((sel.grid, sel.slots), ("inventory", ((1, 2),)))

    def test_nothing_selected_returns_none(self) -> None:
        self.assertIsNone(resolve_selection(Rect(3000, 3000, 3100, 3100),
                                            self.grids, click_threshold_px=6))


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_drag_start(self, x, y):
        self.events.append(("start", x, y))

    def on_drag_update(self, rect):
        self.events.append(("update", rect))

    def on_drag_end(self, rect):
        self.events.append(("end", rect))

    def on_drag_cancel(self, reason):
        self.events.append(("cancel", reason))

    def on_user_click(self, x, y, modifiers):
        self.events.append(("click", x, y, modifiers))

    def on_user_move(self, x, y):
        self.events.append(("move", x, y))

    def on_user_key(self, key):
        self.events.append(("key", key))

    def kinds(self):
        return [e[0] for e in self.events]


class GestureGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rec = _Recorder()
        self.enabled = True
        self.focused = True
        self.gate = GestureGate(
            self.rec,
            enabled=lambda: self.enabled,
            modifier=lambda: frozenset({"alt"}),
            game_focused=lambda: self.focused,
            start_allowed=lambda x, y: INV.bounds().expanded(12).contains(x, y),
        )

    def _down(self, x=1000, y=500, mods=ALT, injected=False):
        return self.gate.handle_mouse(MouseEvent("down", x, y, mods, injected))

    def _move(self, x, y, mods=ALT, injected=False):
        return self.gate.handle_mouse(MouseEvent("move", x, y, mods, injected))

    def _up(self, x, y, mods=ALT, injected=False):
        return self.gate.handle_mouse(MouseEvent("up", x, y, mods, injected))

    def test_alt_drag_is_swallowed_and_reported(self) -> None:
        self.assertTrue(self._down(990, 490))
        self.assertTrue(self.gate.dragging)
        self.assertFalse(self._move(1030, 530))      # moves always pass through
        self.assertTrue(self._up(1060, 560))         # matching up is swallowed
        self.assertFalse(self.gate.dragging)
        self.assertEqual(self.rec.kinds(), ["start", "update", "end"])
        self.assertEqual(self.rec.events[-1][1], Rect(990, 490, 1060, 560))

    def test_plain_click_passes_through(self) -> None:
        self.assertFalse(self._down(mods=frozenset()))
        self.assertFalse(self.gate.dragging)
        self.assertFalse(self._up(1000, 500, mods=frozenset()))

    def test_ctrl_click_is_observed_but_not_swallowed(self) -> None:
        ctrl = frozenset({"ctrl"})
        self.assertFalse(self._down(1000, 500, mods=ctrl))
        self.assertEqual(self.rec.events, [("click", 1000, 500, ctrl)])

    def test_modifier_must_match_exactly(self) -> None:
        # Ctrl+Alt is not Alt: avoid hijacking other key combos.
        self.assertFalse(self._down(mods=frozenset({"alt", "ctrl"})))
        self.assertFalse(self.gate.dragging)

    def test_disabled_feature_never_swallows(self) -> None:
        self.enabled = False
        self.assertFalse(self._down())
        self.assertFalse(self.gate.dragging)

    def test_requires_game_focus(self) -> None:
        self.focused = False
        self.assertFalse(self._down())
        self.assertFalse(self.gate.dragging)

    def test_start_outside_inventory_passes_through(self) -> None:
        # Alt+click on ground loot elsewhere on screen must still work.
        self.assertFalse(self._down(200, 200))
        self.assertFalse(self.gate.dragging)

    def test_drag_may_end_outside_the_grid(self) -> None:
        self._down(990, 490)
        self.assertTrue(self._up(10, 10))
        self.assertEqual(self.rec.events[-1], ("end", Rect(10, 10, 990, 490)))

    def test_escape_cancels_and_is_swallowed(self) -> None:
        self._down()
        self.assertTrue(self.gate.handle_key(KeyEvent("esc", True)))
        self.assertTrue(self.gate.handle_key(KeyEvent("esc", False)))
        self.assertFalse(self.gate.dragging)
        self.assertIn(("cancel", "escape"), self.rec.events)
        # The game never saw the down, so the stray up is swallowed too.
        self.assertTrue(self._up(1100, 600))
        self.assertNotIn("end", self.rec.kinds())

    def test_escape_outside_a_drag_passes_through(self) -> None:
        self.assertFalse(self.gate.handle_key(KeyEvent("esc", True)))
        self.assertEqual(self.rec.events, [("key", "esc")])

    def test_losing_focus_mid_drag_cancels(self) -> None:
        self._down()
        self.focused = False
        self._move(1050, 550)
        self.assertFalse(self.gate.dragging)
        self.assertIn(("cancel", "focus"), self.rec.events)

    def test_external_cancel(self) -> None:
        self._down()
        self.gate.cancel("focus")
        self.assertFalse(self.gate.dragging)
        self.assertTrue(self._up(1100, 600))

    def test_injected_events_are_ignored(self) -> None:
        # Our own (experimental) clicks must not start or end a drag.
        self.assertFalse(self._down(injected=True))
        self.assertFalse(self._move(1010, 510, injected=True))
        self.assertEqual(self.rec.events, [])

    def test_user_moves_are_reported_when_idle(self) -> None:
        self._move(5, 6, mods=frozenset())
        self.assertEqual(self.rec.events, [("move", 5, 6)])


class ParseModifierTests(unittest.TestCase):
    def test_parse(self) -> None:
        self.assertEqual(parse_modifier("alt"), frozenset({"alt"}))
        self.assertEqual(parse_modifier("Ctrl+Alt"), frozenset({"ctrl", "alt"}))
        self.assertEqual(parse_modifier("control + shift"),
                         frozenset({"ctrl", "shift"}))

    def test_rejects_empty_or_unknown(self) -> None:
        for bad in ("", "f5", "alt+q"):
            with self.assertRaises(ValueError):
                parse_modifier(bad)


if __name__ == "__main__":
    unittest.main()
