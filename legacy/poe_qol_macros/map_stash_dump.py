"""Map-stash dump – Ctrl-click every selected slot in a Map stash tab.

Same machinery as `inventory_dump`; only the grid dimensions and
config namespace differ (6 rows × 12 cols by default for Map tabs).
"""
from __future__ import annotations

from ..engine.registry import register
from .inventory_dump import GridDumpMacro


@register
class MapStashDumpMacro(GridDumpMacro):
    NAME = "map_stash_dump"
    CFG_PATH = "macros.map_stash_dump"
    HOTKEYS = {
        "left":  "macros.map_stash_dump.hotkeys.left",
        "right": "macros.map_stash_dump.hotkeys.right",
    }
