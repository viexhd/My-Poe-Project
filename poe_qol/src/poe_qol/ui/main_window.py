"""Tabbed Qt main window.

Tabs:
    * Macros      – global toggle, per-macro on/off + hotkey editor
    * Inventory   – visual 12×5 slot selector + slot profiles + overlay
    * Map Stash   – visual 12×6 slot selector for the Map stash tab
    * Map Search  – visual map mod exclusion → pathofexile.com/trade link
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore
from ..core.state import AppState
from ..engine.scheduler import Scheduler
from .map_search_widget import MapSearchWidget
from .slot_selector import SlotSelector


class MainWindow(QMainWindow):
    def __init__(self, cfg: ConfigStore, state: AppState,
                 scheduler: Scheduler) -> None:
        super().__init__()
        self.cfg = cfg
        self.state = state
        self.scheduler = scheduler

        self.setWindowTitle("PoE QoL")
        # Larger default so the Map Search tab's category grid fits
        # without scrolling. The Macros / slot-selector tabs are happy
        # with less space but benefit from the extra width too.
        self.resize(760, 680)

        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        tabs.addTab(self._build_macros_tab(), "Macros")
        tabs.addTab(self._build_inventory_tab(), "Inventory")
        tabs.addTab(self._build_map_stash_tab(), "Map Stash")
        tabs.addTab(MapSearchWidget(cfg), "Map Search")

        # Status bar
        self.status = QLabel("Idle")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.statusBar().addPermanentWidget(self.status, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(400)

    # ---- macros tab ----
    def _build_macros_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        self.master = QCheckBox("Global enabled")
        self.master.setChecked(self.cfg.get("app.global_enabled", True))
        self.master.stateChanged.connect(self._on_master)
        v.addWidget(self.master)

        self.estop = QPushButton("EMERGENCY STOP (F12)")
        self.estop.setStyleSheet(
            "background:#c00;color:white;font-weight:bold;padding:8px")
        self.estop.clicked.connect(self.scheduler.emergency_stop)
        v.addWidget(self.estop)

        for name, macro in self.scheduler.macros.items():
            row = QHBoxLayout()
            cb = QCheckBox(name)
            cb.setChecked(macro.enabled)
            cb.stateChanged.connect(
                lambda s, n=name:
                self.cfg.set(f"macros.{n}.enabled", bool(s)))
            row.addWidget(cb)

            # One line-edit per action in HOTKEYS so macros with both
            # `left` and `right` bindings (inventory_dump,
            # map_stash_dump) are fully editable from the UI.
            for action, path in macro.HOTKEYS.items():
                row.addWidget(QLabel(action))
                le = QLineEdit(self.cfg.get(path, "") or "")
                le.setMaximumWidth(90)
                le.setPlaceholderText(action)
                le.editingFinished.connect(
                    lambda le=le, p=path: self._rebind(p, le.text()))
                row.addWidget(le)
            v.addLayout(row)

        # Surface any hotkey collision the router detected at
        # bind-time so the user sees it instead of only learning
        # about it via the logs.
        self.conflict_label = QLabel("")
        self.conflict_label.setStyleSheet("color:#e80;font-weight:bold;")
        self.conflict_label.setWordWrap(True)
        v.addWidget(self.conflict_label)

        v.addWidget(QLabel("Life flask interval (ms)"))
        lo, hi = self.cfg.get("macros.life_flask.interval_ms", [4000, 5000])
        row = QHBoxLayout()
        self.lo_spin = QSpinBox(); self.lo_spin.setRange(500, 30000); self.lo_spin.setValue(lo)
        self.hi_spin = QSpinBox(); self.hi_spin.setRange(500, 30000); self.hi_spin.setValue(hi)
        self.lo_spin.valueChanged.connect(self._on_interval)
        self.hi_spin.valueChanged.connect(self._on_interval)
        row.addWidget(self.lo_spin); row.addWidget(self.hi_spin)
        v.addLayout(row)

        v.addStretch(1)
        return w

    # ---- inventory tab ----
    def _build_inventory_tab(self) -> QWidget:
        return SlotSelector(
            self.cfg,
            cfg_path="macros.inventory_dump",
            title="Inventory",
            macro=self.scheduler.macros.get("inventory_dump"),
            scheduler=self.scheduler,
        )

    # ---- map stash tab ----
    def _build_map_stash_tab(self) -> QWidget:
        return SlotSelector(
            self.cfg,
            cfg_path="macros.map_stash_dump",
            title="Map Stash",
            macro=self.scheduler.macros.get("map_stash_dump"),
            scheduler=self.scheduler,
        )

    # ---- slots ----
    def _on_master(self, s: int) -> None:
        on = bool(s)
        self.cfg.set("app.global_enabled", on)
        self.state.set("global_enabled", on)
        # Re-enabling clears any latched emergency-stop so macros can
        # actually fire again. Without this the app looks healthy but
        # every macro.guard() still returns False.
        if on:
            self.state.clear_emergency()

    def _on_interval(self) -> None:
        self.cfg.set("macros.life_flask.interval_ms",
                     [self.lo_spin.value(), self.hi_spin.value()])

    def _rebind(self, cfg_path: str, combo: str) -> None:
        self.cfg.set(cfg_path, combo)
        self.scheduler.hotkeys.unbind_all()
        self.scheduler._bind_hotkeys()

    def _refresh_status(self) -> None:
        # Keep the master checkbox in sync with state so an F12 press
        # (which flips global_enabled off) is visible in the UI.
        want = bool(self.cfg.get("app.global_enabled", True))
        if self.master.isChecked() != want:
            self.master.blockSignals(True)
            self.master.setChecked(want)
            self.master.blockSignals(False)

        # Surface any hotkey conflict reported by the router.
        conflict = getattr(self.scheduler.hotkeys, "last_conflict", None)
        if conflict and self.conflict_label.text() != conflict:
            self.conflict_label.setText(conflict)
        elif not conflict and self.conflict_label.text():
            self.conflict_label.setText("")

        if self.state.stop_event.is_set():
            self.status.setText(
                "EMERGENCY STOP — re-check 'Global enabled' to resume")
            return

        # Progress-aware active list. Macros expose `progress` as
        # (current, total) during a sweep so we can render
        # "inventory_dump 5/60" instead of just the name.
        parts: list[str] = []
        for n, m in self.scheduler.macros.items():
            if not m.running:
                continue
            prog = getattr(m, "progress", None)
            if prog:
                parts.append(f"{n} {prog[0]}/{prog[1]}")
            else:
                parts.append(n)
        self.status.setText(
            "Active: " + (", ".join(parts) if parts else "—"))
