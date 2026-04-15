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
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore
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
    def _build(self) -> None:
        v = QVBoxLayout(self)

        # Toolbar: league, have, auto-toggle, manual re-price.
        top = QHBoxLayout()
        top.addWidget(QLabel("League:"))
        default_league = (self.cfg.get(_CFG_LEAGUE)
                          or self.cfg.get("trade.league", "Standard"))
        self.league_edit = QLineEdit(default_league)
        self.league_edit.setMaximumWidth(160)
        self.league_edit.editingFinished.connect(self._persist_prefs)
        top.addWidget(self.league_edit)

        top.addSpacing(12)
        top.addWidget(QLabel("Denominate in:"))
        self.have_edit = QLineEdit(self.cfg.get(_CFG_HAVE, "chaos"))
        self.have_edit.setMaximumWidth(100)
        self.have_edit.setToolTip(
            "Trade slug for the currency you want prices in. "
            "Common: chaos, divine, exalted.")
        self.have_edit.editingFinished.connect(self._persist_prefs)
        top.addWidget(self.have_edit)

        self.auto_chk = QCheckBox("Auto-price on copy")
        self.auto_chk.setChecked(bool(self.cfg.get(_CFG_AUTO, True)))
        self.auto_chk.setToolTip(
            "When on, every Ctrl+C on an item queries the trade API. "
            "Turn off to browse/compare without spamming requests.")
        self.auto_chk.stateChanged.connect(self._persist_prefs)
        top.addWidget(self.auto_chk)

        top.addStretch(1)
        self.repriced_btn = QPushButton("Price clipboard")
        self.repriced_btn.setProperty("role", "primary")
        self.repriced_btn.clicked.connect(self._reprice_manual)
        top.addWidget(self.repriced_btn)
        v.addLayout(top)

        # Item summary card.
        self.summary = QLabel("Ctrl+C an item in Path of Exile to price it.")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            "padding:10px; background:#151A22; border:1px solid #2A3240;"
            " border-radius:6px; color:#E6EAF2;")
        v.addWidget(self.summary)

        # Price card.
        self.price_card = QLabel("")
        self.price_card.setWordWrap(True)
        self.price_card.setTextFormat(Qt.TextFormat.RichText)
        self.price_card.setStyleSheet(
            "padding:10px; background:#1C222C; border:1px solid #2A3240;"
            " border-radius:6px;")
        v.addWidget(self.price_card)

        # Listings table.
        self.table = QTableWidget(0, len(_LISTING_COLS))
        self.table.setHorizontalHeaderLabels(_LISTING_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.table, 1)

        # Raw item box (collapsible feel via small height).
        self.raw = QTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setPlaceholderText("Raw clipboard text will appear here.")
        self.raw.setMaximumHeight(120)
        v.addWidget(self.raw)

        # Status line.
        self.status = QLabel("Idle.")
        self.status.setProperty("role", "caption")
        v.addWidget(self.status)

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
            self.status.setText("Clipboard is empty.")
            return
        # Bypass the "same text" guard so the user can force a refetch.
        self._last_text = text
        self._try_price(text)

    # ---- pricing ----
    def _try_price(self, text: str) -> None:
        self.raw.setPlainText(text)
        item = parse_item(text)
        if item is None:
            self.summary.setText("Clipboard doesn't look like a PoE item.")
            self.price_card.setText("")
            self.table.setRowCount(0)
            self.status.setText("Idle.")
            return
        self._render_summary(item)
        if self._worker and self._worker.isRunning():
            # Don't cancel mid-flight — the user's most recent copy is
            # usually the one they want priced, but interrupting a
            # trade-API request only to fire another is the fastest way
            # to get rate-limited.
            self.status.setText(
                f"Fetching (queued behind previous request for "
                f"{self._last_query_label})…")
            return
        league = self.league_edit.text().strip() or "Standard"
        have = self.have_edit.text().strip() or "chaos"
        self._last_query_label = item.name
        self.status.setText(f"Fetching prices for {item.name}…")
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
            f"{result.total} total listings  ·  showing {len(result.listings)}")

    def _on_failed(self, item: ParsedItem, msg: str) -> None:
        self.price_card.setText(
            f"<b>Price lookup failed.</b><br>{_html_escape(msg)}")
        self.table.setRowCount(0)
        self.status.setText("Failed.")

    # ---- render ----
    def _render_summary(self, item: ParsedItem) -> None:
        parts = [f"<b>{_html_escape(item.name)}</b>"]
        if item.base_type and item.base_type != item.name:
            parts.append(f"<span style='color:#A9B2C3'>"
                         f"{_html_escape(item.base_type)}</span>")
        meta: list[str] = [item.rarity]
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
            meta.append("<span style='color:#D9544A'>Corrupted</span>")
        parts.append("<span style='color:#A9B2C3'>"
                     + " · ".join(_html_escape(m) for m in meta) + "</span>")
        self.summary.setText("<br>".join(parts))

    def _render_result(self, item: ParsedItem, r: PriceResult) -> None:
        lines: list[str] = []
        if r.floor is not None:
            lines.append(
                f"<b>Floor:</b> {_fmt_price(r.floor, r.floor_currency)}")
        if r.effective_floor is not None and r.effective_floor != r.floor:
            lines.append(
                f"<b>Effective floor (ignoring stale):</b> "
                f"<span style='color:#E8B057'>"
                f"{_fmt_price(r.effective_floor, r.floor_currency)}</span>")
        if r.stale_count:
            frac = r.stale_fraction * 100
            lines.append(
                f"<span style='color:#D9544A'>{r.stale_count} of "
                f"{len(r.listings)} top listings look stale "
                f"({frac:.0f}%).</span>")
        if r.search_url:
            lines.append(
                f"<a href='{r.search_url}' style='color:#4FA7E3'>"
                f"Open on pathofexile.com/trade →</a>")
        for n in r.notes:
            lines.append(f"<span style='color:#A9B2C3'>· "
                         f"{_html_escape(n)}</span>")
        self.price_card.setText("<br>".join(lines) if lines
                                else "No pricing data.")
        self.price_card.setOpenExternalLinks(True)

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
            status = ("stale" if lst.stale
                      else ("online" if lst.online else "offline"))
            self.table.setItem(row, 4, QTableWidgetItem(status))

    # ---- persistence ----
    def _persist_prefs(self) -> None:
        self.cfg.set(_CFG_LEAGUE, self.league_edit.text().strip())
        self.cfg.set(_CFG_HAVE, self.have_edit.text().strip())
        self.cfg.set(_CFG_AUTO, bool(self.auto_chk.isChecked()))
        try:
            self.cfg.save_user_overrides([_CFG_LEAGUE, _CFG_HAVE, _CFG_AUTO])
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
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
