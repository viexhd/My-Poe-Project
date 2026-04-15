"""Tabbed Qt main window.

Tabs:
    * Macros      – global toggle, per-macro on/off + hotkey editor
    * Inventory   – 12×5 slot highlighter + slot profiles + overlay
    * Map Stash   – 12×6 slot highlighter for the Map stash tab
    * Map Search  – visual map mod exclusion → pathofexile.com/trade link
    * Flipper     – poe.ninja-backed bulk currency flip ranking
    * Pricer      – clipboard-driven trade-site price lookup

Help → About shows GGG's required third-party disclaimer.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, DISCLAIMER, __version__

from ..core.config import ConfigStore
from ..core.state import AppState
from ..engine.scheduler import Scheduler
from .map_search_widget import MapSearchWidget
from .slot_selector import SlotSelector
from .flipper_widget import FlipperWidget
from .pricer_widget import PricerWidget


class MainWindow(QMainWindow):
    def __init__(self, cfg: ConfigStore, state: AppState,
                 scheduler: Scheduler) -> None:
        super().__init__()
        self.cfg = cfg
        self.state = state
        self.scheduler = scheduler

        self.setWindowTitle(APP_NAME)
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
        # Flipper needs repo root to locate its disk cache. Resolve
        # the same way app.py does — two parents up from this file's
        # package, then two more to reach the repo.
        from pathlib import Path as _Path
        repo_root = _Path(__file__).resolve().parents[3]
        tabs.addTab(FlipperWidget(cfg, repo_root), "Flipper")
        tabs.addTab(PricerWidget(cfg), "Pricer")

        help_menu = self.menuBar().addMenu("&Help")
        about = QAction(f"About {APP_NAME}", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

        # Qt-level fallback shortcut for emergency stop. The primary
        # path is the global `keyboard` hook (input/hotkeys.py), but
        # that fails silently when:
        #   * PoE runs as admin and this app doesn't (Windows UIPI)
        #   * the `keyboard` package isn't installed / lacks privileges
        # In those cases F12 still fires when *our* window has focus,
        # so Alt-Tabbing here and pressing F12 remains a reliable kill.
        self._estop_shortcut = QShortcut(QKeySequence("F12"), self)
        self._estop_shortcut.setContext(
            Qt.ShortcutContext.ApplicationShortcut)
        self._estop_shortcut.activated.connect(self.scheduler.emergency_stop)

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

        self.estop = QPushButton("Emergency stop (F12)")
        # Themed via ui/styles.py: ghost-red by default, fills solid red
        # when armed (`armed` property flipped on by _refresh_status).
        self.estop.setProperty("role", "danger")
        self.estop.setProperty("armed", False)
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

            # One line-edit per action in HOTKEYS so macros with
            # several bindings are fully editable from the UI.
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
        self.conflict_label.setStyleSheet(
            "color:#E0A24A; font-weight:600;")
        self.conflict_label.setWordWrap(True)
        v.addWidget(self.conflict_label)

        v.addStretch(1)
        return w

    # ---- inventory tab ----
    def _build_inventory_tab(self) -> QWidget:
        return SlotSelector(
            self.cfg,
            cfg_path="macros.inventory_dump",
            title="Inventory",
            scheduler=self.scheduler,
        )

    # ---- map stash tab ----
    def _build_map_stash_tab(self) -> QWidget:
        return SlotSelector(
            self.cfg,
            cfg_path="macros.map_stash_dump",
            title="Map Stash",
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

    def about_text(self) -> str:
        return "\n".join([
            f"{APP_NAME} {__version__}",
            "",
            "A quality-of-life companion for Path of Exile.",
            "It never reads or changes game memory or game files, and "
            "never runs game input on a timer.",
            "",
            DISCLAIMER,
        ])

    def _show_about(self) -> None:
        QMessageBox.about(self, f"About {APP_NAME}", self.about_text())

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

        tripped = self.state.stop_event.is_set()
        if self.estop.property("armed") != tripped:
            from .styles import repolish
            self.estop.setProperty("armed", tripped)
            repolish(self.estop)
        if tripped:
            self.status.setText(
                "EMERGENCY STOP — re-check 'Global enabled' to resume")
            return

        # Progress-aware active list. Macros expose `progress` as
        # (current, total) while working so we can render
        # "name 5/60" instead of just the name.
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
