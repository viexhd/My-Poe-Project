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
