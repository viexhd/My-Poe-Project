"""Grid generation + slot-selection filtering tests for GridDumpMacro.

Run with:  python -m unittest discover -s poe_qol/tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class InventoryGridTests(unittest.TestCase):
    def test_serpentine_and_filter(self) -> None:
        from poe_qol.macros.inventory_dump import (
            build_serpentine, filter_selected,
        )
        pts = build_serpentine((0, 0), (10, 10), 3, 3)
        # 3x3 = 9 points
        self.assertEqual(len(pts), 9)
        # (row, col, (x, y))
        self.assertEqual(pts[0], (0, 0, (0, 0)))
        self.assertEqual(pts[1], (1, 0, (0, 10)))
        self.assertEqual(pts[3], (2, 1, (10, 20)))   # col 1 starts at bottom
        # selection filter: only (0,0) and (2,2)
        filt = filter_selected(pts, [(0, 0), (2, 2)])
        self.assertEqual(len(filt), 2)
        self.assertEqual({(p[0], p[1]) for p in filt}, {(0, 0), (2, 2)})

    def test_empty_selection_keeps_all(self) -> None:
        from poe_qol.macros.inventory_dump import (
            build_row_major, filter_selected,
        )
        pts = build_row_major((0, 0), (10, 10), 2, 2)
        self.assertEqual(len(filter_selected(pts, [])), 4)


if __name__ == "__main__":
    unittest.main()
