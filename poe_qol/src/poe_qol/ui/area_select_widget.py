"""Area Select tab: settings for the Alt+drag inventory selection.

Every change is written to config/user.yaml immediately and pushed to
the running controller (if any) with ``reload_settings()``.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
    QLabel, QMessageBox, QRadioButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ..area_select.grid import load_geometry
from ..area_select.settings import AreaSelectSettings, OverlaySettings

MODIFIERS = ("alt", "ctrl+alt", "alt+shift")
_MODIFIER_LABELS = {"alt": "Alt", "ctrl+alt": "Ctrl+Alt", "alt+shift": "Alt+Shift"}
GRIDS = (("macros.inventory_dump", "Inventory"),
         ("macros.map_stash_dump", "Map Stash Tab"))

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
            controller.status_changed.connect(self._set_status)

    def _set_status(self, text: str) -> None:
        from .text import capitalise
        text = capitalise(text)
        self.status.setText(text)
        self.status.setVisible(bool(text))

    # ---- construction ----
    def _build(self) -> None:
        from .components import Switch, caption, card, field, with_help

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(18)

        # ---- hero: on/off ----
        hero, hv = card(variant="gilt")
        self.enabled_cb = Switch("Alt + Drag Selection", big=True)
        hv.addWidget(with_help(self.enabled_cb, (
            "Hold <b>Alt</b> and drag across the inventory to select "
            "slots. <b>Esc</b> cancels. Only starts inside the calibrated "
            "grid, so Alt-clicking loot elsewhere still reaches the game.")))
        self.status = caption("")
        self.status.setVisible(False)
        hv.addWidget(self.status)
        v.addWidget(hero)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(18)

        # ---- selection ----
        sel, f = card("Selection", icon="select")
        self.modifier = QComboBox()
        for m in MODIFIERS:
            self.modifier.addItem(_MODIFIER_LABELS[m], m)
        f.addWidget(field("Hold While Dragging", self.modifier,
                          "The key(s) you hold while dragging."))
        grids_row = QHBoxLayout()
        grids_row.setSpacing(18)
        self.grid_cbs: dict[str, QCheckBox] = {}
        for ns, label in GRIDS:
            cb = Switch(label)
            self.grid_cbs[ns] = cb
            grids_row.addWidget(cb)
        grids_row.addStretch(1)
        gw = QWidget(); gw.setLayout(grids_row)
        f.addWidget(field("Works On", gw,
                          "Which grids the drag can select in."))
        dims = QHBoxLayout()
        self.cols = QSpinBox(); self.cols.setRange(1, 24)
        self.rows = QSpinBox(); self.rows.setRange(1, 24)
        self.cols.setSuffix(" Cols"); self.rows.setSuffix(" Rows")
        dims.addWidget(self.cols); dims.addWidget(QLabel("×"))
        dims.addWidget(self.rows); dims.addStretch(1)
        dw = QWidget(); dw.setLayout(dims)
        self.bounds_label = caption("")
        f.addWidget(field("Inventory Grid", dw,
                          "Columns × rows of your inventory. Screen "
                          "position comes from <b>Calibrate…</b> on the "
                          "Inventory page."))
        f.addWidget(self.bounds_label)
        self.detect_cb = Switch("Spot Empty Slots")
        f.addWidget(with_help(self.detect_cb,
                              "Looks at the screen to tell empty slots "
                              "from occupied ones. Read-only screen capture."))
        self.skip_empty_cb = Switch("Skip Empty Slots")
        f.addWidget(with_help(self.skip_empty_cb,
                              "Leaves empty slots out of the selection."))
        f.addStretch(1)
        grid.addWidget(sel, 0, 0)

        # ---- overlay ----
        ov, f = card("Overlay", icon="eye")
        self.overlay_cb = Switch("Show Selection Box")
        f.addWidget(with_help(self.overlay_cb,
                              "Draws the drag rectangle and slot marks "
                              "over the game while you drag."))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        f.addWidget(field("Box Opacity", self.opacity))
        self.border = QSpinBox(); self.border.setRange(1, 10); self.border.setSuffix(" px")
        f.addWidget(field("Border", self.border))
        self.debug_cb = Switch("Debug")
        f.addWidget(with_help(self.debug_cb,
                              "Draws the grid bounds and logs slot details. "
                              "For lining things up."))
        f.addStretch(1)
        grid.addWidget(ov, 0, 1)

        # ---- transfer ----
        tr, tv = card("Transfer", "What happens after you let go.",
                      icon="flip")
        self.mode_manual = QRadioButton("Manual")
        self.mode_exp = QRadioButton("Experimental")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.mode_manual)
        self._mode_group.addButton(self.mode_exp)
        modes = QHBoxLayout()
        modes.setSpacing(24)
        modes.addWidget(with_help(self.mode_manual, (
            "<b>Recommended.</b> The slots stay highlighted and tick off "
            "as you Ctrl-click each one yourself.")))
        modes.addWidget(with_help(self.mode_exp, (
            "Ctrl-clicks every selected slot for you. <b>Not "
            "GGG-compliant</b>: many game actions from one input.")))
        modes.addStretch(1)
        tv.addLayout(modes)
        ef = QHBoxLayout()
        ef.setSpacing(18)
        self.delay = QSpinBox(); self.delay.setRange(20, 2000); self.delay.setSuffix(" ms")
        self.max_slots = QSpinBox(); self.max_slots.setRange(1, 200)
        ef.addWidget(field("Delay Between Clicks", self.delay), 1)
        ef.addWidget(field("Max Slots Per Drag", self.max_slots), 1)
        tv.addLayout(ef)
        self.exp_warning = QLabel(
            "⚠  Not GGG-Compliant. Use At Your Own Risk. "
            "F12, Esc Or Moving The Mouse Stops It.")
        self.exp_warning.setWordWrap(True)
        self.exp_warning.setProperty("role", "warn")
        tv.addWidget(self.exp_warning)
        grid.addWidget(tr, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        v.addStretch(1)

        for w in (self.enabled_cb, self.detect_cb, self.skip_empty_cb,
                  self.overlay_cb, self.debug_cb, *self.grid_cbs.values()):
            w.toggled.connect(self._save)
        self.modifier.currentIndexChanged.connect(self._save)
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
        self.modifier.setCurrentIndex(max(0, self.modifier.findData(
            s.modifier if s.modifier in MODIFIERS else "alt")))
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
            modifier=self.modifier.currentData() or "alt",
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
                self, "Experimental Transfer", EXPERIMENTAL_WARNING,
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
                f"On Screen: {b.left:.0f}, {b.top:.0f} → "
                f"{b.right:.0f}, {b.bottom:.0f}")
        except Exception as e:
            self.bounds_label.setText(f"Not Calibrated ({e})")
