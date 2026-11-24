"""Wealth tab: stash sync from your Path of Exile account, Wealthy Exile style.

1. **Connect**: opens pathofexile.com's own consent page in your browser
   (log in there and press *Authorize*). The app gets a token for
   ``account:profile``, ``account:leagues`` and ``account:stashes`` only.
2. **Sync**: reads the chosen stash tabs through GGG's official API,
   prices every item with poe.ninja and saves a snapshot locally.
   Automatic sync repeats this every hour (or the interval you pick).
3. **Range**: pick any time range; the tab shows the wealth change
   between the snapshots at its two ends, per hour, a Total/Hourly
   chart and per-item gains and losses.

Old Wealthy Exile CSV exports can still be imported into the same
history. Nothing is sent anywhere except to pathofexile.com (your stash)
and poe.ninja (prices, by league and item type only).
"""
from __future__ import annotations

import logging
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDateTime, QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateTimeEdit,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..core.config import ConfigStore
from ..economy.wealth_history import (
    RANGE_PRESETS, RangeResult, compute_range, hourly_series, item_changes,
    preset_hours,
)
from ..economy.wealth_service import WealthService
from ..ggg.api import AuthExpired, Cancelled
from .league import LeagueBox
from .text import capitalise
from .wealth_chart import WealthChart
from .wealth_overlay import WealthOverlay

log = logging.getLogger("poe_qol.ui.wealth")

GGG_DEV_DOCS = "https://www.pathofexile.com/developer/docs"
REALMS = (("pc", "PC"), ("xbox", "Xbox"), ("sony", "PlayStation"))
SYNC_INTERVALS = (15, 30, 60, 120, 240, 360)     # minutes
MIN_SYNC_INTERVAL = 15
MANUAL_COOLDOWN_SEC = 60
RETRY_AFTER_FAIL_SEC = 10 * 60

_K = "wealth."
_K_LEAGUE, _K_REALM = _K + "league", _K + "realm"
_K_AUTO, _K_INTERVAL = _K + "auto_sync", _K + "sync_interval_minutes"
_K_TABS, _K_RANGE, _K_CUSTOM = _K + "synced_tabs", _K + "range", _K + "range_custom"
_K_CHART, _K_RATE = _K + "chart", _K + "chaos_per_divine"
_K_VISIBLE, _K_POS = _K + "overlay_visible", _K + "overlay_pos"
_K_CLIENT, _K_CONTACT, _K_PORT = (_K + "oauth.client_id", _K + "oauth.contact",
                                  _K + "oauth.redirect_port")

_SORT = Qt.ItemDataRole.UserRole + 1


def clamp_sync_interval(minutes) -> int:
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        m = 60
    return max(MIN_SYNC_INTERVAL, m)


def _ago(ts: float, now: float | None = None) -> str:
    s = max(0, int((now or time.time()) - ts))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s / 3600:.1f} h ago"
    return f"{s / 86400:.1f} days ago"


def _signed(v: float, digits: int = 2) -> str:
    return f"{'+' if v > 0 else ''}{v:,.{digits}f}"


class _Task(QThread):
    """Runs ``fn(progress, cancelled)`` off the UI thread."""
    progress = Signal(str, int, int)
    done = Signal(object)
    failed = Signal(object)

    def __init__(self, fn: Callable, parent=None) -> None:
        super().__init__(parent)
        self._fn = fn
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:  # noqa: D401
        try:
            self.done.emit(self._fn(lambda m, a=0, b=0: self.progress.emit(m, a, b),
                                    self._cancel.is_set))
        except Exception as e:  # noqa: BLE001
            log.warning("wealth task failed: %s", e)
            self.failed.emit(e)


class _NumItem(QTableWidgetItem):
    def __init__(self, text: str, value: float) -> None:
        super().__init__(text)
        self.setData(_SORT, value)
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other) -> bool:  # noqa: D105
        a, b = self.data(_SORT), other.data(_SORT)
        try:
            return float(a) < float(b)
        except (TypeError, ValueError):
            return str(self.text()) < str(other.text())


class TabPickerDialog(QDialog):
    """Wealthy Exile's "Edit synced tabs"."""

    def __init__(self, tabs, selected: set[str] | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Synced Tabs")
        self.resize(420, 520)
        v = QVBoxLayout(self)
        self.all_cb = QCheckBox("Sync Every Tab (New Tabs Included)")
        self.all_cb.setChecked(selected is None)
        v.addWidget(self.all_cb)
        self.list = QListWidget()
        for t in tabs:
            it = QListWidgetItem(f"{t.label}   ·  {t.type}")
            it.setData(Qt.ItemDataRole.UserRole, t.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            on = selected is None or t.id in selected
            it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        self.list.setEnabled(selected is not None)
        self.all_cb.toggled.connect(lambda on: self.list.setEnabled(not on))
        v.addWidget(self.list, 1)
        note = QLabel("Fewer tabs = faster syncs. GGG rate-limits stash reads, "
                      "so a big account can take a few minutes per sync.")
        note.setWordWrap(True)
        note.setObjectName("StatSub")
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def selection(self) -> list[str] | None:
        if self.all_cb.isChecked():
            return None
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


class WealthWidget(QWidget):
    def __init__(self, cfg: ConfigStore, *, service: WealthService | None = None,
                 data_dir: Path | None = None, ninja_cache: Path | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        if service is None:
            from ..paths import user_data_dir
            service = WealthService(
                data_dir or user_data_dir(), client_id=cfg.get(_K_CLIENT),
                contact=cfg.get(_K_CONTACT), ninja_cache=ninja_cache)
        self.svc = service
        self._task: _Task | None = None
        self._login = None                       # PendingLogin while signing in
        self._last_attempt = 0.0
        self._last_failed = False
        self._range: RangeResult | None = None
        self._shut = False

        self.overlay = WealthOverlay()
        self.overlay.refresh_requested.connect(self.sync_now)
        self.overlay.hide_requested.connect(lambda: self.overlay_cb.setChecked(False))
        self.overlay.moved.connect(self._on_overlay_moved)

        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30_000)
        self._update_account()
        self.refresh()
        if self.cfg.get(_K_VISIBLE, False):
            self.overlay_cb.setChecked(True)
        if self.svc.connected and self.svc.configured:
            QTimer.singleShot(4000, self._tick)

    # ================================================================ UI
    def header_actions(self) -> list[QWidget]:
        return [self.connect_btn, self.sync_btn]

    def _build(self) -> None:
        from . import styles as S
        from .components import CardRow, StatCard, Switch, card, field, with_help
        from .icons import icon

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(18)

        self.sync_btn = QPushButton("Sync Now")
        self.sync_btn.setProperty("role", "primary")
        self.sync_btn.setIcon(icon("refresh", "#1A1200"))
        self.sync_btn.setToolTip("Read your stash tabs now and save a snapshot.")
        self.sync_btn.clicked.connect(self._on_sync_clicked)
        self.connect_btn = QPushButton("Connect Account")
        self.connect_btn.setIcon(icon("external", S.FG_1))
        self.connect_btn.clicked.connect(self._on_connect_clicked)

        # ---- account strip ----
        ac, al = card("Path Of Exile Account", (
            "Like Wealthy Exile: <b>Connect account</b> opens pathofexile.com "
            "in your browser. Log in there and press <b>Authorize</b>. The "
            "app is allowed to read your account name, leagues and stash "
            "tabs, nothing else, and never sees your password.<br><br>"
            "<b>Disconnect</b> deletes the saved sign-in and revokes it."),
            icon="globe")
        row = QHBoxLayout()
        row.setSpacing(14)
        self.account_label = QLabel("Not Connected")
        self.account_label.setObjectName("CardTitle")
        row.addWidget(self.account_label, 1)
        self.league_box = LeagueBox(self.cfg, _K_LEAGUE)
        self.league_box.setMinimumWidth(180)
        self.league_box.league_changed.connect(self._on_league_changed)
        row.addWidget(field("League", self.league_box,
                            "<b>Latest</b> follows the newest challenge "
                            "league. History is kept per league."))
        self.realm_box = QComboBox()
        for key, label in REALMS:
            self.realm_box.addItem(label, key)
        self.realm_box.setCurrentIndex(max(0, self.realm_box.findData(
            self.cfg.get(_K_REALM, "pc"))))
        self.realm_box.currentIndexChanged.connect(self._on_realm_changed)
        row.addWidget(field("Realm", self.realm_box))
        al.addLayout(row)
        prow = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setVisible(False)
        self.status_label = QLabel("")
        self.status_label.setObjectName("StatSub")
        self.status_label.setWordWrap(True)
        prow.addWidget(self.status_label, 1)
        al.addLayout(prow)
        al.addWidget(self.progress)
        v.addWidget(ac)

        # ---- stat cards ----
        self.worth_card = StatCard("Net Worth", "—", icon="wealth", accent=S.ACCENT,
                                   help="Value of the synced tabs at the newest "
                                        "sync in the range.")
        self.change_card = StatCard("Change", "—", help=(
            "Wealth at the end of the range minus wealth at its start (the "
            "newest sync at or before the start). Both ends use the same "
            "divine price, so a moving divine price isn't counted as profit."))
        self.rate_card = StatCard("Per Hour", "—", hero=True, accent=S.ACCENT, help=(
            "The change divided by the real time between the two syncs."))
        self.reading_label = self.rate_card.value
        self.detail_label = self.rate_card.sub
        self.sync_card = StatCard("Last Sync", "—", icon="refresh",
                                  help="When the newest snapshot was taken, "
                                       "and when the next automatic sync runs.")
        v.addWidget(CardRow([self.rate_card, self.change_card, self.worth_card,
                             self.sync_card], min_w=200))

        # ---- range + chart ----
        right = QHBoxLayout()
        right.setSpacing(8)
        self.range_box = QComboBox()
        for key, label, _h in RANGE_PRESETS:
            self.range_box.addItem(label, key)
        self.range_box.setCurrentIndex(max(0, self.range_box.findData(
            self.cfg.get(_K_RANGE, "24h"))))
        self.range_box.currentIndexChanged.connect(self._on_range_changed)
        right.addWidget(self.range_box)
        self.from_edit = QDateTimeEdit()
        self.to_edit = QDateTimeEdit()
        custom = self.cfg.get(_K_CUSTOM)
        now = time.time()
        a, b = (custom if isinstance(custom, (list, tuple)) and len(custom) == 2
                else (now - 86400, now))
        for ed, ts in ((self.from_edit, a), (self.to_edit, b)):
            ed.setCalendarPopup(True)
            ed.setDisplayFormat("dd MMM HH:mm")
            ed.setDateTime(QDateTime.fromSecsSinceEpoch(int(ts)))
            ed.dateTimeChanged.connect(self._on_custom_changed)
            right.addWidget(ed)
        self.total_btn = QPushButton("Total")
        self.hourly_btn = QPushButton("Hourly")
        grp = QButtonGroup(self)
        for b_, key in ((self.total_btn, "total"), (self.hourly_btn, "hourly")):
            b_.setCheckable(True)
            b_.setProperty("chart", key)
            grp.addButton(b_)
            right.addWidget(b_)
        (self.hourly_btn if self.cfg.get(_K_CHART) == "hourly"
         else self.total_btn).setChecked(True)
        grp.buttonClicked.connect(self._on_chart_mode)
        cc, cl = card("Wealth", "<b>Total</b>: net worth at each sync. "
                      "<b>Hourly</b>: gain or loss per hour between syncs.",
                      icon="wealth", right=right)
        self.range_label = QLabel("")
        self.range_label.setObjectName("StatSub")
        cl.addWidget(self.range_label)
        self.chart = WealthChart()
        cl.addWidget(self.chart, 1)
        v.addWidget(cc)

        # ---- items ----
        irow = QHBoxLayout()
        irow.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter Items")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._fill_table)
        irow.addWidget(self.search_edit)
        self.changed_cb = QCheckBox("Only Changed")
        self.changed_cb.toggled.connect(self._fill_table)
        irow.addWidget(self.changed_cb)
        ic, il = card("Items", "Priced items at the end of the range, with how "
                      "much each one changed since the start. Unpriced items "
                      "(rares, magic gear) aren't counted, as on Wealthy Exile.",
                      icon="clipboard", right=irow)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Tab", "Quantity", "Price (c)", "Total", "Δ Qty", "Δ Value"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 7):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(300)
        self.table.setSortingEnabled(True)
        il.addWidget(self.table, 1)
        self.items_note = QLabel("")
        self.items_note.setObjectName("StatSub")
        il.addWidget(self.items_note)
        v.addWidget(ic)

        # ---- sync settings ----
        sc, sl = card("Sync", (
            "Automatic sync reads your stash every interval while the app "
            "runs (hourly by default). GGG's rate limits are obeyed: the app "
            "waits instead of hammering the API. Manual syncs have a "
            f"{MANUAL_COOLDOWN_SEC} s cooldown."), icon="refresh")
        grid = QHBoxLayout()
        grid.setSpacing(18)
        self.auto_cb = Switch("Automatic Sync", big=True)
        self.auto_cb.setChecked(bool(self.cfg.get(_K_AUTO, True)))
        self.auto_cb.toggled.connect(self._on_auto_toggled)
        grid.addWidget(self.auto_cb)
        self.interval_box = QComboBox()
        cur = clamp_sync_interval(self.cfg.get(_K_INTERVAL, 60))
        opts = sorted(set(SYNC_INTERVALS) | {cur})
        for m in opts:
            self.interval_box.addItem(f"Every {m} min" if m < 60 else
                                      f"Every {m // 60} h" if m % 60 == 0 else
                                      f"Every {m} min", m)
        self.interval_box.setCurrentIndex(self.interval_box.findData(cur))
        self.interval_box.currentIndexChanged.connect(self._on_interval_changed)
        grid.addWidget(field("Interval", self.interval_box), 1)
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0, 100000)
        self.rate_spin.setDecimals(1)
        self.rate_spin.setSpecialValueText("Auto")
        self.rate_spin.setValue(float(self.cfg.get(_K_RATE, 0) or 0))
        self.rate_spin.valueChanged.connect(self._on_rate_changed)
        grid.addWidget(field("Chaos Per Divine", self.rate_spin,
                             "<b>Auto</b> uses poe.ninja's Divine Orb price "
                             "at the newest sync."), 1)
        self.tabs_btn = QPushButton("Synced Tabs…")
        self.tabs_btn.clicked.connect(self._on_tabs_clicked)
        grid.addWidget(self.tabs_btn)
        sl.addLayout(grid)
        orow = QHBoxLayout()
        self.overlay_cb = Switch("Show Per-Hour Overlay In Game")
        self.overlay_cb.toggled.connect(self._on_overlay_toggled)
        orow.addWidget(with_help(self.overlay_cb, (
            "A small always-on-top box over the game with the per-hour "
            "rate for the selected range. Drag to move, right-click for "
            "options. Needs windowed or windowed-fullscreen.")))
        orow.addStretch(1)
        imp = QPushButton("Import Wealthy Exile CSV…")
        imp.setIcon(icon("folder", S.FG_1))
        imp.clicked.connect(self._import_csv)
        orow.addWidget(imp)
        self.delete_btn = QPushButton("Delete History…")
        self.delete_btn.setProperty("role", "danger")
        self.delete_btn.clicked.connect(self._delete_history)
        orow.addWidget(self.delete_btn)
        sl.addLayout(orow)
        v.addWidget(sc)

        # ---- app registration ----
        rc, rl = card("GGG App Registration", (
            "GGG only lets registered apps use account sign-in. The app's "
            "<b>client ID</b> comes with the release; if yours is empty, "
            "register a <i>public</i> client with GGG (see "
            "pathofexile.com/developer/docs, email oauth@grindinggear.com) "
            "with redirect <code>http://127.0.0.1</code> and the scopes "
            "account:profile, account:leagues, account:stashes, then paste "
            "the client ID here."), icon="info")
        crow = QHBoxLayout()
        self.client_edit = QLineEdit(self.svc.client_id)
        self.client_edit.setPlaceholderText("Client ID From GGG")
        self.client_edit.editingFinished.connect(self._on_client_edited)
        crow.addWidget(field("OAuth Client ID", self.client_edit), 1)
        docs = QPushButton("Developer Docs")
        docs.setIcon(icon("external", S.FG_1))
        docs.clicked.connect(lambda: webbrowser.open(GGG_DEV_DOCS))
        crow.addWidget(docs, 0, Qt.AlignmentFlag.AlignBottom)
        rl.addLayout(crow)
        v.addWidget(rc)
        v.addStretch(1)          # spare height goes below the cards
        self._sync_custom_visible()

    # =========================================================== helpers
    @property
    def league(self) -> str:
        return self.league_box.league()

    @property
    def realm(self) -> str:
        return self.realm_box.currentData() or "pc"

    @property
    def account(self) -> str:
        return self.svc.account or "local"

    def _persist(self, *keys: str) -> None:
        try:
            self.cfg.save_user_overrides(list(keys))
        except Exception:  # noqa: BLE001
            pass

    def _say(self, text: str, error: bool = False) -> None:
        from . import styles as S
        self.status_label.setText(capitalise(text))
        self.status_label.setStyleSheet(f"color:{S.DANGER};" if error else "")

    def _busy(self) -> bool:
        return self._task is not None and self._task.isRunning()

    def _run(self, fn, done, failed=None, *, progress=True) -> bool:
        if self._busy() or self._shut:
            return False
        t = _Task(fn, self)
        self._task = t
        if progress:
            t.progress.connect(self._on_progress)
        t.done.connect(done)
        t.failed.connect(failed or self._on_task_failed)
        t.finished.connect(self._on_task_finished)
        self.progress.setVisible(progress)
        self.progress.setRange(0, 0)
        self._update_buttons()
        t.start()
        return True

    def _on_progress(self, msg: str, done: int, total: int) -> None:
        self._say(msg)
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            self.progress.setRange(0, 0)

    def _on_task_finished(self) -> None:
        self.progress.setVisible(False)
        self._task = None
        self._update_buttons()

    def _on_task_failed(self, e: Exception) -> None:
        if isinstance(e, Cancelled):
            self._say("Cancelled.")
            return
        self._last_failed = True
        if isinstance(e, AuthExpired):
            self.svc.disconnect(revoke=False)
            self._update_account()
        self._say(str(e) or e.__class__.__name__, error=True)

    def _update_buttons(self) -> None:
        busy = self._busy()
        syncing = busy and getattr(self._task, "kind", "") == "sync"
        self.sync_btn.setText("Cancel" if syncing else "Sync Now")
        self.sync_btn.setEnabled(self.svc.connected and (not busy or syncing))
        self.tabs_btn.setEnabled(self.svc.connected and not busy)
        if self._login is not None:
            self.connect_btn.setText("Cancel Sign-In")
            self.connect_btn.setEnabled(True)
        else:
            self.connect_btn.setText("Disconnect" if self.svc.connected
                                     else "Connect Account")
            self.connect_btn.setEnabled(not busy and (self.svc.connected
                                                      or self.svc.configured))

    def _update_account(self) -> None:
        if not self.svc.configured:
            self.account_label.setText("Not Connected")
            self._say("This build has no GGG client ID yet: see "
                      "“GGG app registration” below.", error=True)
        elif self.svc.connected:
            self.account_label.setText(f"Connected As {self.svc.account or 'Your Account'}")
        else:
            self.account_label.setText("Not Connected")
            self._say("Press Connect account and authorize on pathofexile.com.")
        self._update_buttons()

    # =========================================================== account
    def _on_connect_clicked(self) -> None:
        if self._login is not None:
            self._login.receiver.close()
            return
        if self.svc.connected:
            if QMessageBox.question(
                    self, "Disconnect",
                    "Forget and revoke the pathofexile.com sign-in? Your saved "
                    "history stays.") != QMessageBox.StandardButton.Yes:
                return
            self.svc.disconnect()
            self._update_account()
            self.refresh()
            return
        try:
            pending = self.svc.begin_login(int(self.cfg.get(_K_PORT, 0) or 0))
        except Exception as e:  # noqa: BLE001
            self._say(str(e), error=True)
            return
        self._login = pending
        webbrowser.open(pending.url)
        self._say("Waiting for you to press Authorize on pathofexile.com…")

        def work(_p, _c):
            return self.svc.finish_login(pending)

        if not self._run(work, self._on_login_done, self._on_login_failed):
            pending.receiver.close()
            self._login = None
        self._update_buttons()

    def _on_login_done(self, _tok) -> None:
        self._login = None
        self._last_failed = False
        self._update_account()
        self._say("Connected. Syncing your stash…")
        self.refresh()
        QTimer.singleShot(0, lambda: self.sync_now(manual=False))

    def _on_login_failed(self, e: Exception) -> None:
        self._login = None
        self._update_account()
        self._say(str(e), error=True)

    # ============================================================== sync
    def _on_sync_clicked(self) -> None:
        if self._busy() and getattr(self._task, "kind", "") == "sync":
            self._task.cancel()
            self._say("Cancelling…")
            return
        self.sync_now(manual=True)

    def _tab_selection(self) -> set[str] | None:
        tabs = self.cfg.get(_K_TABS) or {}
        sel = tabs.get(self.league) if isinstance(tabs, dict) else None
        return set(sel) if isinstance(sel, list) else None

    def sync_now(self, manual: bool = True) -> bool:
        if not self.svc.connected or not self.league or self._busy():
            return False
        now = time.time()
        if manual and now - self._last_attempt < MANUAL_COOLDOWN_SEC:
            self._say(f"Just synced; wait "
                      f"{int(MANUAL_COOLDOWN_SEC - (now - self._last_attempt))} s.")
            return False
        self._last_attempt = now
        league, realm, tabs = self.league, self.realm, self._tab_selection()

        def work(progress, cancelled):
            return self.svc.sync(league, realm, tabs, progress, cancelled)

        ok = self._run(work, self._on_sync_done)
        if ok:
            self._task.kind = "sync"
            self._update_buttons()
        return ok

    def _on_sync_done(self, res) -> None:
        self._last_failed = False
        extra = f", {len(res.skipped_tabs)} tabs skipped" if res.skipped_tabs else ""
        div = (f"{res.total_chaos / res.chaos_per_divine:,.1f} div"
               if res.chaos_per_divine else f"{res.total_chaos:,.0f} c")
        self._say(f"Synced {res.tabs} tabs, {res.items} priced items "
                  f"({res.unpriced} unpriced) = {div} in {res.seconds:.0f} s{extra}.")
        self.refresh()

    def _tick(self) -> None:
        """Every 30 s: run the automatic sync when it's due, and keep the
        "last hour" style ranges sliding."""
        if self._shut:
            return
        self._refresh_if_moved()
        if not (self.auto_cb.isChecked() and self.svc.connected and self.league):
            return
        if self._busy():
            return
        now = time.time()
        if self._last_failed and now - self._last_attempt < RETRY_AFTER_FAIL_SEC:
            return
        last = self.svc.store.latest(self.account, self.league)
        interval = clamp_sync_interval(self.interval_box.currentData()) * 60
        if last is None or now - last.taken_at >= interval - 30:
            self.sync_now(manual=False)

    def next_sync_at(self) -> float | None:
        if not (self.auto_cb.isChecked() and self.svc.connected):
            return None
        last = self.svc.store.latest(self.account, self.league)
        if last is None:
            return time.time()
        return last.taken_at + clamp_sync_interval(self.interval_box.currentData()) * 60

    # ============================================================== view
    def range_bounds(self) -> tuple[float | None, float]:
        key = self.range_box.currentData()
        now = time.time()
        if key == "custom":
            a = float(self.from_edit.dateTime().toSecsSinceEpoch())
            b = float(self.to_edit.dateTime().toSecsSinceEpoch())
            return (min(a, b), max(a, b))
        hours = preset_hours(key)
        return (now - hours * 3600 if hours else None, now)

    def refresh(self) -> None:
        start, end = self.range_bounds()
        rate = self.rate_spin.value() or None
        r = compute_range(self.svc.store, self.account, self.league, start, end,
                          chaos_per_divine=rate)
        self._range = r
        self._show_cards(r)
        self._show_chart(r)
        self._fill_table()
        reading = r.reading()
        self.overlay.show_reading(reading)

    def _refresh_if_moved(self) -> None:
        """Cheap periodic update: a full refresh (which rebuilds the item
        table and loses its scroll position) only when the range now
        compares different snapshots."""
        start, end = self.range_bounds()
        r = compute_range(self.svc.store, self.account, self.league, start, end,
                          chaos_per_divine=self.rate_spin.value() or None)
        ids = lambda x: (x.start.id if x and x.start else None,  # noqa: E731
                         x.end.id if x and x.end else None)
        if ids(r) != ids(self._range):
            self.refresh()
        else:
            self._range = r
            self._show_cards(r)

    def _div(self, chaos: float | None, r: RangeResult) -> str:
        if chaos is None:
            return "—"
        d = r.to_div(chaos)
        return f"{d:,.2f} div" if d is not None else f"{chaos:,.0f} c"

    def _show_cards(self, r: RangeResult) -> None:
        self._show_cards_raw(r)
        for c in (self.worth_card, self.change_card, self.sync_card):
            c.sub.setText(capitalise(c.sub.text()))
        self.detail_label.setText(capitalise(self.detail_label.text()))
        self.range_label.setText(capitalise(self.range_label.text()))

    def _show_cards_raw(self, r: RangeResult) -> None:
        from . import styles as S
        end = r.end
        if end:
            sub = f"≈ {end.total_chaos:,.0f} c"
            if r.chaos_per_divine:
                sub += f" · 1 div = {r.chaos_per_divine:,.0f} c"
            self.worth_card.set(self._div(end.total_chaos, r), sub)
        else:
            self.worth_card.set("—", "No syncs yet.")
        if r.ok:
            dc = r.delta_chaos
            d = r.to_div(dc)
            val = (f"{_signed(d)} div" if d is not None else f"{_signed(dc, 0)} c")
            pct = r.delta_pct
            sub = f"{_signed(dc, 0)} c" + (f" · {_signed(pct, 1)} %" if pct is not None else "")
            sub += f" over {r.hours:.1f} h"
            self.change_card.set(val, sub, S.SUCCESS if dc > 0 else
                                 S.DANGER if dc < 0 else "")
            cph = r.chaos_per_hour
            dph = r.to_div(cph)
            self.reading_label.setText(f"{dph:,.2f} div/h" if dph is not None
                                       else f"{cph:,.0f} c/h")
            self.detail_label.setText(f"≈ {cph:,.0f} c/h · "
                                      f"{datetime.fromtimestamp(r.start.taken_at):%d %b %H:%M}"
                                      f" → {datetime.fromtimestamp(r.end.taken_at):%d %b %H:%M}")
        else:
            self.change_card.set("—", r.message, "")
            self.reading_label.setText("— div/h")
            self.detail_label.setText(r.message)
        latest = self.svc.store.latest(self.account, self.league)
        if latest:
            nxt = self.next_sync_at()
            sub = datetime.fromtimestamp(latest.taken_at).strftime("%a %d %b %H:%M")
            if nxt:
                mins = max(0, int((nxt - time.time()) / 60))
                sub += f" · next in {mins} min" if mins else " · next: now"
            elif self.svc.connected:
                sub += " · automatic sync off"
            if latest.source == "csv":
                sub += " · CSV import"
            self.sync_card.set(capitalise(_ago(latest.taken_at)), sub)
        else:
            self.sync_card.set("Never", "Connect and press Sync now."
                               if not self.svc.connected else "Press Sync now.")
        if r.start and r.end:
            self.range_label.setText(
                f"{len(r.series)} snapshots · comparing "
                f"{datetime.fromtimestamp(r.start.taken_at):%d %b %H:%M} with "
                f"{datetime.fromtimestamp(r.end.taken_at):%d %b %H:%M}")
        else:
            self.range_label.setText(r.message)

    def _show_chart(self, r: RangeResult) -> None:
        mode = "hourly" if self.hourly_btn.isChecked() else "total"
        rate = r.chaos_per_divine
        unit = "div" if rate else "c"
        conv = (lambda c: c / rate) if rate else (lambda c: c)
        if mode == "hourly":
            pts = [(t, conv(v)) for t, v in hourly_series(r.series)]
        else:
            pts = [(s.taken_at, conv(s.total_chaos)) for s in r.series]
        self.chart.set_data(pts, mode=mode, unit=unit,
                            empty=r.message or "No syncs in this range yet.")

    def _fill_table(self, *_a) -> None:
        from . import styles as S
        r = self._range
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        if not r or not r.end:
            self.items_note.setText("")
            self.table.setSortingEnabled(True)
            return
        start = r.start if r.ok else r.end
        changes = item_changes(self.svc.store, start, r.end)
        needle = self.search_edit.text().strip().lower()
        only_changed = self.changed_cb.isChecked()
        rate = r.chaos_per_divine
        shown = 0
        for c in changes:
            if needle and needle not in c.name.lower() and needle not in c.tabs.lower():
                continue
            if only_changed and abs(c.qty_delta) < 1e-9 and abs(c.value_delta) < 0.5:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = QTableWidgetItem(c.name)
            name.setToolTip(c.category)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(c.tabs))
            self.table.setItem(row, 2, _NumItem(f"{c.qty_end:,.0f}", c.qty_end))
            self.table.setItem(row, 3, _NumItem(f"{c.unit_end:,.1f}", c.unit_end))
            tot = (f"{c.value_end / rate:,.2f} div" if rate and c.value_end >= rate
                   else f"{c.value_end:,.0f} c")
            self.table.setItem(row, 4, _NumItem(tot, c.value_end))
            dq = _NumItem(_signed(c.qty_delta, 0) if c.qty_delta else "", c.qty_delta)
            dv_txt = ""
            if abs(c.value_delta) >= 0.5:
                dv_txt = (f"{_signed(c.value_delta / rate)} div"
                          if rate and abs(c.value_delta) >= rate
                          else f"{_signed(c.value_delta, 0)} c")
            dv = _NumItem(dv_txt, c.value_delta)
            for it, val in ((dq, c.qty_delta), (dv, c.value_delta)):
                if val:
                    it.setForeground(QColor(S.SUCCESS if val > 0 else S.DANGER))
            self.table.setItem(row, 5, dq)
            self.table.setItem(row, 6, dv)
            shown += 1
        self.table.setSortingEnabled(True)
        end = r.end
        note = f"{shown} of {len(changes)} items"
        if end.unpriced_count:
            note += f" · {end.unpriced_count} unpriced items not counted"
        if end.note:
            note += f" · {end.note}"
        self.items_note.setText(capitalise(note))

    def overlay_headline(self) -> str:
        return self.overlay.headline_text()

    # ========================================================== settings
    def _on_league_changed(self, _league: str) -> None:
        self.refresh()          # LeagueBox saves the choice itself

    def _on_realm_changed(self, *_a) -> None:
        self.cfg.set(_K_REALM, self.realm)
        self._persist(_K_REALM)

    def _sync_custom_visible(self) -> None:
        custom = self.range_box.currentData() == "custom"
        self.from_edit.setVisible(custom)
        self.to_edit.setVisible(custom)

    def _on_range_changed(self, *_a) -> None:
        self.cfg.set(_K_RANGE, self.range_box.currentData())
        self._persist(_K_RANGE)
        self._sync_custom_visible()
        self.refresh()

    def _on_custom_changed(self, *_a) -> None:
        self.cfg.set(_K_CUSTOM, [self.from_edit.dateTime().toSecsSinceEpoch(),
                                 self.to_edit.dateTime().toSecsSinceEpoch()])
        self._persist(_K_CUSTOM)
        if self.range_box.currentData() == "custom":
            self.refresh()

    def _on_chart_mode(self, btn) -> None:
        self.cfg.set(_K_CHART, btn.property("chart"))
        self._persist(_K_CHART)
        if self._range:
            self._show_chart(self._range)

    def _on_auto_toggled(self, on: bool) -> None:
        self.cfg.set(_K_AUTO, on)
        self._persist(_K_AUTO)
        self.refresh()

    def _on_interval_changed(self, *_a) -> None:
        self.cfg.set(_K_INTERVAL, clamp_sync_interval(self.interval_box.currentData()))
        self._persist(_K_INTERVAL)
        self.refresh()

    def _on_rate_changed(self, value: float) -> None:
        self.cfg.set(_K_RATE, value)
        self._persist(_K_RATE)
        self.refresh()

    def _on_client_edited(self) -> None:
        cid = self.client_edit.text().strip()
        if cid == self.svc.client_id:
            return
        self.cfg.set(_K_CLIENT, cid or None)
        self._persist(_K_CLIENT)
        self.svc.set_client_id(cid)
        self._update_account()

    def _on_tabs_clicked(self) -> None:
        league, realm = self.league, self.realm
        self._say("Loading your stash tabs…")

        def done(tabs):
            self._say("")
            dlg = TabPickerDialog(tabs, self._tab_selection(), self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                all_tabs = dict(self.cfg.get(_K_TABS) or {})
                all_tabs[league] = dlg.selection()
                self.cfg.set(_K_TABS, all_tabs)
                self._persist(_K_TABS)

        self._run(lambda _p, _c: self.svc.list_tabs(league, realm), done)

    def _import_csv(self) -> None:
        from ..economy.stash_sync import csv_to_snapshot
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Wealthy Exile CSV exports", "", "CSV files (*.csv)")
        n = 0
        for p in paths:
            try:
                self.svc.store.add(csv_to_snapshot(p, account=self.account,
                                                   league=self.league))
                n += 1
            except Exception as e:  # noqa: BLE001
                self._say(f"{Path(p).name}: {e}", error=True)
        if n:
            self._say(f"Imported {n} export(s) into {self.league}.")
            self.refresh()

    def _delete_history(self) -> None:
        if QMessageBox.question(
                self, "Delete History",
                f"Delete every saved snapshot for {self.account} in "
                f"{self.league}? This can't be undone.") != QMessageBox.StandardButton.Yes:
            return
        n = self.svc.store.delete_history(self.account, self.league)
        self._say(f"Deleted {n} snapshots.")
        self.refresh()

    # =========================================================== overlay
    def _on_overlay_toggled(self, on: bool) -> None:
        self.cfg.set(_K_VISIBLE, on)
        self._persist(_K_VISIBLE)
        if on:
            pos = self.cfg.get(_K_POS)
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                self.overlay.move(QPoint(int(pos[0]), int(pos[1])))
            self.overlay.show()
            self.overlay.raise_()
        else:
            self.overlay.hide()

    def _on_overlay_moved(self, pos: QPoint) -> None:
        self.cfg.set(_K_POS, [pos.x(), pos.y()])
        self._persist(_K_POS)

    def shutdown(self) -> None:
        self._shut = True                     # pending single-shots do nothing
        self._timer.stop()
        if self._login is not None:
            self._login.receiver.close()
        if self._task is not None:
            self._task.cancel()
            self._task.wait(3000)
        self.overlay.close()
        self.svc.close()
