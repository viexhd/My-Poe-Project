"""App icon / branding helpers.

Loads the Twice Corrupted icon (generated from assets/brand/icon.svg
by ``python -m poe_qol.tools.build_brand``). Search order (first match
wins):

    <repo>/poe_qol/assets/app_icon.png
    <repo>/poe_qol/assets/app_icon.ico
    <repo>/assets/app_icon.png

Returns a null QIcon if none are present; callers should just set it
unconditionally — Qt treats a null icon as "no icon".
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon


_CANDIDATE_SUBPATHS = (
    "poe_qol/assets/app_icon.png",
    "poe_qol/assets/app_icon.ico",
    "assets/app_icon.png",
    "assets/app_icon.ico",
)


def resolve_icon_path(repo_root: Path) -> Path | None:
    for rel in _CANDIDATE_SUBPATHS:
        p = repo_root / rel
        if p.exists():
            return p
    return None


def load_app_icon(repo_root: Path) -> QIcon:
    path = resolve_icon_path(repo_root)
    if path is None:
        return QIcon()
    return QIcon(str(path))
