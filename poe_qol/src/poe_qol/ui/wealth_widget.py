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
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox,
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
    def _build(self) -> None:
        v = QVBoxLayout(self)
        intro = QLabel(
            "Shows your divine-per-hour from Wealthy Exile CSV exports. On "
            "wealthyexile.com press <b>Sync stash</b>, then <b>⋯ → Export "
            "CSV</b>, and save the file into the folder below. Each new "
            "export is compared with the previous one.")
        intro.setWordWrap(True)
        v.addWidget(intro)

        form = QFormLayout()
        row = QHBoxLayout()
        self.dir_edit = QLineEdit(self.cfg.get(_K_DIR) or "")
        self.dir_edit.setPlaceholderText("Folder you save exports to")
        self.dir_edit.editingFinished.connect(self._on_dir_edited)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.dir_edit, 1)
        row.addWidget(browse)
        form.addRow("Exports folder:", row)

        self.unit_box = QComboBox()
        for unit, label in (("chaos", "Chaos"), ("divine", "Divine")):
            self.unit_box.addItem(label, unit)
        i = self.unit_box.findData(self.cfg.get(_K_UNIT, "chaos"))
        self.unit_box.setCurrentIndex(max(0, i))
        self.unit_box.currentIndexChanged.connect(self._on_settings_changed)
        form.addRow("CSV values are in:", self.unit_box)

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0, 100000)
        self.rate_spin.setDecimals(1)
        self.rate_spin.setSpecialValueText("unknown")
        self.rate_spin.setValue(float(self.cfg.get(_K_RATE, 0) or 0))
        self.rate_spin.valueChanged.connect(self._on_settings_changed)
        form.addRow("Chaos per divine:", self.rate_spin)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(MIN_INTERVAL_MINUTES, 24 * 60)
        self.interval_spin.setSuffix(" min")
        self.interval_spin.setValue(
            clamp_interval_minutes(self.cfg.get(_K_INTERVAL, MIN_INTERVAL_MINUTES)))
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        form.addRow("Re-check every:", self.interval_spin)
        v.addLayout(form)

        actions = QHBoxLayout()
        self.overlay_cb = QCheckBox("Show overlay over the game")
        self.overlay_cb.toggled.connect(self._on_overlay_toggled)
        refresh = QPushButton("Refresh now")
        refresh.clicked.connect(self.refresh)
        open_we = QPushButton("Open Wealthy Exile")
        open_we.clicked.connect(lambda: webbrowser.open(WEALTHY_EXILE_STASH_URL))
        actions.addWidget(self.overlay_cb)
        actions.addStretch(1)
        actions.addWidget(open_we)
        actions.addWidget(refresh)
        v.addLayout(actions)

        self.reading_label = QLabel("—")
        self.reading_label.setProperty("role", "section")
        v.addWidget(self.reading_label)
        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        v.addWidget(self.detail_label)

        v.addWidget(QLabel("Exports found (oldest first):"))
        self.snap_list = QListWidget()
        v.addWidget(self.snap_list, 1)

        note = QLabel(
            "Reads only CSV files in this folder. Sends nothing and never "
            "logs into Wealthy Exile. Overlay needs PoE in windowed or "
            "windowed-fullscreen mode.")
        note.setWordWrap(True)
        note.setProperty("role", "caption")
        v.addWidget(note)

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
            extra = f", {s.skipped} rows skipped" if s.skipped else ""
            self.snap_list.addItem(
                f"{s.taken_at:%Y-%m-%d %H:%M}  ·  {s.total:,.1f} {unit}  ·  "
                f"{s.rows} rows{extra}  ·  {s.path.name}")

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
