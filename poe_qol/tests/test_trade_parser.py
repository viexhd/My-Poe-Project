"""Parser + trade-query builder unit tests.

Run with:  python -m pytest poe_qol/tests  (or plain unittest).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poe_qol.trade import ModMap, build_query, parse  # noqa: E402


class ParserTests(unittest.TestCase):
    def test_single_exclusion(self) -> None:
        q = parse("!reflect")
        self.assertEqual(len(q.groups), 1)
        g = q.groups[0]
        self.assertEqual(len(g.atoms), 1)
        self.assertEqual(g.atoms[0].mod, "reflect")
        self.assertTrue(g.atoms[0].negate)

    def test_or_group_all_negative(self) -> None:
        q = parse("!reflect|!no regen")
        self.assertEqual(len(q.groups), 1)
        g = q.groups[0]
        self.assertEqual(len(g.atoms), 2)
        self.assertTrue(g.all_negative)
        self.assertFalse(g.all_positive)

    def test_top_level_and_split(self) -> None:
        q = parse("!reflect, !no regen")
        self.assertEqual(len(q.groups), 2)
        self.assertEqual(q.groups[0].atoms[0].mod, "reflect")
        self.assertEqual(q.groups[1].atoms[0].mod, "no regen")

    def test_multi_word_mod_without_quotes(self) -> None:
        q = parse("!no regen")
        self.assertEqual(q.groups[0].atoms[0].mod, "no regen")
        self.assertTrue(q.groups[0].atoms[0].negate)

    def test_quoted_phrase_survives(self) -> None:
        q = parse('!"no regen"|reflect')
        atoms = q.groups[0].atoms
        self.assertEqual(atoms[0].mod, "no regen")
        self.assertTrue(atoms[0].negate)
        self.assertEqual(atoms[1].mod, "reflect")
        self.assertFalse(atoms[1].negate)

    def test_empty_input(self) -> None:
        self.assertEqual(len(parse("").groups), 0)


class BuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mm = ModMap.load(ROOT / "config" / "map_mods.yaml")

    def test_resolve_alias(self) -> None:
        hit = self.mm.resolve("no regen")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit[0], "no regeneration")

    def test_and_of_negations(self) -> None:
        q = build_query(parse("!reflect, !no regen"), self.mm, league="Affliction")
        stats = q["query"]["stats"]
        self.assertEqual(len(stats), 2)
        for s in stats:
            self.assertEqual(s["type"], "not")
            self.assertEqual(len(s["filters"]), 1)
        self.assertEqual(q["__league__"], "Affliction")

    def test_or_of_negations_becomes_count_max(self) -> None:
        q = build_query(parse("!reflect|!no regen"), self.mm)
        stats = q["query"]["stats"]
        self.assertEqual(len(stats), 1)
        s = stats[0]
        self.assertEqual(s["type"], "count")
        self.assertEqual(s["value"], {"max": 1})
        self.assertEqual(len(s["filters"]), 2)

    def test_or_of_positives_becomes_count_min(self) -> None:
        q = build_query(parse("reflect|vuln"), self.mm)
        s = q["query"]["stats"][0]
        self.assertEqual(s["type"], "count")
        self.assertEqual(s["value"], {"min": 1})

    def test_unknown_mod_is_skipped(self) -> None:
        q = build_query(parse("!totally_not_a_real_mod, !reflect"), self.mm)
        # unknown group dropped, known one kept
        self.assertEqual(len(q["query"]["stats"]), 1)


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
