"""Composition root. Wires config → state → input → engine → UI."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .core.config import ConfigStore
from .core.logger import setup_logging
from .core.state import AppState
from .engine.scheduler import Scheduler
from .input.hotkeys import HotkeyRouter
from .input.sender import InputSender
from .ui.main_window import MainWindow


def run() -> int:
    root = Path(__file__).resolve().parents[2]
    cfg = ConfigStore(root)
    log = setup_logging(root / "logs", cfg.get("app.log_level", "INFO"))
    log.info("poe_qol starting (input backend will be: %s)",
             "pydirectinput")

    state = AppState()
    state.set("global_enabled", cfg.get("app.global_enabled", True))

    sender = InputSender(
        pre_click_settle_ms=cfg.get("input.pre_click_settle_ms", 30),
        click_jitter_px=cfg.get("input.click_jitter_px", 0),
    )
    hotkeys = HotkeyRouter()
    scheduler = Scheduler(cfg, state, sender, hotkeys)
    scheduler.load()

    qapp = QApplication(sys.argv)
    win = MainWindow(cfg, state, scheduler)
    win.show()
    try:
        return qapp.exec()
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    raise SystemExit(run())
