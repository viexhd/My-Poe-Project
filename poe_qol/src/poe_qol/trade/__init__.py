"""PoE trade query pipeline.

Two pipelines live here side-by-side:

* ``parse`` + ``build_query`` — the legacy regex-style one, kept for
  anyone still calling it.
* ``MapDataset`` + ``build_map_query`` — the new visual selector
  pipeline used by the Map Search UI tab.

Both feed into :func:`build_url` for the final POST / URL step.
"""
from .parser import parse, ParsedQuery, Group, Atom  # noqa: F401
from .builder import build_query, build_url, ModMap    # noqa: F401
from .map_query import (  # noqa: F401
    MapDataset, ItemType, Category, Mod, Preset, build_map_query,
)
