"""poe.ninja client.

Endpoints used:
    currencyoverview?league=<L>&type=Currency
    currencyoverview?league=<L>&type=Fragment

Response shape (trimmed to what we consume):

    {
      "lines": [
        {
          "currencyTypeName": "Chaos Orb",
          "pay": { "value": 0.00595, "count": 120, ... },
          "receive": { "value": 167.5, "count": 3, ... },
          "paySparkLine":    { "data": [0, 1.2, ...], "totalChange": 4.2 },
          "receiveSparkLine":{ "data": [...],         "totalChange": -1.0 },
          "lowConfidencePaySparkLine": { ... },
          "lowConfidenceReceiveSparkLine": { ... },
          "detailsId": "chaos-orb"
        }, ...
      ],
      "currencyDetails": [{ "id": 1, "name": "Chaos Orb", "icon": "..." }, ...]
    }

We convert each line into a :class:`CurrencyLine` with normalised
fields, plus enough raw metadata for the scorer to apply its own
filters (low-confidence flags, volume, etc.).

Caching: a disk cache under ``logs/ninja_cache/`` keyed by
``<league>.<type>.json``. Freshness window defaults to 10 minutes;
long enough to be kind to poe.ninja, short enough to stay relevant
for a flip-session.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

log = logging.getLogger("poe_qol.economy.ninja")

_BASE = "https://poe.ninja/api/data/currencyoverview"
_UA = "poe_qol/0.1 (+github.com/viexhd/my-poe-project) python"


@dataclass
class CurrencyLine:
    """One row from ``currencyoverview.lines``.

    Value convention:
        * ``chaos_equivalent`` — what 1 unit is worth in chaos (the
          "receive" side, i.e. what people will give you for it).
        * ``pay_chaos`` — the chaos you pay to get 1 unit (the bid).
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
    def daily_volume(self) -> int:
        """Conservative volume estimate: min of pay / receive counts.

        poe.ninja's ``count`` is listings over the last day on that
        side. Taking the min approximates how many round-trips you
        could realistically close — a 200/3 asymmetry isn't 200 flips,
        it's 3.
        """
        return max(0, min(self.pay_count, self.receive_count))


@dataclass
class CurrencySnapshot:
    league: str
    fetched_at: float                  # epoch seconds
    lines: list[CurrencyLine]

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

    # -- fetch --
    def fetch_currency(self, league: str, *, force: bool = False,
                       kind: str = "Currency") -> CurrencySnapshot:
        """Fetch ``Currency`` (default) or ``Fragment`` overview.

        Returns the cached snapshot if one exists and is within
        ``freshness_sec``, unless ``force=True``.
        """
        cache = self._cache_path(league, kind)
        raw: dict | None = None
        if not force and self._fresh(cache):
            try:
                raw = json.loads(cache.read_text())
            except Exception:
                log.warning("corrupt ninja cache: %s (refetching)", cache)
                raw = None
        if raw is None:
            raw = self._http_get(league, kind)
            try:
                cache.write_text(json.dumps(raw))
            except Exception:
                log.exception("failed to write ninja cache %s", cache)

        lines = list(_parse_lines(raw))
        return CurrencySnapshot(league=league, fetched_at=time.time(),
                                lines=lines)

    def _http_get(self, league: str, kind: str) -> dict:
        q = urllib.parse.urlencode({"league": league, "type": kind})
        url = f"{_BASE}?{q}"
        log.info("GET %s", url)
        req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
            return json.loads(resp.read().decode("utf-8"))


# ---- parsing ------------------------------------------------------------

def _sparkline(block: dict | None, key: str) -> list[float]:
    if not isinstance(block, dict):
        return []
    sl = block.get(key)
    if not isinstance(sl, dict):
        return []
    data = sl.get("data") or []
    # poe.ninja sometimes emits nulls in the series — treat as 0 so
    # downstream stats don't choke.
    return [float(x) if isinstance(x, (int, float)) else 0.0 for x in data]


def _change(block: dict | None, key: str) -> float | None:
    if not isinstance(block, dict):
        return None
    sl = block.get(key)
    if not isinstance(sl, dict):
        return None
    v = sl.get("totalChange")
    return float(v) if isinstance(v, (int, float)) else None


def _parse_lines(raw: dict) -> Iterable[CurrencyLine]:
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
        # per chaos* — invert so pay_chaos is chaos per unit, matching
        # receive side.
        pay_value = pay.get("value")
        pay_chaos = (1.0 / pay_value) if isinstance(pay_value, (int, float)) and pay_value > 0 else None

        yield CurrencyLine(
            name=name,
            details_id=str(line.get("detailsId") or ""),
            icon=det.get("icon"),
            chaos_equivalent=(recv.get("value") if isinstance(recv.get("value"), (int, float)) else None),
            receive_count=int(recv.get("count") or 0),
            receive_change_7d=_change(line, "receiveSparkLine"),
            pay_chaos=pay_chaos,
            pay_count=int(pay.get("count") or 0),
            pay_change_7d=_change(line, "paySparkLine"),
            low_confidence_receive=bool(
                line.get("lowConfidenceReceiveSparkLine")
                and line.get("receiveSparkLine") is None),
            low_confidence_pay=bool(
                line.get("lowConfidencePaySparkLine")
                and line.get("paySparkLine") is None),
            sparkline_receive=_sparkline(line, "receiveSparkLine")
                              or _sparkline(line, "lowConfidenceReceiveSparkLine"),
            sparkline_pay=_sparkline(line, "paySparkLine")
                          or _sparkline(line, "lowConfidencePaySparkLine"),
        )
