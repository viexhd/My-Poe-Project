"""One stash sync: list tabs → fetch the chosen ones → price → save.

This is what Wealthy Exile's **Sync stash** button does, using GGG's
official ``account:stashes`` API with the player's own sign-in. The
Wealth tab runs it on demand and, if switched on, every hour.

Tab layout from ``GET /stash/<league>``:

* ordinary tabs have no ``children``;
* a ``Folder`` tab holds whole tabs as children: each child is fetched
  by its own id;
* special tabs with sub-sections (Map, Unique, ...) list them as
  ``children``: each is fetched as ``/<parent id>/<child id>``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from ..ggg.api import ApiError, Cancelled, PoeApi
from .pricing import PriceBook
from .stash_valuation import price_item
from .wealth_store import ItemLine, NewSnapshot, TabTotal, WealthStore

log = logging.getLogger("poe_qol.economy.stash_sync")


@dataclass
class TabRef:
    id: str                       # id used for selection (child id for children)
    name: str
    type: str
    index: int = 0
    parent_id: str | None = None  # set for sub-sections of special tabs
    folder: str | None = None     # folder name, for display
    colour: str = ""

    @property
    def label(self) -> str:
        return f"{self.folder} / {self.name}" if self.folder else self.name


def flatten_tabs(stashes: Iterable[dict]) -> list[TabRef]:
    """Leaf tabs in game order. Parents with children are replaced by
    their children."""
    out: list[TabRef] = []

    def colour(t: dict) -> str:
        md = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        return str(md.get("colour") or "")

    for t in sorted((s for s in stashes if isinstance(s, dict)),
                    key=lambda s: int(s.get("index") or 0)):
        tid, name, typ = str(t.get("id") or ""), str(t.get("name") or ""), \
            str(t.get("type") or "")
        kids = [c for c in t.get("children") or [] if isinstance(c, dict)]
        if not tid:
            continue
        if not kids:
            out.append(TabRef(tid, name, typ, int(t.get("index") or 0),
                              colour=colour(t)))
            continue
        for c in sorted(kids, key=lambda c: int(c.get("index") or 0)):
            cid = str(c.get("id") or "")
            if not cid:
                continue
            out.append(TabRef(
                cid, str(c.get("name") or typ), str(c.get("type") or typ),
                int(c.get("index") or 0),
                parent_id=None if typ == "Folder" else tid,
                folder=name, colour=colour(c) or colour(t)))
    return out


@dataclass
class SyncResult:
    snapshot_id: int
    total_chaos: float
    chaos_per_divine: float | None
    tabs: int
    items: int
    unpriced: int
    seconds: float
    skipped_tabs: list[str] = field(default_factory=list)


Progress = Callable[[str, int, int], None]


class StashSync:
    def __init__(self, api: PoeApi, store: WealthStore,
                 prices: Callable[[str], PriceBook]) -> None:
        self.api = api
        self.store = store
        self.prices = prices

    def list_tabs(self, league: str, realm: str = "pc") -> list[TabRef]:
        return flatten_tabs(self.api.list_stashes(league, realm))

    def _fetch(self, league: str, realm: str, tab: TabRef) -> dict | None:
        if tab.parent_id:
            try:
                return self.api.get_stash(league, tab.parent_id, tab.id, realm)
            except ApiError as e:
                if e.status != 404:
                    raise
        return self.api.get_stash(league, tab.id, None, realm)

    def run(self, *, account: str, league: str, realm: str = "pc",
            tab_ids: set[str] | None = None,
            progress: Progress | None = None,
            cancelled: Callable[[], bool] | None = None) -> SyncResult:
        t0 = time.time()
        say = progress or (lambda *_a: None)
        is_cancelled = cancelled or (lambda: False)
        self.api.cancelled = is_cancelled

        say("Listing stash tabs…", 0, 0)
        tabs = self.list_tabs(league, realm)
        if tab_ids is not None:
            tabs = [t for t in tabs if t.id in tab_ids]
        if not tabs:
            raise ApiError("No stash tabs to sync. Pick tabs under "
                           "“Synced tabs”, or check the league.")

        say("Loading prices…", 0, len(tabs))
        book = self.prices(league)
        if is_cancelled():
            raise Cancelled("Sync cancelled.")

        lines: list[ItemLine] = []
        totals: list[TabTotal] = []
        unpriced = 0
        skipped: list[str] = []
        for n, tab in enumerate(tabs, 1):
            say(f"Tab {n}/{len(tabs)}: {tab.label}", n - 1, len(tabs))
            try:
                stash = self._fetch(league, realm, tab)
            except Cancelled:
                raise
            except ApiError as e:
                if e.status in (401, 403):
                    raise
                log.warning("skipping tab %s: %s", tab.label, e)
                skipped.append(tab.label)
                continue
            agg: dict[str, ItemLine] = {}
            for it in (stash or {}).get("items") or []:
                if not isinstance(it, dict):
                    continue
                p = price_item(it, book)
                if p.unit_chaos is None or p.unit_chaos <= 0:
                    unpriced += 1
                    continue
                cur = agg.get(p.name)
                if cur is None:
                    agg[p.name] = ItemLine(tab.id, tab.label, p.name, p.category,
                                           p.quantity, p.unit_chaos,
                                           p.total_chaos, p.icon)
                else:
                    cur.quantity += p.quantity
                    cur.total_chaos += p.total_chaos
            lines.extend(agg.values())
            totals.append(TabTotal(tab.id, tab.label, tab.type,
                                   sum(x.total_chaos for x in agg.values())))
        say("Saving snapshot…", len(tabs), len(tabs))
        snap = NewSnapshot(account=account, league=league, realm=realm,
                           taken_at=time.time(),
                           chaos_per_divine=book.chaos_per_divine,
                           unpriced_count=unpriced, tabs=totals, items=lines,
                           note=("prices stale" if book.stale else None))
        sid = self.store.add(snap)
        return SyncResult(snapshot_id=sid, total_chaos=snap.total_chaos,
                          chaos_per_divine=book.chaos_per_divine,
                          tabs=len(totals), items=len(lines), unpriced=unpriced,
                          seconds=time.time() - t0, skipped_tabs=skipped)


def csv_to_snapshot(path, *, account: str, league: str) -> NewSnapshot:
    """A Wealthy Exile CSV export as a snapshot, so old exports can join
    the same history."""
    from .wealthy_exile_csv import parse_snapshot
    s = parse_snapshot(path)
    lines = [ItemLine(tab or "csv", tab or "CSV", name, "", qty,
                      (total / qty) if qty else 0.0, total)
             for name, tab, qty, total in s.items]
    if not lines and s.total:
        lines = [ItemLine("csv", "CSV", "(export total)", "", 1, s.total, s.total)]
    rate = s.divine_price
    if s.unit == "divine":
        lines = [ItemLine(l.stash_id, l.tab_name, l.name, l.category, l.quantity,
                          l.unit_chaos * (rate or 1), l.total_chaos * (rate or 1))
                 for l in lines]
    return NewSnapshot(account=account, league=league,
                       taken_at=s.taken_at.timestamp(), chaos_per_divine=rate,
                       source="csv", note=Path(path).name,
                       tabs=[], items=lines)

