"""Flipper page.

Ranks everything poe.ninja prices (currency, fragments, scarabs,
essences, divination cards, gems, maps, uniques…, but not unique
weapons or armour) by a composite flip-attractiveness score (volume ×
margin × stability × confidence × liquidity). The highest-ranked rows
are the best flip candidates for the league.

Fetching runs on a ``QThread`` so the UI stays responsive; each category
is cached to disk (``logs/ninja_cache/``) for 10 minutes to be kind to
poe.ninja, and an older cache is used if poe.ninja can't be reached.

Double-click a row to open it on pathofexile.com/trade (bulk exchange
for currency-like items, a normal search for gems, maps and uniques), in
the in-app Trade Browser when enabled.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView,
    QPushButton, QSpinBox, QStyle, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore
from ..economy import CurrencyLine, FlipOpportunity, NinjaClient, score_currency_flips
from ..economy.ninja import ALL_CATEGORIES, category_label
from . import styles as S
from .components import CardRow, HelpBadge, StatCard, Switch, caption, card, field
from .icons import icon
from .league import LeagueBox
from .text import capitalise

log = logging.getLogger("poe_qol.ui.flipper")


# Config keys (persisted via save_user_overrides).
_CFG_LEAGUE = "flipper.league"
_CFG_CATEGORY = "flipper.category"
_CFG_MIN_VOL = "flipper.min_volume"
_CFG_INC_LOWCONF = "flipper.include_low_confidence"
_CFG_AUTO_REFRESH_MIN = "flipper.auto_refresh_minutes"

TRADE_EXCHANGE = "https://www.pathofexile.com/trade/exchange/"
# First run: how long to wait for the latest-league lookup before
# fetching prices anyway.
LEAGUE_WAIT_MS = 5000
TRADE_SEARCH = "https://www.pathofexile.com/trade/search/"
ALL = "all"

# (header, attribute, header tooltip)
_COLUMNS = [
    ("Item",      "name",        ""),
    ("Category",  "category",    "Its poe.ninja category."),
    ("Price",     "chaos_value", "Chaos for one."),
    ("7 Days",    "change_7d",   "Price change over the last week."),
    ("Volume",    "volume_disp", "Currency-like items: chaos traded per day. "
                                 "Gems, maps and uniques: how many are listed."),
    ("Edge",      "edge_pct",    "Margin: buy/sell spread, or the gap "
                                 "between its chaos and divine prices."),
    ("Score",     "score",       "Overall flip rating. Higher is better."),
]
_SCORE_COL = 6
_SORT_ROLE = Qt.ItemDataRole.UserRole
_KEY_ROLE = Qt.ItemDataRole.UserRole + 1


def exchange_url(league: str, want: str, have: str = "chaos") -> str:
    """pathofexile.com/trade bulk-exchange URL for ``want`` ← ``have``."""
    q = {"exchange": {"status": {"option": "online"},
                      "have": [have], "want": [want]}}
    return (TRADE_EXCHANGE + urllib.parse.quote(league, safe="")
            + "?q=" + urllib.parse.quote(json.dumps(q, separators=(",", ":"))))


def search_url(league: str, line: CurrencyLine) -> str:
    """pathofexile.com/trade search for one gem / map / unique, cheapest
    first, with its level, quality, links and tier as filters."""
    query: dict = {"status": {"option": "online"}}
    if line.search_name:
        query["name"] = line.search_name
    query["type"] = line.search_type or line.name
    filters: dict = {}
    misc: dict = {}
    if line.gem_level:
        misc["gem_level"] = {"min": line.gem_level}
    if line.gem_quality:
        misc["quality"] = {"min": line.gem_quality}
    if line.corrupted is not None and (line.gem_level or line.category.startswith("Unique")):
        misc["corrupted"] = {"option": "true" if line.corrupted else "false"}
    if misc:
        filters["misc_filters"] = {"filters": misc}
    if line.links and line.links >= 5:
        filters["socket_filters"] = {"filters": {"links": {"min": line.links}}}
    if line.map_tier:
        filters["map_filters"] = {"filters": {"map_tier": {
            "min": line.map_tier, "max": line.map_tier}}}
    if filters:
        query["filters"] = filters
    q = {"query": query, "sort": {"price": "asc"}}
    return (TRADE_SEARCH + urllib.parse.quote(league, safe="")
            + "?q=" + urllib.parse.quote(json.dumps(q, separators=(",", ":"))))


def trade_url(league: str, line: CurrencyLine) -> str:
    if line.is_bulk:
        want = line.trade_id or line.details_id or line.name.lower().replace(" ", "-")
        return exchange_url(league, want)
    return search_url(league, line)


class _FetchWorker(QThread):
    """Off-thread fetch so the UI doesn't freeze while poe.ninja replies."""
    done = Signal(object)          # CurrencySnapshot
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, client: NinjaClient, league: str, force: bool):
        super().__init__()
        self._c = client
        self._league = league
        self._force = force

    def run(self) -> None:  # noqa: D401
        try:
            self.done.emit(self._c.fetch_all(
                self._league, categories=ALL_CATEGORIES, force=self._force,
                progress=lambda n, t: self.progress.emit(n, t)))
        except Exception as e:  # noqa: BLE001
            log.warning("ninja fetch failed: %s", e)
            self.failed.emit(str(e))


class _SortItem(QTableWidgetItem):
    """Sorts on ``_SORT_ROLE`` instead of the display text."""

    def __lt__(self, other: QTableWidgetItem) -> bool:  # noqa: D105
        a, b = self.data(_SORT_ROLE), other.data(_SORT_ROLE)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class _ScoreBar(QStyledItemDelegate):
    """Draws the score as a gilt bar, scaled to the best visible score."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.top = 1.0

    def paint(self, p: QPainter, opt, index) -> None:  # noqa: D102
        if opt.state & QStyle.StateFlag.State_Selected:
            p.fillRect(opt.rect, QColor(217, 178, 90, 46))
        val = index.data(_SORT_ROLE)
        if not isinstance(val, (int, float)) or val == float("-inf"):
            return super().paint(p, opt, index)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(opt.rect).adjusted(8, 0, -8, 0)
        text_w = 44
        bar = QRectF(r.left(), r.center().y() - 4, r.width() - text_w, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(S.BG_3))
        p.drawRoundedRect(bar, 4, 4)
        frac = max(0.0, min(1.0, val / self.top if self.top > 0 else 0))
        if frac > 0:
            fill = QRectF(bar.left(), bar.top(), max(8.0, bar.width() * frac), 8)
            p.setBrush(QColor(S.ACCENT))
            p.drawRoundedRect(fill, 4, 4)
        p.setPen(QColor(S.FG_0))
        p.drawText(QRectF(bar.right() + 6, r.top(), text_w - 6, r.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                   f"{val * 100:.0f}")
        p.restore()


class FlipperWidget(QWidget):
    def __init__(self, cfg: ConfigStore, repo_root: Path,
                 open_in_app: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self._open_in_app = open_in_app
        self._lines: list[CurrencyLine] = []
        self._ops: list[FlipOpportunity] = []
        self._snapshot = None
        self._client = NinjaClient(
            repo_root / "logs" / "ninja_cache",
            freshness_sec=int(cfg.get("flipper.cache_sec", 600)),
        )
        self._worker: Optional[_FetchWorker] = None
        # A refresh asked for while a fetch runs (e.g. the latest league
        # just arrived): None = nothing queued, else its `force` flag.
        self._pending: Optional[bool] = None
        self._build()
        # Fire an initial fetch so the page is useful on first open. On
        # a first run the league list isn't known yet: wait for it (the
        # league picker's league_changed starts the fetch) rather than
        # fetching Standard prices, with a fallback if it is slow.
        from .league import league_service
        from ..trade.leagues import is_auto
        if is_auto(self.league_box.value()) and not league_service().leagues:
            QTimer.singleShot(LEAGUE_WAIT_MS, self._initial_refresh)
        else:
            QTimer.singleShot(200, self._initial_refresh)

        # Optional auto-refresh.
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(lambda: self.refresh(force=True))
        self._apply_auto_refresh()
        # Keep "Updated N Min Ago" current.
        self._age_timer = QTimer(self)
        self._age_timer.timeout.connect(self._render_age)
        self._age_timer.start(30_000)

    # -- construction --
    def header_actions(self) -> list[QWidget]:
        return [self.refresh_btn]

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(18)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("role", "primary")
        self.refresh_btn.setIcon(icon("refresh", "#1A1200"))
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setToolTip("Fetch fresh prices from poe.ninja.")
        self.refresh_btn.clicked.connect(lambda: self.refresh(force=True))

        # ---- stat cards ----
        self.top_card = StatCard("Top Pick", help=(
            "The highest-scoring item right now."), icon="flip",
            accent=S.ACCENT)
        self.edge_card = StatCard("Best Edge", help=(
            "The biggest margin among the shown items."),
            icon="wealth")
        self.count_card = StatCard("Items", help=(
            "How many pass your filters."), icon="tag")
        self.age_card = StatCard("Updated", help=(
            "When poe.ninja's prices were fetched. Cached for 10 minutes."),
            icon="refresh")
        v.addWidget(CardRow([self.top_card, self.edge_card,
                             self.count_card, self.age_card], min_w=200))

        # ---- filters ----
        fc, fl = card()
        row = QHBoxLayout()
        row.setSpacing(18)
        self.league_box = LeagueBox(self.cfg, _CFG_LEAGUE)
        self.league_box.league_changed.connect(lambda _l: self.refresh())
        row.addWidget(field("League", self.league_box,
                            "<b>Latest</b> always follows the newest "
                            "challenge league."), 2)

        self.category_box = QComboBox()
        self.category_box.addItem("All Categories", ALL)
        for cat in ALL_CATEGORIES:
            self.category_box.addItem(category_label(cat), cat)
        i = self.category_box.findData(self.cfg.get(_CFG_CATEGORY, ALL))
        self.category_box.setCurrentIndex(max(0, i))
        self.category_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.category_box.setMinimumContentsLength(8)
        self.category_box.currentIndexChanged.connect(self._on_filters_changed)
        row.addWidget(field("Category", self.category_box,
                            "Everything poe.ninja prices except unique "
                            "weapons and armour."), 2)

        self.min_vol = QSpinBox()
        self.min_vol.setRange(0, 999999)
        self.min_vol.setValue(int(self.cfg.get(_CFG_MIN_VOL, 10)))
        self.min_vol.valueChanged.connect(self._on_filters_changed)
        row.addWidget(field("Min Volume", self.min_vol,
                            "Hide items that trade fewer than this many "
                            "a day (gems, maps and uniques: fewer listed). "
                            "Flipping needs buyers."), 1)

        self.auto_box = QComboBox()
        for label, minutes in (("Off", 0), ("5 Min", 5), ("10 Min", 10),
                               ("30 Min", 30)):
            self.auto_box.addItem(label, minutes)
        saved = int(self.cfg.get(_CFG_AUTO_REFRESH_MIN, 0))
        idx = self.auto_box.findData(saved)
        self.auto_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.auto_box.currentIndexChanged.connect(self._on_auto_changed)
        row.addWidget(field("Auto Refresh", self.auto_box,
                            "Re-fetch prices on a timer."), 1)

        self.low_conf = Switch("Thin")
        self.low_conf.setChecked(bool(self.cfg.get(_CFG_INC_LOWCONF, False)))
        self.low_conf.stateChanged.connect(self._on_filters_changed)
        lc = QWidget()
        lcl = QVBoxLayout(lc)
        lcl.setContentsMargins(0, 22, 0, 0)
        lch = QHBoxLayout()
        lch.addWidget(self.low_conf)
        lch.addWidget(HelpBadge(
            "Show thin markets too: items with too little data for "
            "poe.ninja to be sure of the price. Riskier, sometimes bigger "
            "margins."))
        lch.addStretch(1)
        lcl.addLayout(lch)
        row.addWidget(lc, 0)
        fl.addLayout(row)
        v.addWidget(fc)

        # ---- table ----
        tc, tl = card("Ranking", (
            "Best flips first. Click a header to sort. "
            "<b>Double-click</b> a row to open it on the trade site."),
            icon="flip")
        self.table = QTableWidget(0, len(_COLUMNS))
        for i, (label, _attr, tip) in enumerate(_COLUMNS):
            hi = QTableWidgetItem(label)
            if tip:
                hi.setToolTip(tip)
            hi.setTextAlignment(Qt.AlignmentFlag.AlignLeft
                                | Qt.AlignmentFlag.AlignVCenter)
            self.table.setHorizontalHeaderItem(i, hi)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setCursor(Qt.CursorShape.PointingHandCursor)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(60)
        for i in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_SCORE_COL, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(_SCORE_COL, 150)
        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setMinimumHeight(260)
        self._bar = _ScoreBar(self.table)
        self.table.setItemDelegateForColumn(_SCORE_COL, self._bar)
        self.table.itemDoubleClicked.connect(self._open_trade_for_item)
        tl.addWidget(self.table, 1)
        self.status = caption("Idle")
        tl.addWidget(self.status)
        v.addWidget(tc, 1)

    # -- events --
    def _on_filters_changed(self, *_a) -> None:
        self.cfg.set(_CFG_MIN_VOL, int(self.min_vol.value()))
        self.cfg.set(_CFG_INC_LOWCONF, bool(self.low_conf.isChecked()))
        self.cfg.set(_CFG_CATEGORY, self.category_box.currentData() or ALL)
        self._persist_prefs()
        # Re-score locally from the kept raw lines; no network hit.
        self._rescore_and_render()

    def _on_auto_changed(self) -> None:
        minutes = int(self.auto_box.currentData() or 0)
        self.cfg.set(_CFG_AUTO_REFRESH_MIN, minutes)
        self._persist_prefs()
        self._apply_auto_refresh()

    def _apply_auto_refresh(self) -> None:
        minutes = int(self.cfg.get(_CFG_AUTO_REFRESH_MIN, 0) or 0)
        if minutes <= 0:
            self._auto_timer.stop()
            return
        self._auto_timer.start(minutes * 60 * 1000)

    def _persist_prefs(self) -> None:
        try:
            self.cfg.save_user_overrides(
                [_CFG_MIN_VOL, _CFG_INC_LOWCONF, _CFG_AUTO_REFRESH_MIN,
                 _CFG_CATEGORY])
        except Exception:
            log.exception("failed to persist flipper prefs")

    # -- fetch --
    def _initial_refresh(self) -> None:
        if self._snapshot is None and not self._busy():
            self.refresh()

    def _busy(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def refresh(self, *, force: bool = False) -> None:
        if self._busy():
            # Run again when the current fetch ends: its league may be
            # out of date (the league list arrived mid-fetch).
            self._pending = bool(self._pending) or force
            return
        league = self.league_box.league()
        self.status.setText(f"Fetching {league} Prices…")
        self.refresh_btn.setEnabled(False)
        self._worker = _FetchWorker(self._client, league, force=force)
        self._worker.done.connect(self._on_fetch_done)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.progress.connect(
            lambda n, t: self.status.setText(
                f"Fetching {league} Prices…  {n} / {t} Categories"))
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        self.refresh_btn.setEnabled(True)
        if self._pending is not None:
            force, self._pending = self._pending, None
            self.refresh(force=force)

    def _on_fetch_done(self, snap) -> None:
        if snap.league != self.league_box.league():
            log.info("ignoring %s prices: league is now %s",
                     snap.league, self.league_box.league())
            return
        self._snapshot = snap
        self._lines = list(snap.lines)
        self._rescore_and_render()

    def _on_fetch_failed(self, msg: str) -> None:
        self.status.setText(f"⚠  {capitalise(msg)}")
        if not self._lines:
            self.age_card.set("—", "Fetch Failed", color=S.DANGER)

    def _rescore_and_render(self) -> None:
        cat = self.category_box.currentData() or ALL
        lines = self._lines if cat == ALL else [
            l for l in self._lines if l.category == cat]
        self._ops = score_currency_flips(
            lines,
            min_volume=int(self.min_vol.value()),
            include_low_confidence=bool(self.low_conf.isChecked()),
        )
        self._render(self._ops, len(lines))
        snap = self._snapshot
        if snap is not None:
            notes = []
            if snap.stale:
                notes.append("Offline, Showing Saved Prices")
            if snap.missing:
                notes.append(f"{len(snap.missing)} Categories Unavailable")
            note = "".join(f"  ·  {n}" for n in notes)
            self.status.setText(
                f"{len(self._ops)} Of {len(lines)} Items  ·  Best First{note}")
            self.status.setToolTip(
                "Unavailable: " + ", ".join(category_label(c) for c in snap.missing)
                if snap.missing else "")
        self._render_age()

    # -- render --
    def _render_age(self) -> None:
        snap = self._snapshot
        if snap is None:
            return
        mins = int(max(0, time.time() - snap.fetched_at) // 60)
        when = "Just Now" if mins < 1 else (
            f"{mins} Min Ago" if mins < 120 else f"{mins // 60} H Ago")
        if snap.stale:
            self.age_card.set(when, "Offline · Saved Prices", color=S.WARN)
        else:
            self.age_card.set(when, f"PoE Ninja · {snap.league}", color="")

    def _render(self, ops: list[FlipOpportunity], tracked: int) -> None:
        self._bar.top = max((o.score for o in ops), default=1.0) or 1.0
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for op in ops:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, (_label, attr, _tip) in enumerate(_COLUMNS):
                self.table.setItem(row, col, _make_item(attr, op))
        self.table.setSortingEnabled(True)
        self.table.sortItems(_SCORE_COL, Qt.SortOrder.DescendingOrder)

        if ops:
            top = ops[0]
            self.top_card.set(top.name, f"Score {top.score * 100:.0f}  ·  "
                              f"{category_label(top.category)}")
        else:
            self.top_card.set("—", "Nothing Passes The Filters")
        edged = [o for o in ops if o.edge_pct is not None]
        if edged:
            best = max(edged, key=lambda o: abs(o.edge_pct))
            self.edge_card.set(f"{best.edge_pct:+.1f}%", best.name,
                               color=S.SUCCESS if best.edge_pct > 0 else S.WARN)
        else:
            self.edge_card.set("—", "No Margin Data", color="")
        self.count_card.set(str(len(ops)),
                            f"Of {tracked:,} Tracked" if tracked else "")

    # -- actions --
    def _open_trade_for_item(self, item: QTableWidgetItem) -> None:
        name_item = self.table.item(item.row(), 0)
        if name_item is None:
            return
        key = name_item.data(_KEY_ROLE)
        op = next((o for o in self._ops if _op_key(o) == key), None)
        if op is None:
            return
        url = trade_url(self.league_box.league(), op.line)
        if self._open_in_app is not None:
            self._open_in_app(url)
            return
        try:
            webbrowser.open(url)
        except Exception:
            log.exception("failed to open browser")


# ---- helpers ------------------------------------------------------------

def _op_key(op: FlipOpportunity) -> str:
    return f"{op.category}:{op.trade_id or op.name}"


def _make_item(attr: str, op: FlipOpportunity) -> QTableWidgetItem:
    """Cell with numeric sort data + a tooltip that explains the score,
    so "why is X ranked here?" is answerable at a glance."""
    if attr == "volume_disp":
        if op.listings is not None:
            val, text = op.listings, f"{op.listings:,} Listed"
        elif op.volume_chaos is not None:
            val, text = op.volume_chaos, _fmt_compact(op.volume_chaos) + " c"
        else:
            val, text = op.volume, f"{op.volume:,}"
    elif attr == "category":
        val, text = category_label(op.category), None
    else:
        val = getattr(op, attr, None)
        text = None

    item = _SortItem()
    if val is None:
        item.setText("—")
        item.setData(_SORT_ROLE, float("-inf"))
    elif attr in ("name", "category"):
        item.setText(str(val))
        item.setData(_SORT_ROLE, str(val).lower())
        if attr == "name":
            item.setData(_KEY_ROLE, _op_key(op))
            if op.low_confidence:
                item.setText(f"{val}  ·  Thin")
    elif attr in ("edge_pct", "change_7d"):
        item.setText(f"{val:+.1f}%")
        item.setData(_SORT_ROLE, float(val))
    elif attr == "chaos_value":
        item.setText(_fmt_chaos(val) + " c")
        item.setData(_SORT_ROLE, float(val))
    elif attr == "score":
        item.setText(f"{val * 100:.0f}")
        item.setData(_SORT_ROLE, float(val))
    else:
        item.setText(text if text is not None else str(val))
        item.setData(_SORT_ROLE, float(val))

    item.setToolTip(
        f"<b>{op.name}</b><br>"
        f"Volume {op.volume_factor:.2f} · Margin {op.spread_factor:.2f}<br>"
        f"Stability {op.stability_factor:.2f} · "
        f"Confidence {op.confidence_factor:.2f}<br>"
        f"Liquidity {op.liquidity_factor:.2f}<br>"
        f"<b>Score {op.score * 100:.0f}</b> · Double-Click To Trade")

    if attr in ("change_7d", "edge_pct") and isinstance(val, (int, float)):
        if val > 2:
            item.setForeground(QColor(S.SUCCESS))
        elif val < -2:
            item.setForeground(QColor(S.DANGER))
    if attr in ("name", "category") and op.low_confidence:
        item.setForeground(QColor(S.FG_1))
    if attr == "category":
        item.setForeground(QColor(S.FG_1))
    return item


def _fmt_chaos(v: float) -> str:
    """Avoid '0.00' for high-denomination currencies; show what humans
    trade with."""
    if v is None:
        return "—"
    if v >= 100:
        return f"{v:,.0f}"
    if v >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}"


def _fmt_compact(v: float) -> str:
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v / div:.1f}{suf}"
    return f"{v:.0f}"
