"""Flipper tab.

Ranks currencies from poe.ninja by a composite flip-attractiveness
score (volume × spread × stability × confidence × liquidity). The
highest-ranked rows are the best bulk-flip candidates for the current
league.

Fetching runs on a ``QThread`` so the UI stays responsive; the snapshot
is cached to disk (``logs/ninja_cache/``) for 10 minutes to be kind to
poe.ninja.

Double-click a row to open a pathofexile.com/trade bulk-exchange search
for that currency (buy side) — saves 4 clicks versus doing it manually.
"""
from __future__ import annotations

import logging
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore
from ..economy import NinjaClient, score_currency_flips, FlipOpportunity

log = logging.getLogger("poe_qol.ui.flipper")


# Config keys (persisted via save_user_overrides).
_CFG_LEAGUE = "flipper.league"
_CFG_MIN_VOL = "flipper.min_volume"
_CFG_INC_LOWCONF = "flipper.include_low_confidence"
_CFG_AUTO_REFRESH_MIN = "flipper.auto_refresh_minutes"

_COLUMNS = [
    ("Name",      "name"),
    ("Value (c)", "chaos_value"),
    ("Spread %",  "spread_pct"),
    ("Spread c",  "spread_chaos"),
    ("7d %",      "change_7d"),
    ("Volume",    "volume"),
    ("Score",     "score"),
]


class _FetchWorker(QThread):
    """Off-thread fetch so the UI doesn't freeze while poe.ninja replies."""
    done = Signal(object)          # list[FlipOpportunity]
    failed = Signal(str)

    def __init__(self, client: NinjaClient, league: str,
                 min_volume: int, include_low_confidence: bool,
                 force: bool):
        super().__init__()
        self._c = client
        self._league = league
        self._min_vol = min_volume
        self._inc_low = include_low_confidence
        self._force = force

    def run(self) -> None:  # noqa: D401
        try:
            snap = self._c.fetch_currency(self._league, force=self._force)
            ops = score_currency_flips(
                snap.lines,
                min_volume=self._min_vol,
                include_low_confidence=self._inc_low,
            )
            self.done.emit(ops)
        except Exception as e:  # noqa: BLE001
            log.exception("ninja fetch failed")
            self.failed.emit(str(e))


class FlipperWidget(QWidget):
    def __init__(self, cfg: ConfigStore, repo_root: Path) -> None:
        super().__init__()
        self.cfg = cfg
        self._ops: list[FlipOpportunity] = []
        self._client = NinjaClient(
            repo_root / "logs" / "ninja_cache",
            freshness_sec=int(cfg.get("flipper.cache_sec", 600)),
        )
        self._worker: Optional[_FetchWorker] = None
        self._build()
        # Fire an initial fetch so the tab is useful on first open.
        QTimer.singleShot(200, self.refresh)

        # Optional auto-refresh.
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(lambda: self.refresh(force=True))
        self._apply_auto_refresh()

    # -- construction --
    def _build(self) -> None:
        v = QVBoxLayout(self)

        # Header row: league, filters, refresh
        top = QHBoxLayout()
        top.addWidget(QLabel("League:"))
        # Default to the trade-tab's league; traders work one league at
        # a time, so sharing the value is the right default.
        default_league = self.cfg.get(_CFG_LEAGUE) or self.cfg.get(
            "trade.league", "Standard")
        self.league_edit = QLineEdit(default_league)
        self.league_edit.setMaximumWidth(160)
        self.league_edit.editingFinished.connect(self._on_league_changed)
        top.addWidget(self.league_edit)

        top.addSpacing(12)
        top.addWidget(QLabel("Min volume:"))
        self.min_vol = QSpinBox()
        self.min_vol.setRange(0, 9999)
        self.min_vol.setValue(int(self.cfg.get(_CFG_MIN_VOL, 10)))
        self.min_vol.setToolTip(
            "Drop currencies with fewer than this many daily trades on "
            "the thinner side of the book. Bulk-flipping needs liquidity.")
        self.min_vol.valueChanged.connect(self._on_filters_changed)
        top.addWidget(self.min_vol)

        self.low_conf = QCheckBox("Include low-confidence")
        self.low_conf.setChecked(bool(self.cfg.get(_CFG_INC_LOWCONF, False)))
        self.low_conf.setToolTip(
            "poe.ninja flags currencies with thin / sparse data as "
            "low-confidence. Hiding them removes most noise but also "
            "some niche high-margin flips.")
        self.low_conf.stateChanged.connect(self._on_filters_changed)
        top.addWidget(self.low_conf)

        top.addSpacing(12)
        top.addWidget(QLabel("Auto refresh:"))
        self.auto_box = QComboBox()
        for label, minutes in (("off", 0), ("5 min", 5), ("10 min", 10),
                               ("30 min", 30)):
            self.auto_box.addItem(label, minutes)
        saved = int(self.cfg.get(_CFG_AUTO_REFRESH_MIN, 0))
        idx = self.auto_box.findData(saved)
        self.auto_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.auto_box.currentIndexChanged.connect(self._on_auto_changed)
        top.addWidget(self.auto_box)

        top.addStretch(1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("role", "primary")
        self.refresh_btn.clicked.connect(lambda: self.refresh(force=True))
        top.addWidget(self.refresh_btn)
        v.addLayout(top)

        # Table
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in _COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(i,
                                        QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemDoubleClicked.connect(self._open_trade_for_selected)
        v.addWidget(self.table, 1)

        # Status + hint
        bot = QHBoxLayout()
        self.status = QLabel("Idle.")
        self.status.setProperty("role", "caption")
        bot.addWidget(self.status, 1)
        hint = QLabel("Double-click a row to open the bulk trade for "
                      "that currency.")
        hint.setProperty("role", "caption")
        bot.addWidget(hint)
        v.addLayout(bot)

    # -- events --
    def _on_league_changed(self) -> None:
        self.cfg.set(_CFG_LEAGUE, self.league_edit.text().strip())
        self._persist_prefs()
        self.refresh(force=True)

    def _on_filters_changed(self) -> None:
        self.cfg.set(_CFG_MIN_VOL, int(self.min_vol.value()))
        self.cfg.set(_CFG_INC_LOWCONF, bool(self.low_conf.isChecked()))
        self._persist_prefs()
        # Re-score locally using the cached snapshot — no network hit.
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
        # setInterval expects ms. Fire within a jittered window so
        # multiple instances don't all hit poe.ninja at :00:00.
        self._auto_timer.start(minutes * 60 * 1000)

    def _persist_prefs(self) -> None:
        try:
            self.cfg.save_user_overrides(
                [_CFG_LEAGUE, _CFG_MIN_VOL, _CFG_INC_LOWCONF,
                 _CFG_AUTO_REFRESH_MIN])
        except Exception:
            log.exception("failed to persist flipper prefs")

    # -- fetch --
    def refresh(self, *, force: bool = False) -> None:
        if self._worker and self._worker.isRunning():
            return
        league = self.league_edit.text().strip() or "Standard"
        self.status.setText(f"Fetching {league}…")
        self.refresh_btn.setEnabled(False)
        self._worker = _FetchWorker(
            self._client, league,
            min_volume=int(self.min_vol.value()),
            include_low_confidence=bool(self.low_conf.isChecked()),
            force=force,
        )
        self._worker.done.connect(self._on_fetch_done)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.finished.connect(
            lambda: self.refresh_btn.setEnabled(True))
        self._worker.start()

    def _on_fetch_done(self, ops: list[FlipOpportunity]) -> None:
        self._ops = ops
        self._render(ops)
        self.status.setText(f"{len(ops)} currencies shown  ·  sorted by score")

    def _on_fetch_failed(self, msg: str) -> None:
        self.status.setText(f"Fetch failed: {msg}")

    def _rescore_and_render(self) -> None:
        """Apply filter changes without a network fetch. We don't keep
        the raw lines around so, instead, reapply the min-volume /
        confidence filters to the already-scored list."""
        min_vol = int(self.min_vol.value())
        inc_low = bool(self.low_conf.isChecked())
        filtered = [o for o in self._ops
                    if o.volume >= min_vol
                    and (inc_low or not o.low_confidence)]
        self._render(filtered)

    # -- render --
    def _render(self, ops: list[FlipOpportunity]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for op in ops:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, (_label, attr) in enumerate(_COLUMNS):
                val = getattr(op, attr, None)
                item = _make_item(attr, val, op)
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(6, Qt.SortOrder.DescendingOrder)

    # -- actions --
    def _open_trade_for_selected(self, _item) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ops):
            return
        # _ops is the un-sorted source; use the visible row's Name cell
        # to look the op up by name so sort state doesn't matter.
        name_item = self.table.item(row, 0)
        if name_item is None:
            return
        name = name_item.text()
        league = self.league_edit.text().strip() or "Standard"
        # Bulk exchange URL — lets the user land on the buy-side order
        # book for that currency directly. The trade site accepts a
        # simple path with want=<slug>&have=chaos; poe.ninja's
        # detailsId is that slug.
        op = next((o for o in self._ops if o.name == name), None)
        slug = (op.line.details_id if op else name.lower().replace(" ", "-"))
        # urlencode handles every odd league-name char (HC / SSF variants
        # include ``+`` and parentheses) where a naive .replace would miss.
        url = ("https://www.pathofexile.com/trade/exchange/"
               f"{urllib.parse.quote(league, safe='')}"
               f"?want={urllib.parse.quote(slug, safe='')}&have=chaos")
        try:
            webbrowser.open(url)
        except Exception:
            log.exception("failed to open browser")


# ---- helpers ------------------------------------------------------------

def _make_item(attr: str, val, op: FlipOpportunity) -> QTableWidgetItem:
    """Build a cell item with sort-friendly UserRole data + a tooltip
    that exposes the score breakdown so users can tell *why* something
    ranks where it does."""
    if val is None:
        item = QTableWidgetItem("—")
        item.setData(Qt.ItemDataRole.UserRole, float("-inf"))
    elif attr == "name":
        item = QTableWidgetItem(str(val))
        item.setData(Qt.ItemDataRole.UserRole, str(val).lower())
    elif attr in ("spread_pct", "change_7d"):
        item = QTableWidgetItem(f"{val:+.1f}%")
        item.setData(Qt.ItemDataRole.UserRole, float(val))
    elif attr == "chaos_value":
        item = QTableWidgetItem(_fmt_chaos(val))
        item.setData(Qt.ItemDataRole.UserRole, float(val))
    elif attr == "spread_chaos":
        item = QTableWidgetItem(f"{val:+.2f}")
        item.setData(Qt.ItemDataRole.UserRole, float(val))
    elif attr == "volume":
        item = QTableWidgetItem(str(int(val)))
        item.setData(Qt.ItemDataRole.UserRole, int(val))
    elif attr == "score":
        item = QTableWidgetItem(f"{val:.3f}")
        item.setData(Qt.ItemDataRole.UserRole, float(val))
    else:
        item = QTableWidgetItem(str(val))

    # Tooltip with the score factors so "why is X ranked here?" is
    # answerable without opening a debugger.
    item.setToolTip(
        "<b>" + op.name + "</b><br>"
        f"volume factor: {op.volume_factor:.2f}<br>"
        f"spread factor: {op.spread_factor:.2f}<br>"
        f"stability factor: {op.stability_factor:.2f}<br>"
        f"confidence factor: {op.confidence_factor:.2f}<br>"
        f"liquidity factor: {op.liquidity_factor:.2f}<br>"
        f"<b>score: {op.score:.3f}</b>"
    )

    # Subtle colour cue on the 7d % column. Green = stable up, red =
    # dumping. Using an alpha so it reads on both themes.
    if attr == "change_7d" and isinstance(val, (int, float)):
        if val > 2:
            item.setForeground(QColor(63, 178, 122))
        elif val < -2:
            item.setForeground(QColor(217, 84, 74))
    if attr == "score" and isinstance(val, (int, float)) and val >= 0.15:
        item.setForeground(QColor(232, 176, 87))   # gold accent
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
    return f"{v:.3f}"
