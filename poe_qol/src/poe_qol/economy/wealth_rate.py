"""Divine-per-hour from wealth snapshots, behind a swappable data source.

``WealthRateSource`` is the seam the overlay reads from. Today the only
source is :class:`CsvFolderSource`: it compares the two newest Wealthy
Exile CSV exports in a folder the user picked. A live Wealthy Exile
source would plug in here, but only if Wealthy Exile permits it (see
docs/WEALTHY_EXILE_INTEGRATION.md). It is deliberately not implemented.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .wealthy_exile_csv import CsvFormatError, Snapshot, parse_snapshot

log = logging.getLogger("poe_qol.economy.wealth_rate")

MIN_INTERVAL_MINUTES = 5
UNITS = ("chaos", "divine")


def clamp_interval_minutes(minutes: int | float) -> int:
    """Refresh intervals never go below :data:`MIN_INTERVAL_MINUTES`."""
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        m = MIN_INTERVAL_MINUTES
    return max(MIN_INTERVAL_MINUTES, m)


@dataclass(frozen=True)
class RateReading:
    divine_per_hour: float | None = None
    chaos_per_hour: float | None = None
    span_minutes: float | None = None
    snapshots_used: int = 0
    latest_at: datetime | None = None
    message: str = ""            # why there is no rate, or a caveat
    source: str = ""


class WealthRateSource(Protocol):
    name: str

    def read(self) -> RateReading: ...


def compute_rate(earlier: Snapshot, later: Snapshot, *,
                 chaos_per_divine: float | None,
                 assumed_unit: str = "chaos") -> RateReading:
    """Wealth change per hour between two snapshots."""
    def unit(s: Snapshot) -> str:
        return s.unit if s.unit in UNITS else assumed_unit

    u1, u2 = unit(earlier), unit(later)
    if u1 != u2:
        return RateReading(message=f"Exports use different units ({u1} vs {u2}).",
                           snapshots_used=2, latest_at=later.taken_at)
    minutes = (later.taken_at - earlier.taken_at).total_seconds() / 60.0
    if minutes <= 0:
        return RateReading(message="The two newest exports have the same time.",
                           snapshots_used=2, latest_at=later.taken_at)
    per_hour = (later.total - earlier.total) * 60.0 / minutes

    # An explicit rate wins; otherwise use the newest export's Divine Orb
    # price (chaos per divine at the time of that export).
    rate = chaos_per_divine if chaos_per_divine and chaos_per_divine > 0 else None
    auto = False
    if rate is None and later.divine_price and later.divine_price > 0:
        rate, auto = later.divine_price, True
    if u1 == "divine":
        div = per_hour
        chaos = per_hour * rate if rate else None
    else:
        chaos = per_hour
        div = per_hour / rate if rate else None
    if div is None:
        msg = "Set chaos per divine to see div/h."
    elif auto:
        msg = f"rate {rate:,.0f}c (auto from export)"
    else:
        msg = ""
    return RateReading(divine_per_hour=div, chaos_per_hour=chaos,
                       span_minutes=minutes, snapshots_used=2,
                       latest_at=later.taken_at, message=msg)


class CsvFolderSource:
    """Rate between the two newest ``*.csv`` exports in ``folder``."""
    name = "Wealthy Exile CSV exports"

    def __init__(self, folder: str | Path, *, chaos_per_divine: float | None,
                 assumed_unit: str = "chaos") -> None:
        self.folder = Path(folder) if folder else None
        self.chaos_per_divine = chaos_per_divine
        self.assumed_unit = assumed_unit if assumed_unit in UNITS else "chaos"

    def snapshots(self) -> list[Snapshot]:
        """Every readable export, oldest first."""
        if not self.folder or not self.folder.is_dir():
            return []
        snaps: list[Snapshot] = []
        for p in self.folder.glob("*.csv"):
            try:
                snaps.append(parse_snapshot(p))
            except (CsvFormatError, OSError) as e:
                log.warning("skipping %s: %s", p.name, e)
        return sorted(snaps, key=lambda s: s.taken_at)

    def read(self) -> RateReading:
        if not self.folder or not self.folder.is_dir():
            return RateReading(message="Choose the folder you save exports to.",
                               source=self.name)
        snaps = self.snapshots()
        if len(snaps) < 2:
            return RateReading(
                message=f"Need 2 exports to compare (found {len(snaps)}).",
                snapshots_used=len(snaps),
                latest_at=snaps[-1].taken_at if snaps else None,
                source=self.name)
        r = compute_rate(snaps[-2], snaps[-1],
                         chaos_per_divine=self.chaos_per_divine,
                         assumed_unit=self.assumed_unit)
        return RateReading(**{**r.__dict__, "source": self.name})
