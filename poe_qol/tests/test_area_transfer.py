"""Transfer strategies for the Alt+drag area selection, plus the
empty/occupied slot classifier.

* ManualTransfer only tracks which highlighted slots the player has
  Ctrl-clicked themselves. It sends no input.
* ExperimentalCtrlClickTransfer Ctrl-clicks every slot for the player.
  It is NOT GGG-compliant (many game actions per gesture); these tests
  pin its safety rails: off unless acknowledged, Ctrl always released,
  aborts on F12 / focus loss / user input.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poe_qol.area_select.grid import GridGeometry  # noqa: E402
from poe_qol.area_select.settings import ExperimentalSettings  # noqa: E402
from poe_qol.area_select.transfer import (  # noqa: E402
    ManualTransfer, TransferPlan, order_slots,
)

INV = GridGeometry(origin=(1000.0, 500.0), cell=(50.0, 50.0), cols=12, rows=5)
CTRL = frozenset({"ctrl"})


class _Listener:
    def __init__(self) -> None:
        self.progress: list[tuple[int, int, tuple]] = []
        self.finished: list[tuple[str, str]] = []

    def on_progress(self, done, total, remaining):
        self.progress.append((done, total, tuple(remaining)))

    def on_finished(self, status, message):
        self.finished.append((status, message))


class OrderTests(unittest.TestCase):
    slots = [(1, 1), (0, 0), (1, 0), (0, 1)]

    def test_row_major(self) -> None:
        self.assertEqual(order_slots(self.slots, "row_major"),
                         [(0, 0), (0, 1), (1, 0), (1, 1)])

    def test_column_serpentine(self) -> None:
        self.assertEqual(order_slots(self.slots, "column_serpentine"),
                         [(0, 0), (1, 0), (1, 1), (0, 1)])

    def test_plan_points_are_rounded_slot_centres(self) -> None:
        plan = TransferPlan("inventory", INV, ((0, 0), (2, 3)))
        self.assertEqual(plan.points(), [(1000, 500), (1150, 600)])


class ManualTransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.t = ManualTransfer()
        self.l = _Listener()
        self.plan = TransferPlan("inventory", INV, ((0, 0), (0, 1), (1, 0)))

    def test_start_reports_everything_remaining(self) -> None:
        self.t.start(self.plan, self.l)
        self.assertTrue(self.t.active)
        self.assertEqual(self.l.progress[-1], (0, 3, ((0, 0), (0, 1), (1, 0))))

    def test_ctrl_click_on_a_highlighted_slot_ticks_it_off(self) -> None:
        self.t.start(self.plan, self.l)
        self.t.user_clicked(1052, 505, CTRL)
        self.assertEqual(self.l.progress[-1], (1, 3, ((0, 0), (1, 0))))

    def test_clicks_without_ctrl_or_off_plan_are_ignored(self) -> None:
        self.t.start(self.plan, self.l)
        self.t.user_clicked(1000, 500, frozenset())
        self.t.user_clicked(1300, 700, CTRL)
        self.assertEqual(len(self.l.progress), 1)

    def test_finishes_when_all_slots_clicked(self) -> None:
        self.t.start(self.plan, self.l)
        for x, y in ((1000, 500), (1050, 500), (1000, 550)):
            self.t.user_clicked(x, y, CTRL)
        self.assertEqual(self.l.finished, [("done", "All 3 slots clicked")])
        self.assertFalse(self.t.active)

    def test_cancel(self) -> None:
        self.t.start(self.plan, self.l)
        self.t.cancel("escape")
        self.assertEqual(self.l.finished[-1][0], "cancelled")
        self.assertFalse(self.t.active)

    def test_sends_no_input(self) -> None:
        # ManualTransfer has no sender at all.
        self.assertFalse(hasattr(self.t, "sender"))


class _FakeSender:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def key_down(self, k):
        self.calls.append(("down", k))

    def key_up(self, k):
        self.calls.append(("up", k))

    def click(self, x, y, button="left"):
        self.calls.append(("click", x, y))


class ExperimentalTransferTests(unittest.TestCase):
    def _make(self, **settings):
        from poe_qol.experimental.bulk_ctrl_click import (
            ExperimentalCtrlClickTransfer,
        )
        self.sender = _FakeSender()
        self.allowed = True
        self.focused = True
        self.mod_held = False
        self.sleeps: list[float] = []
        opts = {"acknowledged": True, "click_delay_ms": 50}
        opts.update(settings)
        self.t = ExperimentalCtrlClickTransfer(
            self.sender,
            settings=ExperimentalSettings(**opts),
            is_allowed=lambda: self.allowed,
            game_focused=lambda: self.focused,
            modifier_held=lambda: self.mod_held,
            sleep=self._sleep,
            clock=self._clock,
            run_async=False,
        )
        self._now = 0.0
        self.l = _Listener()
        return self.t

    def _sleep(self, s):
        self.sleeps.append(s)
        self._now += s
        hook = getattr(self, "on_sleep", None)
        if hook:
            hook(len(self.sleeps))

    def _clock(self):
        return self._now

    plan = TransferPlan("inventory", INV, ((0, 0), (0, 1), (1, 0)))

    def test_requires_acknowledgement(self) -> None:
        t = self._make(acknowledged=False)
        t.start(self.plan, self.l)
        self.assertEqual(self.sender.calls, [])
        self.assertEqual(self.l.finished[-1][0], "error")

    def test_ctrl_clicks_each_slot_then_releases_ctrl(self) -> None:
        t = self._make()
        t.start(self.plan, self.l)
        self.assertEqual(self.sender.calls, [
            ("down", "ctrl"),
            ("click", 1000, 500), ("click", 1050, 500), ("click", 1000, 550),
            ("up", "ctrl"),
        ])
        self.assertEqual(self.l.finished[-1][0], "done")
        self.assertEqual(self.l.progress[-1][:2], (3, 3))

    def test_delay_has_a_floor(self) -> None:
        t = self._make(click_delay_ms=1)
        t.start(self.plan, self.l)
        self.assertTrue(all(s >= 0.02 for s in self.sleeps), self.sleeps)

    def test_max_slots_caps_the_run(self) -> None:
        t = self._make(max_slots=2)
        t.start(self.plan, self.l)
        clicks = [c for c in self.sender.calls if c[0] == "click"]
        self.assertEqual(len(clicks), 2)

    def test_emergency_stop_aborts_and_releases_ctrl(self) -> None:
        t = self._make()
        self.on_sleep = lambda n: setattr(self, "allowed", False)
        t.start(self.plan, self.l)
        clicks = [c for c in self.sender.calls if c[0] == "click"]
        self.assertEqual(len(clicks), 1)
        self.assertEqual(self.sender.calls[-1], ("up", "ctrl"))
        self.assertEqual(self.l.finished[-1][0], "aborted")

    def test_focus_loss_aborts(self) -> None:
        t = self._make()
        self.on_sleep = lambda n: setattr(self, "focused", False)
        t.start(self.plan, self.l)
        self.assertEqual(self.sender.calls[-1], ("up", "ctrl"))
        self.assertEqual(self.l.finished[-1][0], "aborted")

    def test_user_mouse_movement_aborts(self) -> None:
        t = self._make(abort_move_px=25)
        # The cursor is parked on slot (0,0) after the first click; a
        # real mouse move far from it means the player took over.
        self.on_sleep = lambda n: t.user_moved(1200, 900)
        t.start(self.plan, self.l)
        self.assertEqual(self.l.finished[-1][0], "aborted")

    def test_small_jitter_does_not_abort(self) -> None:
        t = self._make(abort_move_px=25)
        # A few px around wherever the cursor was last parked.
        self.on_sleep = lambda n: t.user_moved(t.cursor_target[0] + 3,
                                               t.cursor_target[1] - 2)
        t.start(self.plan, self.l)
        self.assertEqual(self.l.finished[-1][0], "done")

    def test_waits_for_selection_modifier_release(self) -> None:
        # Alt is still held right after the drag; Ctrl+Alt+click must
        # not reach the game.
        t = self._make(modifier_release_timeout_ms=200)
        self.mod_held = True
        self.on_sleep = lambda n: setattr(self, "mod_held", n < 3)
        t.start(self.plan, self.l)
        self.assertEqual(self.l.finished[-1][0], "done")
        self.assertEqual(self.sender.calls[0], ("down", "ctrl"))

    def test_gives_up_if_modifier_never_released(self) -> None:
        t = self._make(modifier_release_timeout_ms=200)
        self.mod_held = True
        t.start(self.plan, self.l)
        self.assertEqual(self.sender.calls, [])
        self.assertEqual(self.l.finished[-1][0], "aborted")

    def test_cancel_before_start_of_clicks(self) -> None:
        t = self._make()
        self.on_sleep = lambda n: t.cancel("escape")
        t.start(self.plan, self.l)
        self.assertEqual(self.sender.calls[-1], ("up", "ctrl"))
        self.assertEqual(self.l.finished[-1][0], "cancelled")


class OccupancyTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy not installed (vision extra)")
        self.np = np

    def test_textured_cells_are_occupied_flat_dark_cells_empty(self) -> None:
        np = self.np
        from poe_qol.area_select.occupancy import (
            OccupancyThresholds, classify_slots,
        )
        g = GridGeometry(origin=(25.0, 25.0), cell=(50.0, 50.0), cols=3, rows=1)
        img = np.full((50, 150, 3), 22, dtype=np.uint8)     # dark, flat
        rng = np.random.default_rng(1)
        img[:, 50:100] = rng.integers(0, 255, (50, 50, 3), dtype=np.uint8)
        img[:, 100:150] = 160                                 # bright item
        res = classify_slots(img, (0, 0), g, [(0, 0), (0, 1), (0, 2)],
                             OccupancyThresholds())
        self.assertFalse(res[(0, 0)].occupied)
        self.assertTrue(res[(0, 1)].occupied)
        self.assertTrue(res[(0, 2)].occupied)

    def test_image_offset_and_out_of_frame_slots(self) -> None:
        np = self.np
        from poe_qol.area_select.occupancy import (
            OccupancyThresholds, classify_slots,
        )
        g = GridGeometry(origin=(525.0, 325.0), cell=(50.0, 50.0), cols=2, rows=1)
        img = np.full((50, 50, 3), 200, dtype=np.uint8)      # covers slot (0,0) only
        res = classify_slots(img, (500, 300), g, [(0, 0), (0, 1)],
                             OccupancyThresholds())
        self.assertTrue(res[(0, 0)].occupied)
        self.assertNotIn((0, 1), res)  # unknown, not guessed


if __name__ == "__main__":
    unittest.main()
