"""Clipboard-driven pricer tab.

Flow:
    * ``QGuiApplication.clipboard().dataChanged`` fires every time the
      system clipboard is updated (Ctrl+C).
    * If the new text parses as a PoE item we trigger a background
      trade-API lookup and render the result.
    * A "Price manually" button lets the user force a re-price with
      whatever is currently on the clipboard (useful if the signal
      missed, e.g. the clipboard hadn't actually changed).

The heavy lifting (HTTP) runs on a :class:`QThread` so the GUI never
freezes. We coalesce rapid clipboard changes (multiple Ctrl+C in
quick succession on the same item) with a 250ms debounce — otherwise
we'd hit the trade API three times for a single real parse event.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore
from .text import capitalise
from ..pricer import ParsedItem, PriceResult, TradeClient, parse_item, price_item

log = logging.getLogger("poe_qol.ui.pricer")


_CFG_LEAGUE = "pricer.league"
_CFG_AUTO = "pricer.auto_price_on_copy"
_CFG_HAVE = "pricer.have_currency"

_LISTING_COLS = ["#", "Price", "Seller", "Indexed", "Status"]


class _PriceWorker(QThread):
    done = Signal(object, object)   # (ParsedItem, PriceResult)
    failed = Signal(object, str)    # (ParsedItem, message)

    def __init__(self, item: ParsedItem, league: str, have: str,
                 client: TradeClient):
        super().__init__()
        self._item = item
        self._league = league
        self._have = have
        self._client = client

    def run(self) -> None:  # noqa: D401
        try:
            r = price_item(self._item, league=self._league,
                           client=self._client, have=self._have)
            self.done.emit(self._item, r)
        except Exception as e:  # noqa: BLE001
            log.exception("pricer: price_item failed")
            self.failed.emit(self._item, str(e))


class PricerWidget(QWidget):
    def __init__(self, cfg: ConfigStore) -> None:
        super().__init__()
        self.cfg = cfg
        self._client = TradeClient()
        self._worker: Optional[_PriceWorker] = None
        self._last_text: str = ""
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._on_debounce_fire)
        self._build()
        self._wire_clipboard()

    # ---- build ----
    def header_actions(self) -> list[QWidget]:
        return [self.repriced_btn]

    def _build(self) -> None:
        from . import styles as S
        from .components import HelpBadge, StatCard, Switch, caption, card, field
        from .icons import icon

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(18)

        self.repriced_btn = QPushButton("Price Clipboard")
        self.repriced_btn.setProperty("role", "primary")
        self.repriced_btn.setIcon(icon("clipboard", "#1A1200"))
        self.repriced_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.repriced_btn.setToolTip("Price whatever is on the clipboard now.")
        self.repriced_btn.clicked.connect(self._reprice_manual)

        # ---- settings ----
        sc, sl = card()
        row = QHBoxLayout()
        row.setSpacing(18)
        from .league import LeagueBox
        self.league_box = LeagueBox(self.cfg, _CFG_LEAGUE)
        row.addWidget(field("League", self.league_box,
                            "<b>Latest</b> always follows the newest "
                            "challenge league."), 2)
        self.have_edit = QLineEdit(self.cfg.get(_CFG_HAVE, "chaos"))
        self.have_edit.editingFinished.connect(self._persist_prefs)
        row.addWidget(field("Prices In", self.have_edit,
                            "Currency to show prices in: <b>chaos</b>, "
                            "<b>divine</b> or <b>exalted</b>."), 1)
        self.auto_chk = Switch("Auto-Price")
        self.auto_chk.setChecked(bool(self.cfg.get(_CFG_AUTO, True)))
        self.auto_chk.stateChanged.connect(self._persist_prefs)
        aw = QWidget()
        al = QVBoxLayout(aw)
        al.setContentsMargins(0, 22, 0, 0)
        ah = QHBoxLayout()
        ah.addWidget(self.auto_chk)
        ah.addWidget(HelpBadge(
            "Price every item you Ctrl+C in game. Turn off to copy items "
            "without sending a trade-site search each time."))
        ah.addStretch(1)
        al.addLayout(ah)
        row.addWidget(aw, 1)
        sl.addLayout(row)
        v.addWidget(sc)

        # ---- stats ----
        self.item_card = StatCard("Item", "—", sub="Ctrl+C An Item In Game", help=(
            "The last item you copied in game."), icon="tag")
        self.item_card.value.setStyleSheet("font-size:22px;")
        self.item_card.value.setWordWrap(True)
        self.summary = self.item_card.sub
        self.floor_card = StatCard("Lowest", help=(
            "The lowest listed price."), icon="wealth")
        self.real_card = StatCard("Real", help=(
            "The cheapest price after skipping stale listings (old, "
            "likely unsold bait). Usually the price to beat."),
            icon="target", accent=S.ACCENT)
        self.stale_card = StatCard("Stale", help=(
            "Top listings that look abandoned: listed long ago and never "
            "repriced."), icon="info")
        from .components import CardRow
        v.addWidget(CardRow([self.item_card, self.floor_card,
                             self.real_card, self.stale_card], min_w=170))

        # ---- listings ----
        self.raw_btn = QPushButton("Raw Text")
        self.raw_btn.setProperty("role", "pill")
        self.raw_btn.setCheckable(True)
        lc, ll = card("Listings", "The cheapest matching listings on "
                      "pathofexile.com/trade.", icon="search",
                      right=self.raw_btn)
        self.price_card = QLabel("")
        self.price_card.setWordWrap(True)
        self.price_card.setTextFormat(Qt.TextFormat.RichText)
        self.price_card.setOpenExternalLinks(True)
        self.price_card.setVisible(False)
        ll.addWidget(self.price_card)

        self.table = QTableWidget(0, len(_LISTING_COLS))
        self.table.setHorizontalHeaderLabels(_LISTING_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(200)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        ll.addWidget(self.table, 1)

        self.raw = QTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setPlaceholderText("Copied Text Appears Here")
        self.raw.setMaximumHeight(140)
        self.raw.setVisible(False)
        self.raw_btn.toggled.connect(self.raw.setVisible)
        ll.addWidget(self.raw)

        self.status = caption("Waiting For Ctrl+C")
        ll.addWidget(self.status)
        v.addWidget(lc, 1)
        self._reset_stats()

    def _reset_stats(self) -> None:
        for c in (self.floor_card, self.real_card, self.stale_card):
            c.set("—", "")

    # ---- clipboard plumbing ----
    def _wire_clipboard(self) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.dataChanged.connect(self._on_clipboard_changed)

    def _on_clipboard_changed(self) -> None:
        if not self.auto_chk.isChecked():
            return
        # Debounce — PoE and helper tools sometimes touch the
        # clipboard twice on a single Ctrl+C.
        self._debounce.start()

    def _on_debounce_fire(self) -> None:
        cb = QGuiApplication.clipboard()
        text = cb.text() if cb else ""
        if not text or text == self._last_text:
            return
        self._last_text = text
        self._try_price(text)

    def _reprice_manual(self) -> None:
        cb = QGuiApplication.clipboard()
        text = cb.text() if cb else ""
        if not text:
            self.status.setText("Clipboard Is Empty. Ctrl+C An Item First.")
            return
        # Bypass the "same text" guard so the user can force a refetch.
        self._last_text = text
        self._try_price(text)

    # ---- pricing ----
    def _try_price(self, text: str) -> None:
        self.raw.setPlainText(text)
        item = parse_item(text)
        if item is None:
            self.item_card.set("Not An Item", "Copy An Item In Game With Ctrl+C")
            self.price_card.setText("")
            self.price_card.setVisible(False)
            self._reset_stats()
            self.table.setRowCount(0)
            self.status.setText("Idle")
            return
        self._render_summary(item)
        if self._worker and self._worker.isRunning():
            # Don't cancel mid-flight — the user's most recent copy is
            # usually the one they want priced, but interrupting a
            # trade-API request only to fire another is the fastest way
            # to get rate-limited.
            self.status.setText(
                f"Fetching (Queued Behind The Request For "
                f"{self._last_query_label})…")
            return
        league = self.league_box.league()
        have = self.have_edit.text().strip() or "chaos"
        self._last_query_label = item.name
        self.status.setText(f"Fetching Prices For {item.name}…")
        self.repriced_btn.setEnabled(False)
        self._worker = _PriceWorker(item, league, have, self._client)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(
            lambda: self.repriced_btn.setEnabled(True))
        self._worker.start()

    def _on_done(self, item: ParsedItem, result: PriceResult) -> None:
        self._render_result(item, result)
        self.status.setText(
            f"{result.total} Total Listings  ·  Showing {len(result.listings)}")

    def _on_failed(self, item: ParsedItem, msg: str) -> None:
        self.price_card.setText(
            f"<span style='color:#E5484D'><b>Price Lookup Failed.</b> "
            f"{_html_escape(capitalise(msg))}</span>")
        self.price_card.setVisible(True)
        self.table.setRowCount(0)
        self._reset_stats()
        self.status.setText("Failed")

    # ---- render ----
    def _render_summary(self, item: ParsedItem) -> None:
        meta: list[str] = []
        if item.base_type and item.base_type != item.name:
            meta.append(item.base_type)
        meta.append(item.rarity)
        if item.item_class:
            meta.append(item.item_class)
        if item.map_tier is not None:
            meta.append(f"T{item.map_tier}")
        if item.item_level is not None:
            meta.append(f"iLvl {item.item_level}")
        if item.quality:
            meta.append(f"Q{item.quality}%")
        if item.stack_size:
            meta.append(f"Stack {item.stack_size[0]}/{item.stack_size[1]}")
        if item.corrupted:
            meta.append("Corrupted")
        self.item_card.set(item.name, capitalise(" · ".join(m for m in meta if m)))
        self._reset_stats()

    def _render_result(self, item: ParsedItem, r: PriceResult) -> None:
        from . import styles as S
        self.floor_card.set(
            _fmt_price(r.floor, r.floor_currency) if r.floor is not None
            else "—", "")
        eff = r.effective_floor if r.effective_floor is not None else r.floor
        self.real_card.set(
            _fmt_price(eff, r.floor_currency) if eff is not None else "—",
            "Ignoring Stale" if (r.effective_floor is not None
                                 and r.effective_floor != r.floor) else "")
        if r.listings:
            frac = r.stale_fraction * 100
            self.stale_card.set(
                f"{r.stale_count} / {len(r.listings)}",
                f"{frac:.0f}% Of Top Listings",
                color=S.DANGER if r.stale_count else S.SUCCESS)
        else:
            self.stale_card.set("—", "No Listings", color="")

        lines: list[str] = []
        if r.search_url:
            lines.append(
                f"<a href='{r.search_url}' style='color:#D9B25A'>"
                f"Open This Search On The Trade Site →</a>")
        for n in r.notes:
            lines.append(f"<span style='color:#BEB0A4'>· "
                         f"{_html_escape(capitalise(n))}</span>")
        self.price_card.setText("<br>".join(lines))
        self.price_card.setVisible(bool(lines))

        # Populate the table.
        self.table.setRowCount(0)
        for idx, lst in enumerate(r.listings, start=1):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(
                row, 1,
                QTableWidgetItem(_fmt_price(lst.price_amount,
                                            lst.price_currency)))
            self.table.setItem(row, 2, QTableWidgetItem(lst.seller))
            self.table.setItem(row, 3,
                               QTableWidgetItem(_fmt_indexed(lst.indexed)))
            status = ("Stale" if lst.stale
                      else ("Online" if lst.online else "Offline"))
            self.table.setItem(row, 4, QTableWidgetItem(status))

    # ---- persistence ----
    def _persist_prefs(self) -> None:
        self.cfg.set(_CFG_HAVE, self.have_edit.text().strip())
        self.cfg.set(_CFG_AUTO, bool(self.auto_chk.isChecked()))
        try:
            self.cfg.save_user_overrides([_CFG_HAVE, _CFG_AUTO])
        except Exception:
            log.exception("failed to persist pricer prefs")


# ---- helpers ----

def _fmt_price(amount: float, currency: str) -> str:
    if amount >= 100:
        num = f"{amount:,.0f}"
    elif amount >= 10:
        num = f"{amount:.1f}"
    else:
        num = f"{amount:.2f}"
    return f"{num} {currency}" if currency else num


def _fmt_indexed(dt) -> str:
    if dt is None:
        return "—"
    import datetime as _d
    delta = _d.datetime.now(_d.timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s Ago"
    if s < 3600:
        return f"{s // 60}m Ago"
    if s < 86400:
        return f"{s // 3600}h Ago"
    return f"{s // 86400}d Ago"


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
