"""Wealth tab: divine-per-hour from Wealthy Exile CSV exports + overlay.

Workflow: on wealthyexile.com press Sync stash, then Export CSV, and
save the file into the folder chosen here. Every `interval_minutes`
(minimum 5) this tab re-reads the folder and compares the two newest
exports. Nothing is sent anywhere; Wealthy Exile is never contacted.
"""
from __future__ import annotations

import webbrowser
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog,
    QHBoxLayout, QLineEdit, QListWidget, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore
from ..economy.wealth_rate import (
    MIN_INTERVAL_MINUTES, CsvFolderSource, RateReading, clamp_interval_minutes,
)
from .wealth_overlay import WealthOverlay

WEALTHY_EXILE_STASH_URL = "https://wealthyexile.com/stash"

_K_DIR = "wealth.exports_dir"
_K_UNIT = "wealth.assumed_unit"
_K_RATE = "wealth.chaos_per_divine"
_K_INTERVAL = "wealth.interval_minutes"
_K_VISIBLE = "wealth.overlay_visible"
_K_POS = "wealth.overlay_pos"


class WealthWidget(QWidget):
    def __init__(self, cfg: ConfigStore) -> None:
        super().__init__()
        self.cfg = cfg
        self.overlay = WealthOverlay()
        self.overlay.refresh_requested.connect(self.refresh)
        self.overlay.hide_requested.connect(lambda: self.overlay_cb.setChecked(False))
        self.overlay.moved.connect(self._on_overlay_moved)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._build()
        self._apply_interval()
        self.refresh()
        if self.cfg.get(_K_VISIBLE, False):
            self.overlay_cb.setChecked(True)

    # ---- construction ----
    def header_actions(self) -> list[QWidget]:
        return [self.open_we_btn, self.refresh_btn]

    def _build(self) -> None:
        from . import styles as S
        from .components import StatCard, Switch, card, field, with_help
        from .icons import icon

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(18)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("role", "primary")
        self.refresh_btn.setIcon(icon("refresh", "#1A1200"))
        self.refresh_btn.setToolTip("Re-read the exports folder now.")
        self.refresh_btn.clicked.connect(self.refresh)
        self.open_we_btn = QPushButton("Wealthy Exile")
        self.open_we_btn.setIcon(icon("external", S.FG_1))
        self.open_we_btn.setToolTip("Open wealthyexile.com/stash in your browser.")
        self.open_we_btn.clicked.connect(
            lambda: webbrowser.open(WEALTHY_EXILE_STASH_URL))

        # ---- hero ----
        top = QHBoxLayout()
        top.setSpacing(18)
        self.rate_card = StatCard("Divine Per Hour", "—", hero=True, help=(
            "Compares your two newest exports: how much your stash grew, "
            "divided by the time between them."), icon="wealth",
            accent=S.ACCENT)
        self.reading_label = self.rate_card.value
        self.detail_label = self.rate_card.sub
        self.detail_label.setVisible(True)
        top.addWidget(self.rate_card, 2)

        oc, ol = card("Overlay", icon="eye")
        self.overlay_cb = Switch("Show In Game", big=True)
        self.overlay_cb.toggled.connect(self._on_overlay_toggled)
        ol.addWidget(with_help(self.overlay_cb, (
            "A small always-on-top box over the game. Drag to move, "
            "right-click for options. Needs windowed or "
            "windowed-fullscreen.")))
        ol.addStretch(1)
        top.addWidget(oc, 1)
        v.addLayout(top)

        # ---- settings ----
        sc, sl = card("Setup", (
            "1. On wealthyexile.com press <b>Sync stash</b>.<br>"
            "2. Open <b>⋯ → Export CSV</b> and save into your exports "
            "folder.<br>3. Repeat later; each new export is compared with "
            "the one before.<br><br>Only reads CSV files in that folder. "
            "Never logs into Wealthy Exile."), icon="folder")
        frow = QHBoxLayout()
        self.dir_edit = QLineEdit(self.cfg.get(_K_DIR) or "")
        self.dir_edit.setPlaceholderText("Choose The Folder You Save Exports To")
        self.dir_edit.editingFinished.connect(self._on_dir_edited)
        browse = QPushButton("Browse…")
        browse.setIcon(icon("folder", S.FG_1))
        browse.clicked.connect(self._browse)
        frow.addWidget(self.dir_edit, 1)
        frow.addWidget(browse)
        fw = QWidget(); fw.setLayout(frow)
        sl.addWidget(field("Exports Folder", fw))

        grid = QHBoxLayout()
        grid.setSpacing(18)
        self.unit_box = QComboBox()
        for unit, label in (("chaos", "Chaos"), ("divine", "Divine")):
            self.unit_box.addItem(label, unit)
        i = self.unit_box.findData(self.cfg.get(_K_UNIT, "chaos"))
        self.unit_box.setCurrentIndex(max(0, i))
        self.unit_box.currentIndexChanged.connect(self._on_settings_changed)
        grid.addWidget(field("CSV Values In", self.unit_box,
                             "The currency your export's totals are in."), 1)

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0, 100000)
        self.rate_spin.setDecimals(1)
        self.rate_spin.setSpecialValueText("Auto")
        self.rate_spin.setValue(float(self.cfg.get(_K_RATE, 0) or 0))
        self.rate_spin.valueChanged.connect(self._on_settings_changed)
        grid.addWidget(field("Chaos Per Divine", self.rate_spin,
                             "<b>Auto</b> uses the Divine Orb price in your "
                             "newest export. Type a number to override."), 1)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(MIN_INTERVAL_MINUTES, 24 * 60)
        self.interval_spin.setSuffix(" Min")
        self.interval_spin.setValue(
            clamp_interval_minutes(self.cfg.get(_K_INTERVAL, MIN_INTERVAL_MINUTES)))
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        grid.addWidget(field("Check Every", self.interval_spin,
                             f"How often to re-read the folder "
                             f"(at least {MIN_INTERVAL_MINUTES} min)."), 1)
        sl.addLayout(grid)
        v.addWidget(sc)

        # ---- exports ----
        ec, el = card("Exports", "Every export found, oldest first.",
                      icon="clipboard")
        self.snap_list = QListWidget()
        self.snap_list.setMinimumHeight(120)
        el.addWidget(self.snap_list, 1)
        v.addWidget(ec, 1)

    # ---- data ----
    def _source(self) -> CsvFolderSource:
        rate = self.rate_spin.value()
        return CsvFolderSource(self.dir_edit.text().strip() or None,
                               chaos_per_divine=rate or None,
                               assumed_unit=self.unit_box.currentData())

    def refresh(self) -> None:
        src = self._source()
        reading = src.read()
        self.overlay.show_reading(reading)
        self._show_reading(reading)
        self.snap_list.clear()
        for s in src.snapshots():
            unit = s.unit if s.unit != "unknown" else self.unit_box.currentData()
            extra = f", {s.skipped} Rows Skipped" if s.skipped else ""
            if s.divine_price:
                extra += f", 1 div = {s.divine_price:,.0f}c"
            self.snap_list.addItem(
                f"{s.taken_at:%Y-%m-%d %H:%M}  ·  {s.total:,.1f} "
                f"{str(unit).capitalize()}  ·  {s.rows} Rows{extra}  ·  "
                f"{s.path.name}")

    def _show_reading(self, r: RateReading) -> None:
        self.reading_label.setText(self.overlay.headline_text())
        self.detail_label.setText(self.overlay.detail_text())

    def overlay_headline(self) -> str:
        return self.overlay.headline_text()

    # ---- settings ----
    def _persist(self, *keys: str) -> None:
        try:
            self.cfg.save_user_overrides(list(keys))
        except Exception:
            pass

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Folder with Wealthy Exile exports", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)
            self._on_dir_edited()

    def _on_dir_edited(self) -> None:
        text = self.dir_edit.text().strip()
        self.cfg.set(_K_DIR, str(Path(text)) if text else None)
        self._persist(_K_DIR)
        self.refresh()

    def _on_settings_changed(self, *_a) -> None:
        self.cfg.set(_K_UNIT, self.unit_box.currentData())
        self.cfg.set(_K_RATE, self.rate_spin.value())
        self._persist(_K_UNIT, _K_RATE)
        self.refresh()

    def _on_interval_changed(self, value: int) -> None:
        self.cfg.set(_K_INTERVAL, clamp_interval_minutes(value))
        self._persist(_K_INTERVAL)
        self._apply_interval()

    def _apply_interval(self) -> None:
        minutes = clamp_interval_minutes(self.interval_spin.value())
        self._timer.start(minutes * 60_000)

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
        self._timer.stop()
        self.overlay.close()
