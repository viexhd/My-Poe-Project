"""Area Select tab: settings for the Alt+drag inventory selection.

Every change is written to config/user.yaml immediately and pushed to
the running controller (if any) with ``reload_settings()``.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QRadioButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ..area_select.grid import load_geometry
from ..area_select.settings import AreaSelectSettings, OverlaySettings

MODIFIERS = ("alt", "ctrl+alt", "alt+shift")
GRIDS = (("macros.inventory_dump", "Inventory"),
         ("macros.map_stash_dump", "Map stash tab"))

EXPERIMENTAL_WARNING = (
    "Experimental transfer Ctrl-clicks every selected slot for you after "
    "one Alt+drag.\n\n"
    "That is many game actions from one input. Grinding Gear Games' rules "
    "for third-party tools allow one action per key press, so this mode is "
    "NOT compliant and could get your account actioned. It is meant for "
    "personal experimentation only.\n\n"
    "Press F12 or Esc, move the mouse, or switch windows to stop a run.\n\n"
    "Enable experimental transfer anyway?")


class AreaSelectWidget(QWidget):
    def __init__(self, cfg: Any, controller: Optional[Any] = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.controller = controller
        self._loading = True
        self._build()
        self._load()
        self._loading = False
        if controller is not None:
            controller.status_changed.connect(self.status.setText)

    # ---- construction ----
    def _build(self) -> None:
        v = QVBoxLayout(self)

        intro = QLabel(
            "Hold <b>Alt</b> and drag across the inventory to select slots, "
            "like selecting files on the desktop. Esc cancels. The drag "
            "only starts inside the calibrated grid, so Alt+clicking loot "
            "elsewhere still reaches the game.")
        intro.setWordWrap(True)
        v.addWidget(intro)

        self.enabled_cb = QCheckBox("Enable Alt+drag area selection")
        v.addWidget(self.enabled_cb)

        sel = QGroupBox("Selection")
        f = QFormLayout(sel)
        self.modifier = QComboBox()
        self.modifier.addItems(MODIFIERS)
        f.addRow("Hold while dragging:", self.modifier)
        grids_row = QHBoxLayout()
        self.grid_cbs: dict[str, QCheckBox] = {}
        for ns, label in GRIDS:
            cb = QCheckBox(label)
            self.grid_cbs[ns] = cb
            grids_row.addWidget(cb)
        f.addRow("Works on:", grids_row)
        dims = QHBoxLayout()
        self.cols = QSpinBox(); self.cols.setRange(1, 24)
        self.rows = QSpinBox(); self.rows.setRange(1, 24)
        dims.addWidget(self.cols); dims.addWidget(QLabel("columns ×"))
        dims.addWidget(self.rows); dims.addWidget(QLabel("rows")); dims.addStretch(1)
        f.addRow("Inventory grid:", dims)
        self.bounds_label = QLabel()
        self.bounds_label.setProperty("role", "caption")
        self.bounds_label.setWordWrap(True)
        f.addRow("Screen bounds:", self.bounds_label)
        self.detect_cb = QCheckBox("Detect empty / occupied slots (screen capture)")
        self.skip_empty_cb = QCheckBox("Leave empty slots out of the selection")
        f.addRow(self.detect_cb)
        f.addRow(self.skip_empty_cb)
        v.addWidget(sel)

        ov = QGroupBox("Overlay")
        f = QFormLayout(ov)
        self.overlay_cb = QCheckBox("Show selection overlay")
        f.addRow(self.overlay_cb)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        f.addRow("Rectangle opacity:", self.opacity)
        self.border = QSpinBox(); self.border.setRange(1, 10); self.border.setSuffix(" px")
        f.addRow("Border thickness:", self.border)
        self.debug_cb = QCheckBox("Debug mode (draw grid bounds, log slot details)")
        f.addRow(self.debug_cb)
        v.addWidget(ov)

        tr = QGroupBox("Transfer")
        tv = QVBoxLayout(tr)
        self.mode_manual = QRadioButton(
            "Manual (recommended): highlight the slots, you Ctrl-click each one")
        self.mode_exp = QRadioButton(
            "Experimental: Ctrl-click every selected slot for me (NOT GGG-compliant)")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.mode_manual)
        self._mode_group.addButton(self.mode_exp)
        tv.addWidget(self.mode_manual)
        tv.addWidget(self.mode_exp)
        ef = QFormLayout()
        self.delay = QSpinBox(); self.delay.setRange(20, 2000); self.delay.setSuffix(" ms")
        self.max_slots = QSpinBox(); self.max_slots.setRange(1, 200)
        ef.addRow("Delay between clicks:", self.delay)
        ef.addRow("Max slots per drag:", self.max_slots)
        tv.addLayout(ef)
        self.exp_warning = QLabel(
            "⚠ Experimental transfer breaks GGG's one-action-per-key-press "
            "rule. Use at your own risk. F12 / Esc / moving the mouse stops it.")
        self.exp_warning.setWordWrap(True)
        self.exp_warning.setStyleSheet("color:#E5484D; font-weight:600;")
        tv.addWidget(self.exp_warning)
        v.addWidget(tr)

        self.status = QLabel("")
        self.status.setProperty("role", "caption")
        v.addWidget(self.status)
        v.addStretch(1)

        for w in (self.enabled_cb, self.detect_cb, self.skip_empty_cb,
                  self.overlay_cb, self.debug_cb, *self.grid_cbs.values()):
            w.toggled.connect(self._save)
        self.modifier.currentTextChanged.connect(self._save)
        self.opacity.valueChanged.connect(self._save)
        for sb in (self.border, self.delay, self.max_slots):
            sb.valueChanged.connect(self._save)
        self.cols.valueChanged.connect(self._save_grid)
        self.rows.valueChanged.connect(self._save_grid)
        self.mode_exp.toggled.connect(self._on_mode_toggled)

    # ---- load / save ----
    def _load(self) -> None:
        s = AreaSelectSettings.load(self.cfg)
        self.enabled_cb.setChecked(s.enabled)
        self.modifier.setCurrentText(s.modifier if s.modifier in MODIFIERS else "alt")
        for ns, cb in self.grid_cbs.items():
            cb.setChecked(ns in s.grids)
        self.cols.setValue(int(self.cfg.get("macros.inventory_dump.grid.cols", 12)))
        self.rows.setValue(int(self.cfg.get("macros.inventory_dump.grid.rows", 5)))
        self.detect_cb.setChecked(s.detect_items)
        self.skip_empty_cb.setChecked(s.skip_empty)
        self.overlay_cb.setChecked(s.overlay.visible)
        self.opacity.setValue(int(round(s.overlay.fill_opacity * 100)))
        self.border.setValue(s.overlay.border_px)
        self.debug_cb.setChecked(s.debug)
        self.delay.setValue(s.experimental.click_delay_ms)
        self.max_slots.setValue(s.experimental.max_slots)
        exp = s.effective_mode == "experimental"
        (self.mode_exp if exp else self.mode_manual).setChecked(True)
        self._refresh_experimental(exp)
        self._refresh_bounds()

    def _current(self) -> AreaSelectSettings:
        s = AreaSelectSettings.load(self.cfg)
        grids = tuple(ns for ns, cb in self.grid_cbs.items() if cb.isChecked()) \
            or ("macros.inventory_dump",)
        return s.replace(
            enabled=self.enabled_cb.isChecked(),
            modifier=self.modifier.currentText(),
            grids=grids,
            detect_items=self.detect_cb.isChecked(),
            skip_empty=self.skip_empty_cb.isChecked(),
            debug=self.debug_cb.isChecked(),
            transfer_mode="experimental" if self.mode_exp.isChecked() else "manual",
            overlay=OverlaySettings(
                visible=self.overlay_cb.isChecked(),
                fill_opacity=self.opacity.value() / 100,
                border_px=self.border.value()),
            experimental=replace(s.experimental,
                                 click_delay_ms=self.delay.value(),
                                 max_slots=self.max_slots.value()),
        )

    def _save(self, *_a) -> None:
        if self._loading:
            return
        self._current().save(self.cfg)
        self._notify()

    def _save_grid(self, *_a) -> None:
        if self._loading:
            return
        self.cfg.set("macros.inventory_dump.grid.cols", self.cols.value())
        self.cfg.set("macros.inventory_dump.grid.rows", self.rows.value())
        self.cfg.save_user_overrides(["macros.inventory_dump.grid.cols",
                                      "macros.inventory_dump.grid.rows"])
        self._refresh_bounds()
        self._notify()

    def _notify(self) -> None:
        if self.controller is not None:
            self.controller.reload_settings()

    # ---- experimental mode ----
    def _on_mode_toggled(self, exp: bool) -> None:
        if self._loading:
            return
        if exp and not AreaSelectSettings.load(self.cfg).experimental.acknowledged:
            ok = QMessageBox.warning(
                self, "Experimental transfer", EXPERIMENTAL_WARNING,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ok != QMessageBox.StandardButton.Yes:
                self._loading = True
                self.mode_manual.setChecked(True)
                self._loading = False
                return
            s = self._current()
            s = s.replace(experimental=replace(s.experimental, acknowledged=True))
            s.save(self.cfg)
            self._notify()
        else:
            self._save()
        self._refresh_experimental(exp)

    def _refresh_experimental(self, exp: bool) -> None:
        for w in (self.delay, self.max_slots):
            w.setEnabled(exp)
        self.exp_warning.setVisible(exp)

    def _refresh_bounds(self) -> None:
        try:
            b = load_geometry(self.cfg, "macros.inventory_dump").bounds()
            self.bounds_label.setText(
                f"{b.left:.0f}, {b.top:.0f} → {b.right:.0f}, {b.bottom:.0f}  "
                "(set with Calibrate… on the Inventory tab, or "
                "grid.bounds in user.yaml)")
        except Exception as e:
            self.bounds_label.setText(f"not calibrated ({e})")
