"""Composition root. Wires config → state → input → engine → UI.

Command-line flags (used by the packaged build and its shortcuts):
    --elevate     re-launch with administrator rights (Windows UAC), so
                  in-game hotkeys reach Path of Exile when it runs as admin
    --smoke-test  start the full UI off-screen, then quit after a few
                  seconds with exit code 0 (used by the release build)
"""
from __future__ import annotations

import os
import sys

from . import APP_ID, APP_NAME, __version__
from .paths import app_root

SMOKE_TEST_MS = 4000


def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_elevated(args: list[str]) -> bool:
    """Start this program again via UAC. True if the prompt was accepted."""
    import ctypes
    import subprocess
    from .paths import is_frozen
    if is_frozen():
        exe, params = sys.executable, args
    else:
        exe, params = sys.executable, ["-m", "poe_qol", *args]
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", exe, subprocess.list2cmdline(params), str(app_root()), 1)
    return rc > 32          # ShellExecute returns > 32 on success


def _smoke_test(qapp, win, log) -> None:
    """Check the build works: every page built, and QtWebEngine (Trade
    Browser) can start its renderer and load a page. Exits with 0 when
    both pass, 2 otherwise."""
    from PySide6.QtCore import QTimer
    result = {"web": False}
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from .ui.trade_browser import create_trade_browser
        # Builds the real window; its page only allows pathofexile.com,
        # so the renderer check below uses a plain view instead.
        result["browser"] = create_trade_browser("Standard")
        view = QWebEngineView()
        result["view"] = view
        view.loadFinished.connect(
            lambda ok: result.__setitem__("web", bool(ok)))
        view.setHtml("<p>smoke</p>")
    except Exception:
        log.exception("smoke test: trade browser failed to start")

    def _done() -> None:
        pages = win.pages.count()
        ok = pages > 0 and pages == len(win._nav_buttons) and result["web"]
        log.info("smoke test %s: %d pages, web engine %s",
                 "OK" if ok else "FAILED", pages,
                 "loaded" if result["web"] else "did not load")
        qapp.exit(0 if ok else 2)
    QTimer.singleShot(SMOKE_TEST_MS, _done)


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    smoke = "--smoke-test" in argv
    if "--elevate" in argv:
        argv.remove("--elevate")
        if sys.platform == "win32" and not _is_admin():
            return 0 if _relaunch_elevated(argv) else 1
    if smoke:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    # Relative paths in config (config/map_mods.yaml, logs/coords.json…)
    # resolve against the app root, however the app was started.
    root = app_root()
    os.chdir(root)

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    from .core.config import ConfigStore
    from .core.logger import setup_logging
    from .core.state import AppState
    from .engine.scheduler import Scheduler
    from .input.hotkeys import HotkeyRouter
    from .input.sender import InputSender
    from .ui.branding import load_app_icon
    from .ui.main_window import MainWindow
    from .ui.styles import apply_theme

    cfg = ConfigStore(root)
    log = setup_logging(root / "logs", cfg.get("app.log_level", "INFO"))
    log.info("%s %s starting from %s (input backend will be: %s)",
             APP_NAME, __version__, root, "pydirectinput")

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
    qapp = QApplication([sys.argv[0], *argv])
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
    if smoke:
        _smoke_test(qapp, win, log)
    try:
        return qapp.exec()
    finally:
        area_select.shutdown()
        scheduler.shutdown()


def main() -> int:
    """Entry point for the packaged exe: like :func:`run`, but a crash
    is written to ``logs/crash.log`` and shown in a message box, since a
    windowed exe has no console to print to."""
    try:
        return run()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        text = traceback.format_exc()
        try:
            logs = app_root() / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            (logs / "crash.log").write_text(text, encoding="utf-8")
        except OSError:
            pass
        if "--smoke-test" not in sys.argv and sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    None, f"{APP_NAME} hit an error and has to close.\n\n"
                    f"{text[-1500:]}\nDetails: logs\\crash.log",
                    APP_NAME, 0x10)
            except Exception:
                pass
        else:
            print(text, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
