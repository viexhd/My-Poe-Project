"""Tests for the clipboard-item parser + search pipeline.

Network-free: we stub :class:`TradeClient` so the pricing glue can be
exercised without hitting pathofexile.com.
"""
from __future__ import annotations

import datetime as dt
import unittest

from poe_qol.pricer import (
    Category, ParsedItem, TradeClient, parse_item, price_item,
)
from poe_qol.pricer.search import Listing, _listing_from_search, _summarise


# ---- fixtures ------------------------------------------------------------
# These are copied verbatim from in-game Ctrl+C output (with the
# platform-specific line endings normalised). Keeping them in-tree
# means a future clipboard-format tweak breaks a test rather than
# silently mis-pricing items.

CURRENCY = """\
Item Class: Stackable Currency
Rarity: Currency
Divine Orb
--------
Stack Size: 3/10
--------
Randomises the values of the random modifiers on an item
--------
Right click this item then left click a magic, rare or unique item to apply it. Shift click to unstack.
"""

UNIQUE = """\
Item Class: Wands
Rarity: Unique
Sire of Shards
Sage Wand
--------
Wand
Quality: +20% (augmented)
Physical Damage: 26-48 (augmented)
Critical Strike Chance: 7.00%
Attacks per Second: 1.40
--------
Requirements:
Level: 38
Int: 83
--------
Sockets: B-B-B
--------
Item Level: 72
--------
20% increased Spell Damage (implicit)
--------
Adds 7 to 16 Cold Damage to Spells
Skills fire 4 additional Projectiles
+1 to Level of all Lightning Spell Skill Gems
Projectiles are fired in a circle
--------
A symbol of endless knowledge,
ready to spread its wisdom
at the snap of a finger.
"""

RARE_GLOVES = """\
Item Class: Gloves
Rarity: Rare
Pandemonium Hand
Stealth Gloves
--------
Quality: +20% (augmented)
Energy Shield: 60 (augmented)
--------
Requirements:
Level: 62
Int: 75
--------
Sockets: B-B B-B
--------
Item Level: 86
--------
+25 to maximum Energy Shield (implicit)
--------
Adds 1 to 15 Lightning Damage to Attacks
+71 to maximum Life
+30 to maximum Energy Shield
15% increased Stun and Block Recovery
--------
Note: ~price 40 chaos
"""

MAP = """\
Item Class: Maps
Rarity: Rare
Enigma Reef
Toxic Sewer Map
--------
Map Tier: 16
Item Quantity: +57% (augmented)
Item Rarity: +45% (augmented)
Monster Pack Size: +25% (augmented)
--------
Item Level: 85
--------
Monsters reflect 18% of Elemental Damage
Monsters cannot be Stunned
"""

CORRUPTED_UNIQUE = """\
Item Class: Amulets
Rarity: Unique
Carnage Heart
Onyx Amulet
--------
+10 to all Attributes (implicit)
--------
+29 to Strength
+35 to Dexterity
30% increased Damage
40% increased Evasion Rating while on Low Life
Extra gore
--------
Corrupted
"""

NOT_AN_ITEM = "just some random text copied from discord"


# ---- parser tests --------------------------------------------------------

class ParserTests(unittest.TestCase):

    def test_currency(self):
        it = parse_item(CURRENCY)
        assert it is not None
        self.assertEqual(it.name, "Divine Orb")
        self.assertEqual(it.rarity, "Currency")
        self.assertEqual(it.category, Category.CURRENCY)
        self.assertEqual(it.stack_size, (3, 10))
        self.assertTrue(it.is_stackable_currency_like)

    def test_unique(self):
        it = parse_item(UNIQUE)
        assert it is not None
        self.assertEqual(it.name, "Sire of Shards")
        self.assertEqual(it.base_type, "Sage Wand")
        self.assertEqual(it.rarity, "Unique")
        self.assertEqual(it.category, Category.UNIQUE)
        self.assertEqual(it.item_level, 72)
        self.assertEqual(it.quality, 20)
        self.assertIn("20% increased Spell Damage", it.implicits)
        self.assertIn("Skills fire 4 additional Projectiles", it.explicits)
        self.assertEqual(it.trade_name, "Sire of Shards")
        self.assertEqual(it.trade_type, "Sage Wand")

    def test_rare_gloves(self):
        it = parse_item(RARE_GLOVES)
        assert it is not None
        self.assertEqual(it.rarity, "Rare")
        self.assertEqual(it.base_type, "Stealth Gloves")
        self.assertEqual(it.category, Category.EQUIPMENT)
        self.assertIn("+25 to maximum Energy Shield", it.implicits)
        self.assertEqual(len(it.explicits), 4)
        self.assertEqual(it.note, "~price 40 chaos")
        # Uniques get a name on the trade query; rares do not.
        self.assertEqual(it.trade_name, "")
        self.assertEqual(it.trade_type, "Stealth Gloves")

    def test_map(self):
        it = parse_item(MAP)
        assert it is not None
        self.assertEqual(it.category, Category.MAP)
        self.assertEqual(it.map_tier, 16)
        self.assertEqual(it.base_type, "Toxic Sewer Map")
        self.assertIn("Monsters reflect 18% of Elemental Damage",
                      it.explicits)

    def test_corrupted_flag(self):
        it = parse_item(CORRUPTED_UNIQUE)
        assert it is not None
        self.assertTrue(it.corrupted)
        self.assertEqual(it.category, Category.UNIQUE)
        self.assertIn("+10 to all Attributes", it.implicits)

    def test_non_item_returns_none(self):
        self.assertIsNone(parse_item(NOT_AN_ITEM))
        self.assertIsNone(parse_item(""))


# ---- search / stale detection -------------------------------------------

class _StubClient(TradeClient):
    """Returns canned search + fetch responses without touching the
    network. Lets us exercise ``price_item`` and ``_summarise`` end
    to end."""

    def __init__(self, *, search_total: int = 10,
                 listings: list[Listing] | None = None):
        super().__init__()
        self._total = search_total
        self._listings = listings or []

    # Override I/O.
    def search(self, league, query):
        return ("STUBID",
                [f"h{i}" for i in range(len(self._listings))],
                self._total)

    def exchange(self, league, want, have="chaos"):
        return ("STUBX",
                [f"x{i}" for i in range(len(self._listings))],
                self._total)

    def fetch(self, ids, search_id, *, exchange=False):
        # Return dicts that _listing_from_search / _from_exchange can
        # consume — but since we also override ``price_item``? No, we
        # don't. Instead, shape the dicts so the real response mapper
        # reconstructs our pre-built Listing objects.
        out = []
        for lst in self._listings:
            indexed = lst.indexed.isoformat().replace("+00:00", "Z") if lst.indexed else None
            out.append({
                "listing": {
                    "indexed": indexed,
                    "price": {
                        "amount": lst.price_amount,
                        "currency": lst.price_currency,
                    },
                    "account": {
                        "lastCharacterName": lst.seller,
                        "online": {"status": "online"} if lst.online else None,
                    },
                }
            })
        return out


def _utc(delta_hours: float) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=delta_hours)


class StaleDetectionTests(unittest.TestCase):

    def test_stale_listings_lift_effective_floor(self):
        """Two cheap stale listings (offline + old) + one fresh listing:
        raw floor anchors to the stale price; effective floor skips to
        the fresh listing and a note surfaces the gap."""
        listings = [
            Listing("StaleGuy1",  40.0, "chaos", _utc(72), online=False),
            Listing("StaleGuy2",  41.0, "chaos", _utc(50), online=False),
            Listing("OnlineGuy",  55.0, "chaos", _utc(1),  online=True),
            Listing("Another",    56.0, "chaos", _utc(1),  online=True),
        ]
        client = _StubClient(listings=listings)
        unique = parse_item(UNIQUE)
        assert unique is not None
        r = price_item(unique, league="Mirage", client=client)
        self.assertEqual(r.floor, 40.0)
        self.assertEqual(r.effective_floor, 55.0)
        self.assertEqual(r.stale_count, 2)
        self.assertTrue(any("effective floor" in n for n in r.notes))

    def test_all_stale_warns(self):
        listings = [
            Listing("S1", 5.0, "chaos", _utc(48), online=False),
            Listing("S2", 6.0, "chaos", _utc(48), online=False),
        ]
        client = _StubClient(listings=listings)
        unique = parse_item(UNIQUE)
        assert unique is not None
        r = price_item(unique, league="Mirage", client=client)
        self.assertIsNone(r.effective_floor)
        self.assertTrue(any("every visible listing" in n.lower()
                            for n in r.notes))

    def test_online_listings_never_stale(self):
        fresh = Listing("Live", 10.0, "chaos", _utc(200), online=True)
        self.assertFalse(fresh.stale)


class SummariseDirectTests(unittest.TestCase):
    """Narrow tests on _summarise so we can cover edge cases (no
    timestamp, everything online, empty list) without the stub
    plumbing."""

    def _make(self, listings):
        from poe_qol.pricer.search import PriceResult
        r = PriceResult(query_label="x", search_url="", total=len(listings),
                        listings=listings)
        _summarise(r)
        return r

    def test_empty(self):
        r = self._make([])
        self.assertEqual(r.notes, ["No active listings found."])

    def test_missing_indexed_not_treated_stale(self):
        r = self._make([
            Listing("A", 1.0, "chaos", None, online=False),
            Listing("B", 2.0, "chaos", None, online=False),
        ])
        self.assertEqual(r.stale_count, 0)
        self.assertEqual(r.floor, 1.0)
        self.assertEqual(r.effective_floor, 1.0)


if __name__ == "__main__":
    unittest.main()
