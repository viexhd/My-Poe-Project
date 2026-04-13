"""Macro registry / plugin discovery.

Macros register themselves with @register so adding a new file in
`poe_qol/macros/` is the only step required to ship a new feature.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Type

from .macro import Macro

_REGISTRY: dict[str, Type[Macro]] = {}


def register(cls: Type[Macro]) -> Type[Macro]:
    if not cls.NAME or cls.NAME == "base":
        raise ValueError(f"Macro {cls} must set a unique NAME")
    _REGISTRY[cls.NAME] = cls
    return cls


def discover(package: str = "poe_qol.macros") -> dict[str, Type[Macro]]:
    """Import every module in the package so @register runs."""
    pkg = importlib.import_module(package)
    for modinfo in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{package}.{modinfo.name}")
    return dict(_REGISTRY)
