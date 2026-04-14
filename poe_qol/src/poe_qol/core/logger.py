"""Centralised logger. Rotating file + console."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    root = logging.getLogger("poe_qol")
    root.setLevel(level)
    root.handlers.clear()

    fh = RotatingFileHandler(log_dir / "poe_qol.log",
                             maxBytes=1_000_000, backupCount=3)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    return root
