"""Flipper page.

Ranks currencies from poe.ninja by a composite flip-attractiveness
score (volume × margin × stability × confidence × liquidity). The
highest-ranked rows are the best bulk-flip candidates for the current
league.

Fetching runs on a ``QThread`` so the UI stays responsive; the snapshot
is cached to disk (``logs/ninja_cache/``) for 10 minutes to be kind to
poe.ninja, and an older cache is used if poe.ninja can't be reached.

Double-click a row to open the pathofexile.com/trade bulk exchange for
that currency (paying chaos), in the in-app Trade Browser when enabled.

Fixed here (the tab had stopped working):
    * poe.ninja retired the endpoint it used; see economy/ninja.py.
    * Columns sorted as *text* ("950" > "1,234"); cells now sort on
      their numeric value.
    * Lowering "Min volume" or showing low-confidence rows after a fetch
      did nothing, because only the already-filtered rows were kept.
      The raw lines are kept now and re-scored locally.
    * The bulk-exchange link used ``?want=…&have=…``, which the trade
      site ignores; it now sends a ``q=`` exchange query with the
      trade-site currency id.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView,
    QLineEdit, QPushButton, QSpinBox, QStyle, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore
from ..economy import CurrencyLine, FlipOpportunity, NinjaClient, score_currency_flips
from . import styles as S
from .components import CardRow, HelpBadge, StatCard, Switch, caption, card, field
from .icons import icon

log = logging.getLogger("poe_qol.ui.flipper")


# Config keys (persisted via save_user_overrides).
_CFG_LEAGUE = "flipper.league"
_CFG_MIN_VOL = "flipper.min_volume"
_CFG_INC_LOWCONF = "flipper.include_low_confidence"
_CFG_AUTO_REFRESH_MIN = "flipper.auto_refresh_minutes"

TRADE_EXCHANGE = "https://www.pathofexile.com/trade/exchange/"

# Workers that outlived FlipperWidget.shutdown()'s wait; held so Qt
# doesn't destroy a running QThread (which aborts the process).
_ORPHANS: set = set()

# (header, attribute, header tooltip)
_COLUMNS = [
    ("Currency",  "name",        ""),
    ("Price",     "chaos_value", "Chaos for one."),
    ("7 days",    "change_7d",   "Price change over the last week."),
    ("Volume",    "volume_disp", "Traded per day."),
    ("Edge",      "edge_pct",    "Margin: buy/sell spread, or the gap "
                                 "between its chaos and divine prices."),
    ("Score",     "score",       "Overall flip rating. Higher is better."),
]
_SCORE_COL = 5
_SORT_ROLE = Qt.ItemDataRole.UserRole
_KEY_ROLE = Qt.ItemDataRole.UserRole + 1


def exchange_url(league: str, want: str, have: str = "chaos") -> str:
    """pathofexile.com/trade bulk-exchange URL for ``want`` ← ``have``."""
    q = {"exchange": {"status": {"option": "online"},
                      "have": [have], "want": [want]}}
    return (TRADE_EXCHANGE + urllib.parse.quote(league, safe="")
            + "?q=" + urllib.parse.quote(json.dumps(q, separators=(",", ":"))))


class _FetchWorker(QThread):
    """Off-thread fetch so the UI doesn't freeze while poe.ninja replies.

    The blocking HTTP call runs on a daemon Python thread; this QThread
    only waits for it and honours ``requestInterruption()``. A socket
    stuck until its timeout (offline, firewalled) therefore can't keep
    the QThread alive: on shutdown the QThread returns within ~50 ms and
    the daemon thread is abandoned. Qt aborts the process if a running
    QThread is destroyed, so this matters at exit.
    """
    done = Signal(object)          # CurrencySnapshot
    failed = Signal(str)

    _POLL_SEC = 0.05

    def __init__(self, client: NinjaClient, league: str, force: bool):
        super().__init__()
        self._c = client
        self._league = league
        self._force = force

    def run(self) -> None:  # noqa: D401
        # Locals only: the daemon thread may outlive this QThread object.
        client, league, force = self._c, self._league, self._force
        box: dict = {}
        ready = threading.Event()

        def fetch() -> None:
            try:
                box["snap"] = client.fetch_currency(league, force=force)
            except Exception as e:  # noqa: BLE001
                box["err"] = e
            finally:
                ready.set()

        threading.Thread(target=fetch, name="ninja-fetch",
                         daemon=True).start()
        while not ready.wait(self._POLL_SEC):
            if self.isInterruptionRequested():
                return
        if self.isInterruptionRequested():
            return
        if "err" in box:
            log.warning("ninja fetch failed: %s", box["err"])
            self.failed.emit(str(box["err"]))
        else:
            self.done.emit(box["snap"])


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
        self._shut_down = False
        self._build()
        # Fire an initial fetch so the page is useful on first open. A
        # member timer (not QTimer.singleShot) so shutdown() can stop it.
        self._initial_timer = QTimer(self)
        self._initial_timer.setSingleShot(True)
        self._initial_timer.timeout.connect(lambda: self.refresh())
        self._initial_timer.start(200)

        # Optional auto-refresh.
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(lambda: self.refresh(force=True))
        self._apply_auto_refresh()
        # Keep "updated N min ago" current.
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
        self.top_card = StatCard("Top pick", help=(
            "The highest-scoring currency right now."), icon="flip",
            accent=S.ACCENT)
        self.edge_card = StatCard("Best edge", help=(
            "The biggest margin among the shown currencies."),
            icon="wealth")
        self.count_card = StatCard("Currencies", help=(
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
        # Default to the trade page's league; traders work one league at
        # a time, so sharing the value is the right default.
        default_league = self.cfg.get(_CFG_LEAGUE) or self.cfg.get(
            "trade.league", "Standard")
        self.league_edit = QLineEdit(default_league)
        self.league_edit.editingFinished.connect(self._on_league_changed)
        row.addWidget(field("League", self.league_edit,
                            "Exact league name, e.g. <b>Mirage</b> or "
                            "<b>Hardcore Mirage</b>."), 2)

        self.min_vol = QSpinBox()
        self.min_vol.setRange(0, 999999)
        self.min_vol.setValue(int(self.cfg.get(_CFG_MIN_VOL, 10)))
        self.min_vol.setSuffix(" / day")
        self.min_vol.valueChanged.connect(self._on_filters_changed)
        row.addWidget(field("Min volume", self.min_vol,
                            "Hide currencies that trade fewer than this "
                            "many units a day. Bulk flipping needs "
                            "buyers."), 1)

        self.auto_box = QComboBox()
        for label, minutes in (("Off", 0), ("5 min", 5), ("10 min", 10),
                               ("30 min", 30)):
            self.auto_box.addItem(label, minutes)
        saved = int(self.cfg.get(_CFG_AUTO_REFRESH_MIN, 0))
        idx = self.auto_box.findData(saved)
        self.auto_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.auto_box.currentIndexChanged.connect(self._on_auto_changed)
        row.addWidget(field("Auto refresh", self.auto_box,
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
            "Show thin markets too: currencies with too little data for poe.ninja to be "
            "sure of the price. Riskier, sometimes bigger margins."))
        lch.addStretch(1)
        lcl.addLayout(lch)
        row.addWidget(lc, 1)
        fl.addLayout(row)
        v.addWidget(fc)

        # ---- table ----
        tc, tl = card("Ranking", (
            "Best flips first. Click a header to sort. "
            "<b>Double-click</b> a row to open its bulk exchange on the "
            "trade site."), icon="flip")
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
        self.status = caption("Idle.")
        tl.addWidget(self.status)
        v.addWidget(tc, 1)

    # -- events --
    def _on_league_changed(self) -> None:
        self.cfg.set(_CFG_LEAGUE, self.league_edit.text().strip())
        self._persist_prefs()
        self.refresh(force=True)

    def _on_filters_changed(self) -> None:
        self.cfg.set(_CFG_MIN_VOL, int(self.min_vol.value()))
        self.cfg.set(_CFG_INC_LOWCONF, bool(self.low_conf.isChecked()))
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
                [_CFG_LEAGUE, _CFG_MIN_VOL, _CFG_INC_LOWCONF,
                 _CFG_AUTO_REFRESH_MIN])
        except Exception:
            log.exception("failed to persist flipper prefs")

    # -- lifecycle --
    def shutdown(self, wait_ms: int = 2000) -> None:
        """Stop timers and the fetch worker; later refreshes are no-ops.

        Call before the widget goes away (MainWindow.closeEvent does).
        Idempotent. An in-flight HTTP request is abandoned, not awaited
        (see _FetchWorker), so this returns quickly even offline.
        """
        if self._shut_down:
            return
        self._shut_down = True
        for t in (self._initial_timer, self._auto_timer, self._age_timer):
            t.stop()
        w, self._worker = self._worker, None
        if w is None:
            return
        for sig in (w.done, w.failed, w.finished):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass
        w.requestInterruption()
        if not w.wait(wait_ms):
            # Shouldn't happen (the worker polls every 50 ms). Keep it
            # referenced so it isn't destroyed while running.
            log.warning("flipper fetch worker did not stop in %d ms",
                        wait_ms)
            _ORPHANS.add(w)

    # -- fetch --
    def refresh(self, *, force: bool = False) -> None:
        if self._shut_down:
            return
        if self._worker and self._worker.isRunning():
            return
        league = self.league_edit.text().strip() or "Standard"
        self.status.setText(f"Fetching {league} prices…")
        self.refresh_btn.setEnabled(False)
        self._worker = _FetchWorker(self._client, league, force=force)
        self._worker.done.connect(self._on_fetch_done)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.finished.connect(self._on_fetch_finished)
        self._worker.start()

    def _on_fetch_finished(self) -> None:
        if not self._shut_down:
            self.refresh_btn.setEnabled(True)

    def _on_fetch_done(self, snap) -> None:
        # A result queued before shutdown() disconnected can still land.
        if self._shut_down:
            return
        self._snapshot = snap
        self._lines = list(snap.lines)
        self._rescore_and_render()

    def _on_fetch_failed(self, msg: str) -> None:
        if self._shut_down:
            return
        self.status.setText(f"⚠  {msg}")
        if not self._lines:
            self.age_card.set("—", "fetch failed", color=S.DANGER)

    def _rescore_and_render(self) -> None:
        self._ops = score_currency_flips(
            self._lines,
            min_volume=int(self.min_vol.value()),
            include_low_confidence=bool(self.low_conf.isChecked()),
        )
        self._render(self._ops)
        if self._snapshot is not None:
            note = ("  ·  offline, showing saved prices"
                    if self._snapshot.stale else "")
            self.status.setText(
                f"{len(self._ops)} of {len(self._lines)} currencies  ·  "
                f"best first{note}")
        self._render_age()

    # -- render --
    def _render_age(self) -> None:
        snap = self._snapshot
        if snap is None:
            return
        mins = int(max(0, time.time() - snap.fetched_at) // 60)
        when = "just now" if mins < 1 else (
            f"{mins} min ago" if mins < 120 else f"{mins // 60} h ago")
        if snap.stale:
            self.age_card.set(when, "offline · saved prices", color=S.WARN)
        else:
            self.age_card.set(when, f"poe.ninja · {snap.league}", color="")

    def _render(self, ops: list[FlipOpportunity]) -> None:
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
            self.top_card.set(top.name, f"score {top.score * 100:.0f}")
        else:
            self.top_card.set("—", "nothing passes the filters")
        edged = [o for o in ops if o.edge_pct is not None]
        if edged:
            best = max(edged, key=lambda o: abs(o.edge_pct))
            self.edge_card.set(f"{best.edge_pct:+.1f}%", best.name,
                               color=S.SUCCESS if best.edge_pct > 0 else S.WARN)
        else:
            self.edge_card.set("—", "no margin data", color="")
        self.count_card.set(str(len(ops)),
                            f"of {len(self._lines)} tracked"
                            if self._lines else "")

    # -- actions --
    def _open_trade_for_item(self, item: QTableWidgetItem) -> None:
        name_item = self.table.item(item.row(), 0)
        if name_item is None:
            return
        key = name_item.data(_KEY_ROLE)
        op = next((o for o in self._ops if _op_key(o) == key), None)
        if op is None:
            return
        league = self.league_edit.text().strip() or "Standard"
        want = op.trade_id or op.line.details_id or \
            op.name.lower().replace(" ", "-")
        url = exchange_url(league, want)
        if self._open_in_app is not None:
            self._open_in_app(url)
            return
        try:
            webbrowser.open(url)
        except Exception:
            log.exception("failed to open browser")


# ---- helpers ------------------------------------------------------------

def _op_key(op: FlipOpportunity) -> str:
    return op.trade_id or op.name


def _make_item(attr: str, op: FlipOpportunity) -> QTableWidgetItem:
    """Cell with numeric sort data + a tooltip that explains the score,
    so "why is X ranked here?" is answerable at a glance."""
    if attr == "volume_disp":
        val = op.volume_chaos if op.volume_chaos is not None else op.volume
        text = (_fmt_compact(op.volume_chaos) + " c"
                if op.volume_chaos is not None else f"{op.volume:,}")
    else:
        val = getattr(op, attr, None)
        text = None

    item = _SortItem()
    if val is None:
        item.setText("—")
        item.setData(_SORT_ROLE, float("-inf"))
    elif attr == "name":
        item.setText(str(val))
        item.setData(_SORT_ROLE, str(val).lower())
        item.setData(_KEY_ROLE, _op_key(op))
        if op.low_confidence:
            item.setText(f"{val}  ·  thin")
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
        f"volume {op.volume_factor:.2f} · margin {op.spread_factor:.2f}<br>"
        f"stability {op.stability_factor:.2f} · "
        f"confidence {op.confidence_factor:.2f}<br>"
        f"liquidity {op.liquidity_factor:.2f}<br>"
        f"<b>score {op.score * 100:.0f}</b> · double-click to trade")

    if attr in ("change_7d", "edge_pct") and isinstance(val, (int, float)):
        if val > 2:
            item.setForeground(QColor(S.SUCCESS))
        elif val < -2:
            item.setForeground(QColor(S.DANGER))
    if attr == "name" and op.low_confidence:
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
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= div:
            return f"{v / div:.1f}{suf}"
    return f"{v:.0f}"
