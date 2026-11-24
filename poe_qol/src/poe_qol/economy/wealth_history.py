"""Wealth change over a time range the player picks.

Given a range ``[start, end]`` this picks two snapshots:

* the *start* snapshot: the newest one taken at or before ``start``
  (so "last 24 h" compares against the stash as it was 24 h ago); if
  there is none, the first one inside the range;
* the *end* snapshot: the newest one at or before ``end``.

The change is ``end - start``; per hour divides by the real time
between the two snapshots, not by the range length.

Divine conversion uses **one** rate for both ends (the end snapshot's,
or the player's override), so a moving divine price doesn't show up as
profit or loss. Wealthy Exile does the same.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .wealth_rate import RateReading
from .wealth_store import ItemLine, SnapshotHead, WealthStore

RANGE_PRESETS: tuple[tuple[str, str, float | None], ...] = (
    ("1h", "Last Hour", 1),
    ("3h", "Last 3 Hours", 3),
    ("6h", "Last 6 Hours", 6),
    ("12h", "Last 12 Hours", 12),
    ("24h", "Last 24 Hours", 24),
    ("3d", "Last 3 Days", 72),
    ("7d", "Last 7 Days", 168),
    ("14d", "Last 14 Days", 336),
    ("30d", "Last 30 Days", 720),
    ("all", "All History", None),
    ("custom", "Custom Range…", None),
)


def preset_hours(key: str) -> float | None:
    for k, _label, hours in RANGE_PRESETS:
        if k == key:
            return hours
    return None


@dataclass
class ItemChange:
    name: str
    category: str
    tabs: str
    qty_start: float
    qty_end: float
    value_start: float
    value_end: float
    unit_end: float
    icon: str = ""

    @property
    def qty_delta(self) -> float:
        return self.qty_end - self.qty_start

    @property
    def value_delta(self) -> float:
        return self.value_end - self.value_start


@dataclass
class RangeResult:
    start: SnapshotHead | None = None
    end: SnapshotHead | None = None
    chaos_per_divine: float | None = None
    series: list[SnapshotHead] = field(default_factory=list)
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.start is not None and self.end is not None \
            and self.end.taken_at > self.start.taken_at

    @property
    def hours(self) -> float:
        if not self.ok:
            return 0.0
        return (self.end.taken_at - self.start.taken_at) / 3600.0

    @property
    def delta_chaos(self) -> float | None:
        return (self.end.total_chaos - self.start.total_chaos) if self.ok else None

    @property
    def delta_pct(self) -> float | None:
        if not self.ok or self.start.total_chaos <= 0:
            return None
        return self.delta_chaos / self.start.total_chaos * 100.0

    def to_div(self, chaos: float | None) -> float | None:
        if chaos is None or not self.chaos_per_divine:
            return None
        return chaos / self.chaos_per_divine

    @property
    def chaos_per_hour(self) -> float | None:
        return self.delta_chaos / self.hours if self.ok and self.hours > 0 else None

    def reading(self, source: str = "Stash sync") -> RateReading:
        """For the overlay."""
        if not self.ok:
            return RateReading(message=self.message or "Need 2 syncs in range.",
                               snapshots_used=len(self.series),
                               latest_at=_dt(self.end), source=source)
        cph = self.chaos_per_hour
        msg = "" if self.chaos_per_divine else "No divine price yet."
        return RateReading(divine_per_hour=self.to_div(cph), chaos_per_hour=cph,
                           span_minutes=self.hours * 60.0, snapshots_used=2,
                           latest_at=_dt(self.end), message=msg, source=source)


def _dt(head: SnapshotHead | None):
    from datetime import datetime
    return datetime.fromtimestamp(head.taken_at) if head else None


def compute_range(store: WealthStore, account: str, league: str,
                  start: float | None, end: float, *,
                  chaos_per_divine: float | None = None) -> RangeResult:
    """``start=None`` means all history."""
    series = store.snapshots(account, league, start, end)
    end_snap = store.latest(account, league, at_or_before=end)
    start_snap = None
    if start is not None:
        start_snap = store.latest(account, league, at_or_before=start)
    if start_snap is None:
        start_snap = series[0] if series else None
    if start_snap is not None and (not series or series[0].id != start_snap.id):
        series = [start_snap] + series
    rate = chaos_per_divine if chaos_per_divine and chaos_per_divine > 0 else None
    if rate is None and end_snap is not None:
        rate = end_snap.chaos_per_divine
    msg = ""
    if end_snap is None:
        msg = "No syncs yet. Press Sync now."
    elif start_snap is None or start_snap.id == end_snap.id:
        msg = "Need 2 syncs in this range."
    return RangeResult(start=start_snap, end=end_snap, chaos_per_divine=rate,
                       series=series, message=msg)


def item_changes(store: WealthStore, start: SnapshotHead | None,
                 end: SnapshotHead | None, *, by_tab: bool = False) -> list[ItemChange]:
    """Per-item change between two snapshots, biggest value change first.
    Items are merged across tabs unless ``by_tab``."""
    def index(lines: list[ItemLine]) -> dict[tuple, list[ItemLine]]:
        out: dict[tuple, list[ItemLine]] = {}
        for ln in lines:
            key = (ln.name, ln.stash_id) if by_tab else (ln.name,)
            out.setdefault(key, []).append(ln)
        return out

    a = index(store.items(start.id)) if start else {}
    b = index(store.items(end.id)) if end else {}
    out: list[ItemChange] = []
    for key in set(a) | set(b):
        la, lb = a.get(key, []), b.get(key, [])
        ref = (lb or la)[0]
        qe = sum(x.quantity for x in lb)
        ve = sum(x.total_chaos for x in lb)
        out.append(ItemChange(
            name=ref.name, category=ref.category or "",
            tabs=", ".join(sorted({x.tab_name for x in (lb or la)})),
            qty_start=sum(x.quantity for x in la), qty_end=qe,
            value_start=sum(x.total_chaos for x in la), value_end=ve,
            unit_end=(ve / qe) if qe else (lb or la)[0].unit_chaos,
            icon=ref.icon))
    out.sort(key=lambda c: (-abs(c.value_delta), -c.value_end))
    return out


def hourly_series(series: list[SnapshotHead]) -> list[tuple[float, float]]:
    """``(taken_at, chaos_per_hour)`` for each consecutive pair."""
    out: list[tuple[float, float]] = []
    for a, b in zip(series, series[1:]):
        hours = (b.taken_at - a.taken_at) / 3600.0
        if hours > 0:
            out.append((b.taken_at, (b.total_chaos - a.total_chaos) / hours))
    return out
