"""Visual map-search query builder.

This module is the successor to the regex-driven ``builder.py`` path.
It takes:

    * a loaded :class:`MapDataset` (config/map_mods.yaml, v2 schema)
    * an item-type id  (e.g. ``"map_t16"``)
    * a set of excluded mod ids  (selection from the UI)

and emits a PoE trade POST payload that excludes any listing which has
*any* of the selected mods. The exclusion is encoded as a single
``count``-type stat group with ``value.max = 0`` — the canonical way to
say "none of these mods may appear" on pathofexile.com/trade.

Why ``count(max=0)`` rather than ``type: not``?  Both work on the trade
site, but ``count`` is what the pathofexile.com UI actually produces
when you click the little minus button on a stat, so we emit the same
shape for maximum forward-compatibility.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

log = logging.getLogger("poe_qol.trade.map_query")


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

@dataclass
class ItemType:
    id: str
    name: str
    category: str | None = None
    # {"min": 16, "max": 16} – optional
    map_tier: dict[str, int] | None = None


@dataclass
class Category:
    id: str
    name: str
    color: str = "#888888"


@dataclass
class Mod:
    id: str
    name: str
    category: str
    stat_id: str
    tags: list[str] = field(default_factory=list)

    def matches(self, needle: str) -> bool:
        """Search-bar match: substring against id, name, tags."""
        needle = needle.strip().lower()
        if not needle:
            return True
        if needle in self.id.lower():
            return True
        if needle in self.name.lower():
            return True
        return any(needle in t.lower() for t in self.tags)


@dataclass
class Preset:
    id: str
    name: str
    excluded: list[str]
    description: str = ""


@dataclass
class MapDataset:
    """Loaded, validated view of ``config/map_mods.yaml`` (v2)."""
    item_types: list[ItemType]
    categories: list[Category]
    mods: list[Mod]
    presets: list[Preset]

    # ---- lookups ----
    def mod(self, mod_id: str) -> Mod | None:
        return next((m for m in self.mods if m.id == mod_id), None)

    def item_type(self, item_type_id: str) -> ItemType | None:
        return next((t for t in self.item_types if t.id == item_type_id), None)

    def preset(self, preset_id: str) -> Preset | None:
        return next((p for p in self.presets if p.id == preset_id), None)

    def category(self, cat_id: str) -> Category | None:
        return next((c for c in self.categories if c.id == cat_id), None)

    def mods_in_category(self, cat_id: str) -> list[Mod]:
        return [m for m in self.mods if m.category == cat_id]

    # ---- loader ----
    @classmethod
    def load(cls, path: str | Path) -> "MapDataset":
        data = yaml.safe_load(Path(path).read_text()) or {}
        if data.get("version") != 2:
            # The old v1 file has `map_mods:` + `aliases:` only; warn so
            # the user knows the new UI won't see their mods.
            log.warning(
                "map_mods.yaml is version %r but the visual Map Search "
                "tab expects version 2. The tab will be empty until you "
                "upgrade the file.", data.get("version"))
        item_types = [ItemType(**t) for t in (data.get("item_types") or [])]
        categories = [Category(**c) for c in (data.get("categories") or [])]
        mods_raw = data.get("mods") or []
        mods = []
        for m in mods_raw:
            mods.append(Mod(
                id=m["id"], name=m["name"], category=m["category"],
                stat_id=m["stat_id"], tags=list(m.get("tags") or []),
            ))
        presets_raw = data.get("presets") or []
        presets = [Preset(
            id=p["id"], name=p["name"],
            excluded=list(p.get("excluded") or []),
            description=p.get("description", ""),
        ) for p in presets_raw]
        return cls(item_types=item_types, categories=categories,
                   mods=mods, presets=presets)


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------

def _exclusion_group(mods: Iterable[Mod]) -> dict[str, Any] | None:
    """Return a count(max=0) stat group over the given mods, or None
    if ``mods`` is empty."""
    filters = [{"id": m.stat_id, "value": {"min": 1},
                "disabled": False} for m in mods]
    if not filters:
        return None
    return {
        "type": "count",
        "filters": filters,
        "value": {"max": 0},
        "disabled": False,
    }


def build_map_query(dataset: MapDataset, *,
                    item_type_id: str,
                    excluded_mod_ids: Iterable[str],
                    league: str = "Standard",
                    status: str = "online") -> dict[str, Any]:
    """Assemble a trade POST payload.

    Layout matches what pathofexile.com/trade emits for
    'Map (Tier N) with none of these mods':

        query.status                              – online / any
        query.filters.type_filters.filters.category.option = "map"
        query.filters.map_filters.filters.map_tier.{min,max}
        query.stats = [ count(max=0) over all excluded mod stat ids ]
        sort.price = asc
    """
    item = dataset.item_type(item_type_id)
    filters: dict[str, Any] = {}
    if item and item.category:
        filters.setdefault("type_filters", {"filters": {}})
        filters["type_filters"]["filters"]["category"] = {
            "option": item.category}
    if item and item.map_tier:
        filters.setdefault("map_filters", {"filters": {}})
        filters["map_filters"]["filters"]["map_tier"] = dict(item.map_tier)

    # Resolve excluded mod ids -> Mod objects, dropping unknowns.
    unknown: list[str] = []
    excl_mods: list[Mod] = []
    for mid in excluded_mod_ids:
        m = dataset.mod(mid)
        if m is None:
            unknown.append(mid)
        else:
            excl_mods.append(m)
    if unknown:
        log.warning("unknown mod ids skipped: %s", ", ".join(unknown))

    stats: list[dict[str, Any]] = []
    grp = _exclusion_group(excl_mods)
    if grp:
        stats.append(grp)

    q: dict[str, Any] = {
        "query": {
            "status": {"option": status},
            "stats": stats,
        },
        "sort": {"price": "asc"},
    }
    if filters:
        q["query"]["filters"] = filters
    # Convenience marker used by build_url(); stripped before POST.
    q["__league__"] = league
    return q
