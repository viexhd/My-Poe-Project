"""poe.ninja client.

poe.ninja retired the old ``/api/data/currencyoverview`` endpoint in
late 2026 (it now answers 404). That is why the Flipper tab stopped
working. The replacement is the economy *exchange* overview:

    https://poe.ninja/poe1/api/economy/exchange/current/overview
        ?league=<L>&type=Currency

Exchange response shape (trimmed to what we consume)::

    {
      "core":  { "primary": "chaos", "secondary": "divine",
                 "rates": { "divine": 0.0061, ... },
                 "items": [ ...same shape as "items"... ] },
      "lines": [
        { "id": "divine",
          "primaryValue": 163.2,          # chaos per unit
          "volumePrimaryValue": 512345.0, # traded volume, in chaos
          "maxVolumeCurrency": "chaos",   # pair it trades most against
          "maxVolumeRate": 163.0,
          "sparkline": { "data": [...], "totalChange": -1.2 } }, ...
      ],
      "items": [
        { "id": "divine", "name": "Divine Orb", "image": "/gen/...",
          "detailsId": "divine-orb" }, ...
      ]
    }

The exchange endpoint gives one market price plus volume per currency,
not separate bid/ask books. The scorer copes with both shapes: see
``economy/flipper.py``.

The legacy shape (``currencyTypeName`` / ``pay`` / ``receive``) is still
parsed, so old disk caches and the legacy endpoint (tried as a fallback)
keep working.

Caching: a disk cache under ``logs/ninja_cache/`` keyed by
``<league>.<type>.json``. Fresh for ``freshness_sec`` (default 10 min).
When the network fails, a stale cache is used instead of failing, and
the snapshot is marked ``stale``.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .. import __version__

log = logging.getLogger("poe_qol.economy.ninja")

EXCHANGE_URL = "https://poe.ninja/poe1/api/economy/exchange/current/overview"
STASH_URL = "https://poe.ninja/poe1/api/economy/stash/current/item/overview"
LEGACY_URL = "https://poe.ninja/api/data/currencyoverview"

# poe.ninja categories. Bulk-traded ones come from the exchange
# overview; the rest (gems, maps, uniques…) from the stash item
# overview. Unique weapons and armour are left out on purpose: too many
# variants to flip.
EXCHANGE_CATEGORIES = (
    "Currency", "Fragment", "Scarab", "Essence", "Fossil", "Resonator",
    "Oil", "DeliriumOrb", "DivinationCard", "Omen", "Tattoo", "Artifact",
    "AllflameEmber", "Astrolabe",
)
ITEM_CATEGORIES = (
    "SkillGem", "Map", "UniqueMap", "BlightedMap", "BlightRavagedMap",
    "Invitation", "Memory", "Incubator", "Beast", "Vial", "UniqueJewel",
    "UniqueFlask", "UniqueAccessory", "UniqueRelic",
)
EXCLUDED_CATEGORIES = ("UniqueWeapon", "UniqueArmour")
ALL_CATEGORIES = EXCHANGE_CATEGORIES + ITEM_CATEGORIES
CATEGORY_LABELS = {
    "Currency": "Currency", "Fragment": "Fragments", "Scarab": "Scarabs",
    "Essence": "Essences", "Fossil": "Fossils", "Resonator": "Resonators",
    "Oil": "Oils", "DeliriumOrb": "Delirium Orbs",
    "DivinationCard": "Divination Cards", "Omen": "Omens",
    "Tattoo": "Tattoos", "Artifact": "Artifacts",
    "AllflameEmber": "Allflame Embers", "Astrolabe": "Astrolabes",
    "SkillGem": "Skill Gems", "Map": "Maps", "UniqueMap": "Unique Maps",
    "BlightedMap": "Blighted Maps", "BlightRavagedMap": "Blight-Ravaged Maps",
    "Invitation": "Invitations", "Memory": "Memories",
    "Incubator": "Incubators", "Beast": "Beasts", "Vial": "Vials",
    "UniqueJewel": "Unique Jewels", "UniqueFlask": "Unique Flasks",
    "UniqueAccessory": "Unique Accessories", "UniqueRelic": "Unique Relics",
}


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def _endpoints(category: str) -> tuple[str, ...]:
    if category in ITEM_CATEGORIES:
        return (STASH_URL,)
    if category in ("Currency", "Fragment"):      # also had a legacy form
        return (EXCHANGE_URL, LEGACY_URL)
    return (EXCHANGE_URL,)
_MAX_CROSS_GAP = 0.25   # bigger cross-pair gaps are treated as noise
# poe.ninja asks API clients for an identifying User-Agent.
_UA = (f"TwiceCorrupted/{__version__} "
       "(+https://github.com/viexhd/Twice-Corrupted)")


@dataclass
class CurrencyLine:
    """One currency, normalised from either response shape.

    Value convention:
        * ``chaos_equivalent``: what 1 unit is worth in chaos.
        * ``pay_chaos``: the chaos you pay to get 1 unit (the bid). Only
          the legacy endpoint has it; ``None`` for exchange data.
        * Spread is ``chaos_equivalent - pay_chaos``; a *positive*
          spread means buying at pay and selling at receive is profit.
    """
    name: str
    details_id: str
    icon: str | None

    # Receive = you receive N chaos for 1 of this currency (the ask).
    chaos_equivalent: float | None
    receive_count: int                # listings / day on receive side
    receive_change_7d: float | None   # totalChange, percent

    # Pay = you pay N chaos for 1 of this currency (the bid).
    pay_chaos: float | None
    pay_count: int
    pay_change_7d: float | None

    low_confidence_receive: bool
    low_confidence_pay: bool

    # 7-day series (relative values, already normalised by poe.ninja).
    sparkline_receive: list[float] = field(default_factory=list)
    sparkline_pay: list[float] = field(default_factory=list)

    # ---- exchange-endpoint extras ----
    # Trade-site exchange id ("divine", "alch", ...). Used to build the
    # bulk-exchange link. Empty for legacy data.
    trade_id: str = ""
    # Traded volume over the last day, in chaos. None for legacy data.
    volume_chaos: float | None = None
    # Price implied by the pair this currency trades most against
    # (e.g. its divine price converted to chaos). None when that pair
    # *is* chaos or the rate is unknown.
    cross_chaos: float | None = None

    # ---- category / item-overview extras ----
    category: str = "Currency"           # poe.ninja category id
    # Listings on the trade site (item overview only; replaces volume).
    listings: int | None = None
    # What to search for on the trade site (item overview only).
    search_name: str = ""
    search_type: str = ""
    gem_level: int | None = None
    gem_quality: int | None = None
    links: int | None = None
    map_tier: int | None = None
    corrupted: bool | None = None

    @property
    def is_bulk(self) -> bool:
        """Traded on the bulk exchange (vs. individual listings)."""
        return self.listings is None

    @property
    def has_book(self) -> bool:
        """True when separate bid/ask prices are known (legacy data)."""
        return self.pay_chaos is not None and self.chaos_equivalent is not None

    @property
    def spread_chaos(self) -> float | None:
        if self.chaos_equivalent is None or self.pay_chaos is None:
            return None
        return self.chaos_equivalent - self.pay_chaos

    @property
    def spread_pct(self) -> float | None:
        if (self.pay_chaos in (None, 0)
                or self.chaos_equivalent is None
                or self.pay_chaos is None):
            return None
        return (self.chaos_equivalent - self.pay_chaos) / self.pay_chaos * 100.0

    @property
    def cross_gap_pct(self) -> float | None:
        """Gap between the chaos price and the price implied by the
        currency's busiest other pair, in percent. A big gap is a
        two-market flip: buy on the cheap side, sell on the other."""
        if not self.cross_chaos or not self.chaos_equivalent:
            return None
        return ((self.cross_chaos - self.chaos_equivalent)
                / self.chaos_equivalent * 100.0)

    @property
    def edge_pct(self) -> float | None:
        """The margin signal the UI shows: bid/ask spread when known,
        else the cross-pair gap."""
        return self.spread_pct if self.has_book else self.cross_gap_pct

    @property
    def daily_volume(self) -> int:
        """Units that change hands per day.

        Legacy: min of the pay / receive counts, so a 200/3 lopsided
        book counts as 3 round-trips, not 200. Exchange: chaos volume
        divided by the unit price.
        """
        if self.listings is not None:
            return max(0, self.listings)
        if self.volume_chaos is not None:
            if not self.chaos_equivalent:
                return 0
            return max(0, int(self.volume_chaos / self.chaos_equivalent))
        return max(0, min(self.pay_count, self.receive_count))


@dataclass
class CurrencySnapshot:
    league: str
    fetched_at: float                  # epoch seconds (data age)
    lines: list[CurrencyLine]
    stale: bool = False                # served from an expired cache
    source: str = "exchange"           # "exchange" | "legacy" | "stash" | "mixed"
    # Categories that couldn't be loaded (unknown to poe.ninja, offline…)
    missing: list[str] = field(default_factory=list)

    def by_name(self, name: str) -> CurrencyLine | None:
        low = name.lower()
        for l in self.lines:
            if l.name.lower() == low:
                return l
        return None


class NinjaClient:
    """Thin, cached client. One instance per app; safe to reuse."""

    def __init__(self, cache_dir: Path,
                 freshness_sec: int = 600,
                 timeout_sec: float = 15.0) -> None:
        self.cache_dir = cache_dir
        self.freshness_sec = freshness_sec
        self.timeout_sec = timeout_sec
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- cache paths --
    def _cache_path(self, league: str, kind: str) -> Path:
        safe = urllib.parse.quote_plus(league.lower())
        return self.cache_dir / f"{safe}.{kind.lower()}.json"

    def _fresh(self, p: Path) -> bool:
        if not p.exists():
            return False
        age = time.time() - p.stat().st_mtime
        return age < self.freshness_sec

    @staticmethod
    def _read_cache(p: Path) -> dict | None:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            log.warning("unreadable ninja cache: %s", p)
            return None
        return raw if isinstance(raw, dict) else None

    # -- fetch --
    def fetch_all(self, league: str, *, categories=ALL_CATEGORIES,
                  force: bool = False, workers: int = 4,
                  progress=None) -> CurrencySnapshot:
        """Fetch every category and merge them into one snapshot.

        Categories that fail (unknown to poe.ninja, network) are listed
        in ``missing``; only when all of them fail is the error raised.
        ``progress(done, total)`` is called as each one finishes.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        snaps: list[CurrencySnapshot] = []
        missing: list[str] = []
        errors: list[Exception] = []
        cats = [c for c in categories if c not in EXCLUDED_CATEGORIES]
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futs = {pool.submit(self.fetch_currency, league, force=force,
                                kind=c): c for c in cats}
            for n, fut in enumerate(as_completed(futs), 1):
                try:
                    snaps.append(fut.result())
                except Exception as e:  # noqa: BLE001
                    missing.append(futs[fut])
                    errors.append(e)
                if progress is not None:
                    progress(n, len(cats))
        if not snaps:
            raise errors[0] if errors else NinjaError("nothing to fetch")
        lines = [l for sn in snaps for l in sn.lines]
        sources = {sn.source for sn in snaps}
        return CurrencySnapshot(
            league=league,
            fetched_at=min(sn.fetched_at for sn in snaps),
            lines=lines,
            stale=any(sn.stale for sn in snaps),
            source=sources.pop() if len(sources) == 1 else "mixed",
            missing=sorted(missing, key=cats.index))

    def fetch_currency(self, league: str, *, force: bool = False,
                       kind: str = "Currency") -> CurrencySnapshot:
        """Fetch one category's overview (``Currency`` by default).

        Returns the cached snapshot if it is within ``freshness_sec``,
        unless ``force=True``. If every endpoint fails, falls back to an
        expired cache (``stale=True``) before raising.
        """
        cache = self._cache_path(league, kind)
        raw: dict | None = None
        stale = False
        fetched_at = time.time()
        if not force and self._fresh(cache):
            raw = self._read_cache(cache)
            if raw is not None:
                fetched_at = cache.stat().st_mtime
        if raw is None:
            try:
                raw = self._http_get(league, kind)
            except Exception as e:
                old = self._read_cache(cache) if cache.exists() else None
                if old is None:
                    raise NinjaError(_friendly_error(e, league)) from e
                log.warning("ninja fetch failed (%s); using stale cache", e)
                raw, stale = old, True
                fetched_at = cache.stat().st_mtime
            else:
                try:
                    cache.write_text(json.dumps(raw), encoding="utf-8")
                except Exception:
                    log.exception("failed to write ninja cache %s", cache)

        lines = list(_parse_lines(raw, kind))
        return CurrencySnapshot(league=league, fetched_at=fetched_at,
                                lines=lines, stale=stale,
                                source=response_kind(raw))

    def _http_get(self, league: str, kind: str) -> dict:
        q = urllib.parse.urlencode({"league": league, "type": kind})
        last: Exception | None = None
        for base in _endpoints(kind):
            url = f"{base}?{q}"
            log.info("GET %s", url)
            req = urllib.request.Request(
                url, headers={"User-Agent": _UA, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                # 404 = endpoint retired or unknown league; try the next.
                last = e
                continue
            if isinstance(raw, dict) and raw.get("lines"):
                return raw
            last = NinjaError(f"no prices for league '{league}'")
        assert last is not None
        raise last


class NinjaError(RuntimeError):
    """A fetch failure worded for the status line."""


def _friendly_error(e: Exception, league: str) -> str:
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return f"PoE Ninja Has No Prices For League '{league}'"
        return f"PoE Ninja Answered HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return "Can't Reach PoE Ninja (Offline Or Blocked)"
    if isinstance(e, NinjaError):
        return str(e)
    return f"PoE Ninja Fetch Failed ({e})"


# ---- parsing ------------------------------------------------------------

def response_kind(raw: dict) -> str:
    """``"exchange"``, ``"stash"`` or ``"legacy"``, from the first line."""
    for line in raw.get("lines") or []:
        if isinstance(line, dict):
            if "currencyTypeName" in line:
                return "legacy"
            if "chaosValue" in line:
                return "stash"
            return "exchange"
    return "exchange"


def _parse_lines(raw: dict, category: str = "Currency") -> list[CurrencyLine]:
    if not isinstance(raw, dict):
        return []
    kind = response_kind(raw)
    parser = {"legacy": _parse_legacy, "stash": _parse_stash}.get(
        kind, _parse_exchange)
    lines = list(parser(raw))
    for l in lines:
        l.category = category
    return lines


# -- stash item overview (gems, maps, uniques, beasts…) --

def _int(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _parse_stash(raw: dict) -> Iterable[CurrencyLine]:
    for line in raw.get("lines") or []:
        if not isinstance(line, dict):
            continue
        name = str(line.get("name") or "").strip()
        value = _num(line.get("chaosValue"))
        if not name or not value or value <= 0:
            continue
        base = str(line.get("baseType") or "").strip()
        gem_level = _int(line.get("gemLevel"))
        gem_quality = _int(line.get("gemQuality"))
        links = _int(line.get("links"))
        tier = _int(line.get("mapTier"))
        corrupted = line.get("corrupted") if isinstance(
            line.get("corrupted"), bool) else None
        variant = str(line.get("variant") or "").strip()

        tags: list[str] = []
        if gem_level:
            tags.append(f"Level {gem_level}")
        if gem_quality:
            tags.append(f"{gem_quality}% Quality")
        if links and links >= 5:
            tags.append(f"{links} Link")
        if tier:
            tags.append(f"Tier {tier}")
        if variant and variant.lower() not in " ".join(tags).lower():
            tags.append(variant)
        if corrupted:
            tags.append("Corrupted")
        label = name + (f" ({', '.join(tags)})" if tags else "")

        data, change = _series(line.get("sparkline"))
        if not data:
            data, change2 = _series(line.get("lowConfidenceSparkline"))
            change = change if change is not None else change2
        listings = _int(line.get("listingCount"))
        if listings is None:
            listings = _int(line.get("count")) or 0
        icon = line.get("icon")
        unique = bool(base) and base != name
        yield CurrencyLine(
            name=label,
            details_id=str(line.get("detailsId") or ""),
            icon=icon if isinstance(icon, str) else None,
            chaos_equivalent=value,
            receive_count=0,
            receive_change_7d=change,
            pay_chaos=None,
            pay_count=0,
            pay_change_7d=None,
            # No history, or only a handful of listings: poe.ninja's
            # price is a guess.
            low_confidence_receive=(not data) or listings < 5,
            low_confidence_pay=False,
            sparkline_receive=data,
            listings=listings,
            search_name=name if unique else "",
            search_type=base if unique else name,
            gem_level=gem_level,
            gem_quality=gem_quality,
            links=links,
            map_tier=tier,
            corrupted=corrupted,
        )


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _series(sl) -> tuple[list[float], float | None]:
    """(data, totalChange) from a sparkline block; nulls become 0."""
    if not isinstance(sl, dict):
        return [], None
    raw = sl.get("data") or []
    data = [float(x) if isinstance(x, (int, float)) else 0.0 for x in raw]
    has_points = any(isinstance(x, (int, float)) for x in raw)
    return (data if has_points else []), _num(sl.get("totalChange"))


# -- exchange (current) --

def _parse_exchange(raw: dict) -> Iterable[CurrencyLine]:
    core = raw.get("core") if isinstance(raw.get("core"), dict) else {}
    items: dict[str, dict] = {}
    for src in (core.get("items"), raw.get("items")):
        for it in src or []:
            if isinstance(it, dict) and it.get("id") is not None:
                items[str(it["id"])] = it
    primary = str(core.get("primary") or "chaos")
    rates = core.get("rates") if isinstance(core.get("rates"), dict) else {}

    # Chaos value of 1 unit of the primary currency. Normally primary is
    # chaos (1.0); if poe.ninja ever switches it, rates[x] = x per primary.
    to_chaos = 1.0 if primary == "chaos" else _num(rates.get("chaos"))
    if not to_chaos:
        return

    # Chaos price of every line, for converting cross-pair rates.
    chaos_of: dict[str, float] = {"chaos": 1.0}
    for line in raw.get("lines") or []:
        if isinstance(line, dict):
            v = _num(line.get("primaryValue"))
            if v and line.get("id") is not None:
                chaos_of[str(line["id"])] = v * to_chaos

    for line in raw.get("lines") or []:
        if not isinstance(line, dict) or line.get("id") is None:
            continue
        lid = str(line["id"])
        value = chaos_of.get(lid)
        if not value:
            continue
        it = items.get(lid, {})
        name = str(it.get("name") or lid)
        vol = _num(line.get("volumePrimaryValue"))
        data, change = _series(line.get("sparkline"))
        if not data:
            data, change2 = _series(line.get("lowConfidenceSparkline"))
            change = change if change is not None else change2
        image = it.get("image") or it.get("icon")
        if isinstance(image, str) and image.startswith("/"):
            image = "https://web.poecdn.com" + image

        yield CurrencyLine(
            name=name,
            details_id=str(it.get("detailsId") or ""),
            icon=image if isinstance(image, str) else None,
            chaos_equivalent=value,
            receive_count=0,
            receive_change_7d=change,
            pay_chaos=None,
            pay_count=0,
            pay_change_7d=None,
            # No history at all = poe.ninja has too few trades to chart.
            low_confidence_receive=not data,
            low_confidence_pay=False,
            sparkline_receive=data,
            trade_id=lid,
            volume_chaos=(vol * to_chaos) if vol is not None else None,
            cross_chaos=_cross_chaos(line, value, chaos_of),
        )


def _cross_chaos(line: dict, value: float,
                 chaos_of: dict[str, float]) -> float | None:
    """Chaos price implied by the line's busiest pair.

    ``maxVolumeRate`` is quoted in one direction or the other depending
    on the pair, so both readings are converted and the one closer to
    the chaos price wins. Readings more than 25% off are discarded as
    stale or thin data rather than shown as a huge "flip".
    """
    cur = line.get("maxVolumeCurrency")
    rate = _num(line.get("maxVolumeRate"))
    if not cur or cur == "chaos" or not rate or rate <= 0:
        return None
    other = chaos_of.get(str(cur))
    if not other:
        return None
    best = min((rate * other, other / rate), key=lambda c: abs(c - value))
    if abs(best - value) > value * _MAX_CROSS_GAP:
        return None
    return best


# -- legacy (/api/data/currencyoverview) --

def _sparkline(block: dict | None, key: str) -> list[float]:
    if not isinstance(block, dict):
        return []
    return _series(block.get(key))[0]


def _change(block: dict | None, key: str) -> float | None:
    if not isinstance(block, dict):
        return None
    return _series(block.get(key))[1]


def _parse_legacy(raw: dict) -> Iterable[CurrencyLine]:
    details = {d.get("name"): d for d in (raw.get("currencyDetails") or [])
               if isinstance(d, dict)}
    for line in raw.get("lines") or []:
        if not isinstance(line, dict):
            continue
        name = line.get("currencyTypeName") or ""
        if not name:
            continue
        pay = line.get("pay") or {}
        recv = line.get("receive") or {}
        det = details.get(name) or {}
        # poe.ninja's "value" on pay side is expressed as *this currency
        # per chaos*; invert so pay_chaos is chaos per unit, matching
        # receive side.
        pay_value = _num(pay.get("value"))
        pay_chaos = (1.0 / pay_value) if pay_value and pay_value > 0 else None

        recv_main = _sparkline(line, "receiveSparkLine")
        pay_main = _sparkline(line, "paySparkLine")
        yield CurrencyLine(
            name=name,
            details_id=str(line.get("detailsId") or ""),
            icon=det.get("icon"),
            chaos_equivalent=_num(recv.get("value")),
            receive_count=int(recv.get("count") or 0),
            receive_change_7d=(_change(line, "receiveSparkLine")
                               if recv_main else
                               _change(line, "lowConfidenceReceiveSparkLine")),
            pay_chaos=pay_chaos,
            pay_count=int(pay.get("count") or 0),
            pay_change_7d=(_change(line, "paySparkLine") if pay_main else
                           _change(line, "lowConfidencePaySparkLine")),
            # poe.ninja always sends both series; the main one is empty
            # (no points) when the data is low-confidence. The old check
            # ("main series key missing") never fired, so the
            # low-confidence filter silently did nothing.
            low_confidence_receive=(not recv_main and bool(
                _sparkline(line, "lowConfidenceReceiveSparkLine"))),
            low_confidence_pay=(not pay_main and bool(
                _sparkline(line, "lowConfidencePaySparkLine"))),
            sparkline_receive=recv_main
                              or _sparkline(line, "lowConfidenceReceiveSparkLine"),
            sparkline_pay=pay_main
                          or _sparkline(line, "lowConfidencePaySparkLine"),
        )
