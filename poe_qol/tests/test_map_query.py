"""Characterisation tests for the live Map Search pipeline.

Covers ``MapDataset`` loading of the shipped ``config/map_mods.yaml``
(v2 schema), ``build_map_query`` payload shape, and ``build_url`` in
offline ``copy`` mode. No network access.

Run with:  python -m unittest discover -s poe_qol/tests
"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poe_qol.trade import MapDataset, build_map_query, build_url  # noqa: E402
from poe_qol.trade.builder import _strip_stat_id  # noqa: E402

MAP_MODS = ROOT / "config" / "map_mods.yaml"


class MapDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ds = MapDataset.load(MAP_MODS)

    def test_shipped_file_loads_with_content(self) -> None:
        self.assertTrue(self.ds.item_types)
        self.assertTrue(self.ds.categories)
        self.assertTrue(self.ds.mods)
        self.assertTrue(self.ds.presets)

    def test_every_mod_has_known_category_and_stat_id(self) -> None:
        cat_ids = {c.id for c in self.ds.categories}
        for m in self.ds.mods:
            self.assertIn(m.category, cat_ids, m.id)
            self.assertTrue(m.stat_id.startswith(("explicit.", "pseudo.",
                                                  "implicit.", "enchant.")),
                            m.stat_id)

    def test_presets_reference_existing_mods(self) -> None:
        mod_ids = {m.id for m in self.ds.mods}
        for p in self.ds.presets:
            for mid in p.excluded:
                self.assertIn(mid, mod_ids, f"preset {p.id} -> {mid}")

    def test_mod_search_matches_name_and_tags(self) -> None:
        m = self.ds.mod("no_regen")
        assert m is not None
        self.assertTrue(m.matches("regen"))
        self.assertTrue(m.matches("RF"))          # tag, case-insensitive
        self.assertTrue(m.matches(""))            # empty needle matches all
        self.assertFalse(m.matches("zzz-not-a-mod"))


class BuildMapQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ds = MapDataset.load(MAP_MODS)

    def test_exclusion_is_single_count_max_zero_group(self) -> None:
        q = build_map_query(self.ds, item_type_id="map_t16",
                            excluded_mod_ids=["no_regen", "less_recovery"],
                            league="Mirage")
        stats = q["query"]["stats"]
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["type"], "count")
        self.assertEqual(stats[0]["value"], {"max": 0})
        # Inner filters carry no `value` (a value makes the API 400).
        for f in stats[0]["filters"]:
            self.assertEqual(set(f), {"id", "disabled"})
        self.assertEqual(q["__league__"], "Mirage")

    def test_tier_category_and_dataset_defaults_applied(self) -> None:
        q = build_map_query(self.ds, item_type_id="map_t16",
                            excluded_mod_ids=[])
        f = q["query"]["filters"]
        self.assertEqual(f["type_filters"]["filters"]["category"],
                         {"option": "map"})
        self.assertEqual(f["map_filters"]["filters"]["map_tier"],
                         {"min": 16, "max": 16})
        self.assertEqual(f["type_filters"]["filters"]["rarity"],
                         {"option": self.ds.defaults.rarity})
        self.assertEqual(q["query"]["stats"], [])

    def test_explicit_none_disables_default_filters(self) -> None:
        q = build_map_query(self.ds, item_type_id="any",
                            excluded_mod_ids=[], rarity=None, corrupted=None)
        self.assertNotIn("filters", q["query"])

    def test_unknown_mod_ids_are_skipped(self) -> None:
        q = build_map_query(self.ds, item_type_id="map_t16",
                            excluded_mod_ids=["not_a_real_mod"])
        self.assertEqual(q["query"]["stats"], [])


class BuildUrlTests(unittest.TestCase):
    def test_copy_mode_encodes_payload_without_private_keys(self) -> None:
        ds = MapDataset.load(MAP_MODS)
        q = build_map_query(ds, item_type_id="map_t16",
                            excluded_mod_ids=["no_regen"], league="Mirage")
        url = build_url(q, mode="copy",
                        base_site="https://www.pathofexile.com/trade/search")
        base, _, query = url.partition("?q=")
        self.assertEqual(base, "https://www.pathofexile.com/trade/search/Mirage")
        payload = json.loads(urllib.parse.unquote(query))
        self.assertNotIn("__league__", payload)
        self.assertEqual(payload["query"]["stats"][0]["value"], {"max": 0})

    def test_strip_stat_id_drops_emptied_groups(self) -> None:
        payload = {"query": {"stats": [
            {"type": "count", "filters": [{"id": "a"}, {"id": "b"}]},
            {"type": "count", "filters": [{"id": "a"}]},
        ]}}
        self.assertTrue(_strip_stat_id(payload, "a"))
        self.assertEqual(payload["query"]["stats"],
                         [{"type": "count", "filters": [{"id": "b"}]}])
        self.assertFalse(_strip_stat_id(payload, "zzz"))


if __name__ == "__main__":
    unittest.main()
