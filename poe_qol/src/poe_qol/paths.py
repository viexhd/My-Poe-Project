"""Where the app's files live.

From source, the app root is the ``poe_qol/`` project folder (it holds
``config/``, ``assets/`` and ``logs/``). In the packaged Windows build
(PyInstaller), the same folders sit next to ``TwiceCorrupted.exe``, so
the root is the exe's folder. Everything else asks :func:`app_root`.
"""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True inside the packaged (PyInstaller) build."""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # src/poe_qol/paths.py → parents[2] = the poe_qol project folder
    return Path(__file__).resolve().parents[2]


def user_data_dir() -> Path:
    """Per-user data (stash history, sign-in token): never in the repo.

    ``%APPDATA%\\twice-corrupted`` on Windows (the trade browser's
    profile lives there too), ``$XDG_DATA_HOME/twice-corrupted``
    elsewhere. ``TWICE_CORRUPTED_DATA`` overrides it (tests).
    """
    import os
    env = os.environ.get("TWICE_CORRUPTED_DATA")
    if env:
        return Path(env)
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "twice-corrupted"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "twice-corrupted"
