"""Visual inventory slot selector.

Renders a rows×cols grid of toggle buttons. Selection is kept in sync
with `macros.inventory_dump.selected_slots` in config. Profiles under
`config/slot_profiles/` can be saved / loaded by name.

Also exposes an overlay preview that mirrors the selection at real
inventory coordinates (origin + cell_size from config), drawn as a
frameless always-on-top Qt window. Useful to eyeball that the grid
lines up with the game before you hit F1.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore


CELL_SIZE_PX = 28   # button size in the selector (purely cosmetic)


class SlotSelector(QWidget):
    def __init__(self, cfg: ConfigStore, on_change: Callable[[], None] | None = None):
        super().__init__()
        self.cfg = cfg
        self.on_change = on_change or (lambda: None)
        self._buttons: dict[tuple[int, int], QToolButton] = {}
        self._overlay: _OverlayWindow | None = None
        self._build()

    # ---- construction ----
    def _build(self) -> None:
        v = QVBoxLayout(self)

        rows = self.cfg.get("macros.inventory_dump.grid.rows", 5)
        cols = self.cfg.get("macros.inventory_dump.grid.cols", 12)

        header = QLabel(f"Inventory slots ({rows} × {cols})")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(header)

        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setSpacing(2)
        grid.setContentsMargins(0, 0, 0, 0)
        selected = {tuple(s) for s in
                    (self.cfg.get("macros.inventory_dump.selected_slots") or [])}
        for r in range(rows):
            for c in range(cols):
                b = QToolButton()
                b.setCheckable(True)
                b.setChecked((r, c) in selected)
                b.setFixedSize(CELL_SIZE_PX, CELL_SIZE_PX)
                b.setToolTip(f"row {r}, col {c}")
                b.toggled.connect(lambda _v, rr=r, cc=c: self._on_toggle(rr, cc))
                self._style_button(b)
                grid.addWidget(b, r, c)
                self._buttons[(r, c)] = b
        v.addWidget(grid_w)

        # Controls row: all / none / invert
        ctl = QHBoxLayout()
        for label, fn in (("All", self._select_all),
                          ("None", self._clear),
                          ("Invert", self._invert)):
            btn = QPushButton(label)
            btn.clicked.connect(fn)
            ctl.addWidget(btn)
        v.addLayout(ctl)

        # Profile row: dropdown + save/load/delete
        prof = QHBoxLayout()
        self.prof_combo = QComboBox()
        self.prof_combo.setEditable(False)
        self._refresh_profiles()
        self.prof_combo.currentTextChanged.connect(self._on_profile_changed)
        prof.addWidget(QLabel("Profile:"))
        prof.addWidget(self.prof_combo, 1)
        for label, fn in (("Save", self._save_profile_prompt),
                          ("Delete", self._delete_profile)):
            btn = QPushButton(label)
            btn.clicked.connect(fn)
            prof.addWidget(btn)
        v.addLayout(prof)

        # Overlay + calibration row
        ov = QHBoxLayout()
        self.overlay_btn = QPushButton("Show overlay")
        self.overlay_btn.setCheckable(True)
        self.overlay_btn.toggled.connect(self._on_overlay_toggle)
        ov.addWidget(self.overlay_btn, 1)

        self.calibrate_btn = QPushButton("Calibrate…")
        self.calibrate_btn.setToolTip(
            "Capture top-left / right / down slot positions from the cursor "
            "and compute origin + cell size automatically.")
        self.calibrate_btn.clicked.connect(self._on_calibrate)
        ov.addWidget(self.calibrate_btn, 1)
        v.addLayout(ov)

        summary = QLabel()
        self._summary = summary
        v.addWidget(summary)
        self._refresh_summary()

    def _style_button(self, b: QToolButton) -> None:
        b.setStyleSheet("""
            QToolButton            { background:#333; border:1px solid #555; }
            QToolButton:checked    { background:#4a8; border:1px solid #7db; }
            QToolButton:hover      { border:1px solid #aaa; }
        """)

    # ---- selection ----
    def _current_selected(self) -> list[tuple[int, int]]:
        return [rc for rc, b in self._buttons.items() if b.isChecked()]

    def _commit(self) -> None:
        sel = sorted(self._current_selected())
        self.cfg.set("macros.inventory_dump.selected_slots",
                     [list(p) for p in sel])
        # switching out of profile mode when user hand-edits
        self.cfg.set("macros.inventory_dump.active_slot_profile", None)
        self._refresh_summary()
        if self._overlay:
            self._overlay.refresh(sel)
        self.on_change()

    def _on_toggle(self, r: int, c: int) -> None:
        self._commit()

    def _select_all(self) -> None:
        for b in self._buttons.values():
            b.blockSignals(True)
            b.setChecked(True)
            b.blockSignals(False)
        self._commit()

    def _clear(self) -> None:
        for b in self._buttons.values():
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self._commit()

    def _invert(self) -> None:
        for b in self._buttons.values():
            b.blockSignals(True)
            b.setChecked(not b.isChecked())
            b.blockSignals(False)
        self._commit()

    def _refresh_summary(self) -> None:
        n = len(self._current_selected())
        total = len(self._buttons)
        self._summary.setText(f"{n} / {total} selected"
                              + ("  (all)" if n == total else ""))

    # ---- profiles ----
    def _profile_dir(self) -> Path:
        return Path(self.cfg.get("macros.inventory_dump.slot_profile_dir",
                                 "config/slot_profiles"))

    def _refresh_profiles(self) -> None:
        self.prof_combo.blockSignals(True)
        self.prof_combo.clear()
        self.prof_combo.addItem("(none)")
        d = self._profile_dir()
        if d.exists():
            for p in sorted(d.glob("*.yaml")):
                self.prof_combo.addItem(p.stem)
        active = self.cfg.get("macros.inventory_dump.active_slot_profile")
        if active:
            i = self.prof_combo.findText(active)
            if i >= 0:
                self.prof_combo.setCurrentIndex(i)
        self.prof_combo.blockSignals(False)

    def _on_profile_changed(self, name: str) -> None:
        if not name or name == "(none)":
            self.cfg.set("macros.inventory_dump.active_slot_profile", None)
            return
        path = self._profile_dir() / f"{name}.yaml"
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text()) or {}
        slots = {tuple(s) for s in data.get("slots") or []}
        for rc, b in self._buttons.items():
            b.blockSignals(True)
            b.setChecked(rc in slots)
            b.blockSignals(False)
        self.cfg.set("macros.inventory_dump.active_slot_profile", name)
        self.cfg.set("macros.inventory_dump.selected_slots",
                     [list(s) for s in sorted(slots)])
        self._refresh_summary()
        if self._overlay:
            self._overlay.refresh(sorted(slots))

    def _save_profile_prompt(self) -> None:
        name, ok = QInputDialog.getText(self, "Save slot profile", "Name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        d = self._profile_dir()
        d.mkdir(parents=True, exist_ok=True)
        slots = sorted(self._current_selected())
        (d / f"{name}.yaml").write_text(yaml.safe_dump(
            {"name": name, "slots": [list(s) for s in slots]},
            sort_keys=False))
        self._refresh_profiles()
        i = self.prof_combo.findText(name)
        if i >= 0:
            self.prof_combo.setCurrentIndex(i)

    def _delete_profile(self) -> None:
        name = self.prof_combo.currentText()
        if name in ("", "(none)"):
            return
        ok = QMessageBox.question(self, "Delete profile",
                                  f"Delete slot profile '{name}'?")
        if ok != QMessageBox.StandardButton.Yes:
            return
        p = self._profile_dir() / f"{name}.yaml"
        if p.exists():
            p.unlink()
        self._refresh_profiles()

    # ---- calibration ----
    def _on_calibrate(self) -> None:
        from .calibrate_dialog import CalibrateDialog
        dlg = CalibrateDialog(self.cfg, self)
        if dlg.exec():
            # refresh overlay if visible so it reflects new origin/cell
            if self._overlay:
                self._overlay._reposition()
                self._overlay.refresh(self._current_selected())

    # ---- overlay ----
    def _on_overlay_toggle(self, on: bool) -> None:
        if on:
            self._overlay = _OverlayWindow(self.cfg)
            self._overlay.refresh(self._current_selected())
            self._overlay.show()
            self.overlay_btn.setText("Hide overlay")
        else:
            if self._overlay:
                self._overlay.close()
                self._overlay = None
            self.overlay_btn.setText("Show overlay")


class _OverlayWindow(QWidget):
    """Frameless always-on-top window that draws highlighted squares at
    the game's real inventory coordinates. Click-through on best effort
    — if the platform doesn't support it the user can just drag it away."""

    def __init__(self, cfg: ConfigStore):
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.cfg = cfg
        self._selected: list[tuple[int, int]] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._reposition)
        self._timer.start(250)
        self._reposition()

    def _current_origin(self) -> tuple[int, int]:
        """Mirror of InventoryDumpMacro._resolve_origin, sans template
        match (we don't want to capture the screen at 4 Hz)."""
        rel = self.cfg.get("macros.inventory_dump.origin_relative_to_window")
        if rel:
            try:
                from ..vision.window import find_window
                rect = find_window(
                    self.cfg.get(
                        "macros.inventory_dump.window.title_pattern",
                        "Path of Exile"),
                    self.cfg.get(
                        "macros.inventory_dump.window.class_pattern"),
                )
                if rect is not None:
                    ax, ay = rect.anchor(rel.get("anchor", "top_left"))
                    dx, dy = rel.get("offset", [0, 0])
                    return (ax + int(dx), ay + int(dy))
            except Exception:
                pass
        return tuple(  # type: ignore[return-value]
            self.cfg.get("macros.inventory_dump.grid.origin", [1988, 612]))

    def _reposition(self) -> None:
        origin = self._current_origin()
        cell = self.cfg.get("macros.inventory_dump.grid.cell_size", [53, 55])
        rows = self.cfg.get("macros.inventory_dump.grid.rows", 5)
        cols = self.cfg.get("macros.inventory_dump.grid.cols", 12)
        # window covers the whole grid bounding box, centred on each slot.
        pad = max(cell) // 2 + 4
        w = cols * cell[0] + pad * 2
        h = rows * cell[1] + pad * 2
        self._origin_cache = origin
        self.setGeometry(origin[0] - pad, origin[1] - pad, w, h)

    def refresh(self, selected) -> None:
        self._selected = list(selected)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802 – Qt naming
        origin = getattr(self, "_origin_cache", None) or self._current_origin()
        cell = self.cfg.get("macros.inventory_dump.grid.cell_size", [53, 55])
        pad = max(cell) // 2 + 4
        size = min(cell)  # square highlight
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor(80, 220, 140, 90)
        border = QColor(80, 220, 140, 220)
        p.setBrush(fill)
        p.setPen(border)
        for r, c in self._selected:
            # local coords = (slot screen coord) - (window top-left)
            lx = origin[0] + c * cell[0] - (origin[0] - pad) - size // 2
            ly = origin[1] + r * cell[1] - (origin[1] - pad) - size // 2
            p.drawRoundedRect(lx, ly, size, size, 4, 4)
