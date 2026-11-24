"""Turn the items of a stash tab (GGG ``Item`` objects) into priced lines.

Matching rules, in order:

* **unique** (frameType 3, relics 9/10): unique name + base + links;
* **gem** (frameType 4): name + level + quality + corrupted;
* **map** (has a "Map Tier" property, not unique): base name + tier;
* everything else, mostly stackables: the base type / type line on the
  exchange price list, times the stack size.

Items with no market price (rares, magic gear, unknown bases) count as
*unpriced*, as on Wealthy Exile.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .pricing import PriceBook

_MARKUP = re.compile(r"<<[^>]*>>")
_INT = re.compile(r"-?\d+")


def clean(s: str | None) -> str:
    return _MARKUP.sub("", str(s or "")).strip()


@dataclass
class PricedItem:
    name: str                 # display name ("Divine Orb", "Crimson Temple Map (T16)")
    category: str
    quantity: float
    unit_chaos: float | None  # None = no price
    icon: str = ""

    @property
    def total_chaos(self) -> float:
        return (self.unit_chaos or 0.0) * self.quantity


def _prop_int(item: dict, prop: str) -> int | None:
    for p in item.get("properties") or []:
        if isinstance(p, dict) and clean(p.get("name")) == prop:
            for v in p.get("values") or []:
                if isinstance(v, (list, tuple)) and v:
                    m = _INT.search(str(v[0]))
                    if m:
                        return int(m.group())
    return None


def links_of(item: dict) -> int:
    groups: dict[int, int] = {}
    for s in item.get("sockets") or []:
        if isinstance(s, dict):
            g = int(s.get("group") or 0)
            groups[g] = groups.get(g, 0) + 1
    return max(groups.values(), default=0)


def price_item(item: dict, book: PriceBook) -> PricedItem:
    frame = int(item.get("frameType") or 0)
    name = clean(item.get("name"))
    type_line = clean(item.get("typeLine"))
    base = clean(item.get("baseType")) or type_line
    qty = float(item.get("stackSize") or 1)
    icon = str(item.get("icon") or "")

    if frame in (3, 9, 10) and name:
        unit = book.unique_price(name, base, links_of(item))
        if unit is None:
            # unique maps/jewels are sometimes listed by type line
            hit = book.stack_price(name)
            unit = hit[0] if hit else None
        return PricedItem(name, "Unique", qty, unit, icon)

    if frame == 4:
        level = _prop_int(item, "Level") or 1
        quality = _prop_int(item, "Quality") or 0
        corrupted = bool(item.get("corrupted"))
        unit = book.gem_price(type_line, level, quality, corrupted)
        label = f"{type_line} {level}/{quality}" + (" (corrupted)" if corrupted else "")
        return PricedItem(label, "Gem", qty, unit, icon)

    tier = _prop_int(item, "Map Tier")
    if tier is not None:
        unit = book.map_price(base, tier)
        if unit is None and type_line != base:
            unit = book.map_price(type_line, tier)
        return PricedItem(f"{base} (T{tier})", "Map", qty, unit, icon)

    for key in (base, type_line):
        hit = book.stack_price(key)
        if hit:
            return PricedItem(key, hit[1], qty, hit[0], icon)
    return PricedItem(name or type_line or base or "Unknown item",
                      "Other", qty, None, icon)
