"""PoE trade query pipeline used by the Map Search tab.

* :class:`MapDataset` + :func:`build_map_query` turn the visual mod
  selection (``config/map_mods.yaml``, v2 schema) into a trade payload.
* :func:`build_url` turns that payload into a pathofexile.com/trade URL.

The older regex-style pipeline (``parse`` / ``build_query`` / ``ModMap``)
was removed: its v1 data schema no longer exists and nothing used it.
"""
from .builder import build_url  # noqa: F401
from .map_query import (  # noqa: F401
    MapDataset, ItemType, Category, Mod, Preset, build_map_query,
)
