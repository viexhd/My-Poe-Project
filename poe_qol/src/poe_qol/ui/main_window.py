"""Minimal but functional Qt UI.

Shows:
    * Master enable toggle
    * Per-macro enable checkbox
    * Per-macro hotkey field (click-to-capture)
    * Life-flask interval slider pair
    * Emergency stop button
    * Status bar with currently running macros
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore
from ..core.state import AppState
from ..engine.scheduler import Scheduler


class MainWindow(QMainWindow):
    def __init__(self, cfg: ConfigStore, state: AppState,
                 scheduler: Scheduler) -> None:
        super().__init__()
        self.cfg = cfg
        self.state = state
        self.scheduler = scheduler

        self.setWindowTitle("PoE QoL")
        self.resize(360, 420)

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)

        # Master switch
        self.master = QCheckBox("Global enabled")
        self.master.setChecked(cfg.get("app.global_enabled", True))
        self.master.stateChanged.connect(self._on_master)
        v.addWidget(self.master)

        # Emergency stop
        self.estop = QPushButton("EMERGENCY STOP (F12)")
        self.estop.setStyleSheet("background:#c00;color:white;font-weight:bold")
        self.estop.clicked.connect(scheduler.emergency_stop)
        v.addWidget(self.estop)

        # Per-macro rows
        self._macro_widgets: dict[str, QCheckBox] = {}
        for name, macro in scheduler.macros.items():
            row = QHBoxLayout()
            cb = QCheckBox(name)
            cb.setChecked(macro.enabled)
            cb.stateChanged.connect(lambda s, n=name:
                                    self.cfg.set(f"macros.{n}.enabled", bool(s)))
            self._macro_widgets[name] = cb
            row.addWidget(cb)

            # hotkey editor (one representative hotkey per macro)
            if macro.HOTKEYS:
                action, path = next(iter(macro.HOTKEYS.items()))
                le = QLineEdit(self.cfg.get(path, "") or "")
                le.setPlaceholderText(f"{action} hotkey")
                le.editingFinished.connect(
                    lambda le=le, p=path: self._rebind(p, le.text())
                )
                row.addWidget(le)
            v.addLayout(row)

        # Life-flask interval tuners (example of config-driven knob)
        v.addWidget(QLabel("Life flask interval (ms)"))
        lo, hi = cfg.get("macros.life_flask.interval_ms", [4000, 5000])
        row = QHBoxLayout()
        self.lo_spin = QSpinBox(); self.lo_spin.setRange(500, 30000); self.lo_spin.setValue(lo)
        self.hi_spin = QSpinBox(); self.hi_spin.setRange(500, 30000); self.hi_spin.setValue(hi)
        self.lo_spin.valueChanged.connect(self._on_interval)
        self.hi_spin.valueChanged.connect(self._on_interval)
        row.addWidget(self.lo_spin); row.addWidget(self.hi_spin)
        v.addLayout(row)

        # Status bar
        self.status = QLabel("Idle")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.status)

        # Periodic status refresh
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(400)

    # ---- slots ----
    def _on_master(self, s: int) -> None:
        self.cfg.set("app.global_enabled", bool(s))
        self.state.set("global_enabled", bool(s))

    def _on_interval(self) -> None:
        self.cfg.set("macros.life_flask.interval_ms",
                     [self.lo_spin.value(), self.hi_spin.value()])

    def _rebind(self, cfg_path: str, combo: str) -> None:
        self.cfg.set(cfg_path, combo)
        # re-bind everything (cheap & simple)
        self.scheduler.hotkeys.unbind_all()
        self.scheduler._bind_hotkeys()

    def _refresh_status(self) -> None:
        active = [n for n, m in self.scheduler.macros.items() if m.running]
        self.status.setText("Active: " + (", ".join(active) if active else "—"))
