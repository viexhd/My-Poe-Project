"""Inventory grid mapping for the Alt+drag area selection.

Pure geometry: no Qt, no Win32, no screen access.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poe_qol.area_select.grid import (  # noqa: E402
    GridGeometry, Rect, resolve_geometry,
)
from poe_qol.vision.window import WindowRect  # noqa: E402

# A 12x5 grid whose slot (0,0) centre is at (1000, 500) with 50 px cells.
# Slot (r, c) centre = (1000 + 50c, 500 + 50r); outer bounds are
# x 975..1575, y 475..725.
INV = GridGeometry(origin=(1000.0, 500.0), cell=(50.0, 50.0), cols=12, rows=5)


class RectTests(unittest.TestCase):
    def test_from_points_normalises_any_drag_direction(self) -> None:
        a = Rect.from_points(10, 20, 110, 220)
        b = Rect.from_points(110, 220, 10, 20)     # bottom-right -> top-left
        c = Rect.from_points(110, 20, 10, 220)     # top-right -> bottom-left
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertEqual((a.left, a.top, a.right, a.bottom), (10, 20, 110, 220))
        self.assertEqual((a.width, a.height), (100, 200))

    def test_contains_is_inclusive(self) -> None:
        r = Rect(0, 0, 10, 10)
        self.assertTrue(r.contains(0, 0))
        self.assertTrue(r.contains(10, 10))
        self.assertFalse(r.contains(10.01, 5))


class GridGeometryTests(unittest.TestCase):
    def test_slot_center_and_rect(self) -> None:
        self.assertEqual(INV.slot_center((0, 0)), (1000.0, 500.0))
        self.assertEqual(INV.slot_center((4, 11)), (1550.0, 700.0))
        self.assertEqual(INV.slot_rect((1, 2)), Rect(1075, 525, 1125, 575))

    def test_bounds_cover_every_cell(self) -> None:
        self.assertEqual(INV.bounds(), Rect(975, 475, 1575, 725))

    def test_slot_at_maps_screen_point_to_cell(self) -> None:
        self.assertEqual(INV.slot_at(1000, 500), (0, 0))
        self.assertEqual(INV.slot_at(1574, 724), (4, 11))
        self.assertEqual(INV.slot_at(1101, 549), (1, 2))
        self.assertIsNone(INV.slot_at(974, 500))
        self.assertIsNone(INV.slot_at(1000, 726))

    def test_rejects_degenerate_geometry(self) -> None:
        with self.assertRaises(ValueError):
            GridGeometry(origin=(0, 0), cell=(0, 50), cols=12, rows=5)
        with self.assertRaises(ValueError):
            GridGeometry(origin=(0, 0), cell=(50, 50), cols=0, rows=5)

    def test_from_bounds(self) -> None:
        g = GridGeometry.from_bounds(Rect(975, 475, 1575, 725), cols=12, rows=5)
        self.assertEqual(g, INV)


class SlotsInRectTests(unittest.TestCase):
    """Only slots whose centre falls inside the rectangle are selected."""

    def test_single_slot(self) -> None:
        r = Rect.from_points(990, 490, 1010, 510)
        self.assertEqual(INV.slots_in_rect(r), [(0, 0)])

    def test_rect_not_covering_a_centre_selects_nothing(self) -> None:
        r = Rect.from_points(1005, 505, 1045, 545)  # inside one cell, misses centres
        self.assertEqual(INV.slots_in_rect(r), [])

    def test_adjacent_block(self) -> None:
        r = Rect.from_points(990, 490, 1060, 560)
        self.assertEqual(INV.slots_in_rect(r), [(0, 0), (0, 1), (1, 0), (1, 1)])

    def test_entire_row(self) -> None:
        r = Rect.from_points(960, 590, 1600, 610)
        self.assertEqual(INV.slots_in_rect(r), [(2, c) for c in range(12)])

    def test_entire_column(self) -> None:
        r = Rect.from_points(1140, 450, 1160, 750)
        self.assertEqual(INV.slots_in_rect(r), [(r_, 3) for r_ in range(5)])

    def test_entire_inventory(self) -> None:
        r = Rect.from_points(0, 0, 4000, 4000)
        sel = INV.slots_in_rect(r)
        self.assertEqual(len(sel), 60)
        self.assertEqual(sel[0], (0, 0))
        self.assertEqual(sel[-1], (4, 11))

    def test_reverse_drag_matches_forward_drag(self) -> None:
        fwd = INV.slots_in_rect(Rect.from_points(990, 490, 1110, 560))
        rev = INV.slots_in_rect(Rect.from_points(1110, 560, 990, 490))
        self.assertEqual(fwd, rev)
        self.assertEqual(len(fwd), 6)

    def test_partially_outside_the_grid_is_clipped(self) -> None:
        # Starts far left/above the grid, ends on slot (1, 1).
        r = Rect.from_points(500, 100, 1060, 560)
        self.assertEqual(INV.slots_in_rect(r), [(0, 0), (0, 1), (1, 0), (1, 1)])

    def test_fully_outside_selects_nothing(self) -> None:
        self.assertEqual(INV.slots_in_rect(Rect(0, 0, 900, 400)), [])


class ResolveGeometryTests(unittest.TestCase):
    def _section(self, **over):
        sec = {
            "grid": {"origin": [1000, 500], "cell_size": [50, 50],
                     "cols": 12, "rows": 5},
            "origin_relative_to_window": None,
        }
        sec.update(over)
        return sec

    def test_absolute_origin(self) -> None:
        self.assertEqual(resolve_geometry(self._section()), INV)

    def test_grid_dimensions_come_from_config(self) -> None:
        sec = self._section()
        sec["grid"]["cols"], sec["grid"]["rows"] = 12, 6
        g = resolve_geometry(sec)
        self.assertEqual((g.cols, g.rows), (12, 6))
        self.assertEqual(len(g.slots_in_rect(Rect(0, 0, 9999, 9999))), 72)

    def test_bounds_override_origin(self) -> None:
        sec = self._section()
        sec["grid"]["bounds"] = [975, 475, 1575, 725]
        sec["grid"]["origin"] = [0, 0]
        self.assertEqual(resolve_geometry(sec), INV)

    def test_window_relative_origin_follows_the_window(self) -> None:
        sec = self._section(origin_relative_to_window={
            "anchor": "top_right", "offset": [-920, 500]})
        win = WindowRect(0, 0, 1920, 1080)
        g = resolve_geometry(sec, win)
        self.assertEqual(g.origin, (1000.0, 500.0))
        moved = resolve_geometry(sec, WindowRect(100, 50, 2020, 1130))
        self.assertEqual(moved.origin, (1100.0, 550.0))

    def test_window_relative_ignored_without_window(self) -> None:
        sec = self._section(origin_relative_to_window={
            "anchor": "top_right", "offset": [-920, 500]})
        self.assertEqual(resolve_geometry(sec, None), INV)

    def test_resolution_change_scales_offset_and_cell_by_height(self) -> None:
        sec = self._section(origin_relative_to_window={
            "anchor": "top_right", "offset": [-920, 500],
            "window_size": [1920, 1080]})
        g = resolve_geometry(sec, WindowRect(0, 0, 2560, 1440))
        scale = 1440 / 1080
        self.assertAlmostEqual(g.cell[0], 50 * scale)
        self.assertAlmostEqual(g.cell[1], 50 * scale)
        self.assertAlmostEqual(g.origin[0], 2560 - 920 * scale)
        self.assertAlmostEqual(g.origin[1], 500 * scale)

    def test_same_resolution_is_unscaled(self) -> None:
        sec = self._section(origin_relative_to_window={
            "anchor": "top_right", "offset": [-920, 500],
            "window_size": [1920, 1080]})
        self.assertEqual(resolve_geometry(sec, WindowRect(0, 0, 1920, 1080)), INV)


if __name__ == "__main__":
    unittest.main()
