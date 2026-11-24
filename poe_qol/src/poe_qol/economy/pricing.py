"""Prices for stash valuation, from poe.ninja.

Wealthy Exile values a stash with market prices per item; this does the
same with poe.ninja's documented economy endpoints:

* stackables (currency, fragments, scarabs, essences, divination cards,
  fossils, oils, ...) from the *exchange* overview, one call per type;
* uniques, maps and gems from the *item* overview.

Everything is cached on disk by :class:`~poe_qol.economy.ninja.NinjaClient`
(30 min by default), so an hourly sync costs at most one round of calls.
A type poe.ninja doesn't know for the league is skipped, not fatal.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .ninja import NinjaClient

log = logging.getLogger("poe_qol.economy.pricing")

EXCHANGE_TYPES = (
    "Currency", "Fragment", "Scarab", "Essence", "DivinationCard", "Fossil",
    "Resonator", "Oil", "Incubator", "DeliriumOrb", "Omen", "Tattoo",
    "Artifact", "AllflameEmber", "Runegraft", "KalguuranRune", "Astrolabe",
    "Memory", "Vial",
)
ITEM_TYPES = (
    "UniqueWeapon", "UniqueArmour", "UniqueAccessory", "UniqueFlask",
    "UniqueJewel", "UniqueMap", "UniqueRelic", "Map", "BlightedMap",
    "BlightRavagedMap", "Invitation", "SkillGem",
)
_CATEGORY_OF_TYPE = {
    "DivinationCard": "Divination Card", "DeliriumOrb": "Delirium Orb",
    "AllflameEmber": "Allflame Ember", "KalguuranRune": "Rune",
    "UniqueWeapon": "Unique", "UniqueArmour": "Unique",
    "UniqueAccessory": "Unique", "UniqueFlask": "Unique",
    "UniqueJewel": "Unique", "UniqueMap": "Unique", "UniqueRelic": "Unique",
    "BlightedMap": "Map", "BlightRavagedMap": "Map", "SkillGem": "Gem",
}


def category_of(kind: str) -> str:
    return _CATEGORY_OF_TYPE.get(kind, kind)


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


@dataclass
class UniqueEntry:
    base: str
    links: int
    variant: str
    chaos: float


@dataclass
class PriceBook:
    league: str = ""
    fetched_at: float = field(default_factory=time.time)
    stale: bool = False
    stack: dict[str, tuple[float, str]] = field(default_factory=dict)
    uniques: dict[str, list[UniqueEntry]] = field(default_factory=dict)
    maps: dict[tuple[str, int], float] = field(default_factory=dict)
    gems: dict[tuple[str, int, int, bool], float] = field(default_factory=dict)
    missing_types: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.stack.setdefault("chaos orb", (1.0, "Currency"))

    @property
    def chaos_per_divine(self) -> float | None:
        v = self.stack.get("divine orb")
        return v[0] if v else None

    def size(self) -> int:
        return (len(self.stack) + sum(len(v) for v in self.uniques.values())
                + len(self.maps) + len(self.gems))

    # ---- filling ----
    def add_stack(self, name: str, chaos: float | None, category: str) -> None:
        if name and chaos and chaos > 0:
            self.stack.setdefault(norm(name), (float(chaos), category))

    def add_item_lines(self, kind: str, lines: Iterable[dict]) -> None:
        for ln in lines:
            chaos = _num(ln.get("chaosValue"))
            if chaos is None:
                chaos = _num(ln.get("primaryValue"))
            name = ln.get("name")
            if not name or not chaos or chaos <= 0:
                continue
            if kind.startswith("Unique"):
                self.uniques.setdefault(norm(name), []).append(UniqueEntry(
                    base=norm(ln.get("baseType")),
                    links=int(ln.get("links") or 0),
                    variant=str(ln.get("variant") or ""),
                    chaos=chaos))
            elif kind in ("Map", "BlightedMap", "BlightRavagedMap"):
                tier = int(ln.get("mapTier") or 0)
                self.maps.setdefault((norm(name), tier), chaos)
            elif kind == "SkillGem":
                key = (norm(name), int(ln.get("gemLevel") or 1),
                       int(ln.get("gemQuality") or 0), bool(ln.get("corrupted")))
                self.gems.setdefault(key, chaos)
            else:
                self.add_stack(name, chaos, category_of(kind))

    # ---- lookups ----
    def stack_price(self, name: str) -> tuple[float, str] | None:
        return self.stack.get(norm(name))

    def unique_price(self, name: str, base: str, links: int) -> float | None:
        entries = self.uniques.get(norm(name))
        if not entries:
            return None
        same_base = [e for e in entries if e.base == norm(base)] or entries
        want = links if links >= 5 else 0
        exact = [e for e in same_base if e.links == want]
        pool = exact or [e for e in same_base if e.links == 0] or same_base
        # several variants (e.g. different implicits): be conservative
        return min(e.chaos for e in pool)

    def map_price(self, name: str, tier: int) -> float | None:
        return self.maps.get((norm(name), tier))

    def gem_price(self, name: str, level: int, quality: int,
                  corrupted: bool) -> float | None:
        return self.gems.get((norm(name), level, quality, corrupted))


ProgressFn = Callable[[str], None]


def build_price_book(client: NinjaClient, league: str, *,
                     progress: ProgressFn | None = None,
                     cancelled: Callable[[], bool] | None = None,
                     exchange_types: Iterable[str] = EXCHANGE_TYPES,
                     item_types: Iterable[str] = ITEM_TYPES) -> PriceBook:
    book = PriceBook(league=league)
    oldest = time.time()
    for kind in exchange_types:
        if cancelled and cancelled():
            break
        if progress:
            progress(f"Prices: {category_of(kind)}")
        try:
            snap = client.fetch_currency(league, kind=kind)
        except Exception as e:  # noqa: BLE001
            log.info("no %s prices: %s", kind, e)
            book.missing_types.append(kind)
            continue
        oldest = min(oldest, snap.fetched_at)
        book.stale |= snap.stale
        for line in snap.lines:
            book.add_stack(line.name, line.chaos_equivalent, category_of(kind))
    for kind in item_types:
        if cancelled and cancelled():
            break
        if progress:
            progress(f"Prices: {kind}")
        try:
            lines, at, stale = client.fetch_item_lines(league, kind)
        except Exception as e:  # noqa: BLE001
            log.info("no %s prices: %s", kind, e)
            book.missing_types.append(kind)
            continue
        oldest = min(oldest, at)
        book.stale |= stale
        book.add_item_lines(kind, lines)
    book.fetched_at = oldest
    return book
