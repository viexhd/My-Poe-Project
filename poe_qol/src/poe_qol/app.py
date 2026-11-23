"""Composition root. Wires config → state → input → engine → UI."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from . import APP_ID, APP_NAME, __version__
from .core.config import ConfigStore
from .core.logger import setup_logging
from .core.state import AppState
from .engine.scheduler import Scheduler
from .input.hotkeys import HotkeyRouter
from .input.sender import InputSender
from .ui.branding import load_app_icon
from .ui.main_window import MainWindow
from .ui.styles import apply_theme


def run() -> int:
    root = Path(__file__).resolve().parents[2]
    cfg = ConfigStore(root)
    log = setup_logging(root / "logs", cfg.get("app.log_level", "INFO"))
    log.info("%s %s starting (input backend will be: %s)",
             APP_NAME, __version__, "pydirectinput")

    state = AppState()
    state.set("global_enabled", cfg.get("app.global_enabled", True))

    sender = InputSender(
        pre_click_settle_ms=cfg.get("input.pre_click_settle_ms", 30),
        click_jitter_px=cfg.get("input.click_jitter_px", 0),
    )
    hotkeys = HotkeyRouter()
    scheduler = Scheduler(cfg, state, sender, hotkeys)
    scheduler.load()

    # Required before QApplication when QtWebEngine (Trade Browser) is
    # imported later on.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_ID)
    qapp.setApplicationDisplayName(APP_NAME)
    qapp.setApplicationVersion(__version__)
    apply_theme(qapp)
    icon = load_app_icon(root)
    if not icon.isNull():
        qapp.setWindowIcon(icon)
    # Alt+drag area selection (needs a running QApplication). Its global
    # mouse hook is only installed when the feature is enabled.
    from .area_select.controller import AreaSelectController
    area_select = AreaSelectController(cfg, state, sender)
    win = MainWindow(cfg, state, scheduler, area_select=area_select)
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.show()
    try:
        return qapp.exec()
    finally:
        area_select.shutdown()
        scheduler.shutdown()


if __name__ == "__main__":
    raise SystemExit(run())
