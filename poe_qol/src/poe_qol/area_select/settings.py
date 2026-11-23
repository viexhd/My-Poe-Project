"""Typed, validated view of the ``area_select:`` config section.

``AreaSelectSettings.load(cfg)`` never raises on bad values: anything
out of range is clamped or replaced with its default, so a typo in
user.yaml can't break the feature. ``save(cfg)`` writes the section back
through ConfigStore and persists it to config/user.yaml.
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any

from .gesture import parse_modifier

log = logging.getLogger("poe_qol.area_select")

SECTION = "area_select"
TRANSFER_MODES = ("manual", "experimental")
ORDERS = ("column_serpentine", "row_major")
MIN_CLICK_DELAY_MS = 20


def _num(v: Any, default: float, lo: float, hi: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, f))


def _int(v: Any, default: int, lo: int, hi: int) -> int:
    return int(round(_num(v, default, lo, hi)))


@dataclass(frozen=True)
class OverlaySettings:
    visible: bool = True
    fill_opacity: float = 0.18     # selection rectangle fill, 0..1
    border_px: int = 2             # selection rectangle border

    @classmethod
    def from_dict(cls, d: dict) -> "OverlaySettings":
        d = d or {}
        return cls(visible=bool(d.get("visible", True)),
                   fill_opacity=_num(d.get("fill_opacity"), 0.18, 0.0, 1.0),
                   border_px=_int(d.get("border_px"), 2, 1, 10))


@dataclass(frozen=True)
class ExperimentalSettings:
    """Settings of the experimental bulk Ctrl-click transfer.

    NOT GGG-compliant: see docs/COMPLIANCE_REVIEW.md §7.
    """
    acknowledged: bool = False             # user accepted the warning
    click_delay_ms: int = 60               # pause between clicks
    max_slots: int = 60                    # hard cap per gesture
    modifier_release_timeout_ms: int = 1500
    abort_move_px: int = 25                # real mouse move this far aborts

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentalSettings":
        d = d or {}
        return cls(
            acknowledged=bool(d.get("acknowledged", False)),
            click_delay_ms=_int(d.get("click_delay_ms"), 60,
                                MIN_CLICK_DELAY_MS, 2000),
            max_slots=_int(d.get("max_slots"), 60, 1, 200),
            modifier_release_timeout_ms=_int(
                d.get("modifier_release_timeout_ms"), 1500, 0, 10000),
            abort_move_px=_int(d.get("abort_move_px"), 25, 5, 500),
        )


@dataclass(frozen=True)
class AreaSelectSettings:
    enabled: bool = True
    modifier: str = "alt"
    grids: tuple[str, ...] = ("macros.inventory_dump",)
    start_margin_px: int = 12
    click_threshold_px: int = 6
    order: str = "column_serpentine"
    detect_items: bool = True
    skip_empty: bool = True
    occupancy_std_min: float = 14.0
    occupancy_mean_min: float = 70.0
    manual_clear_after_s: int = 30
    debug: bool = False
    transfer_mode: str = "manual"
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    experimental: ExperimentalSettings = field(default_factory=ExperimentalSettings)

    # ---- derived ----
    @property
    def modifier_keys(self) -> frozenset[str]:
        return parse_modifier(self.modifier)

    @property
    def effective_mode(self) -> str:
        """Experimental only runs once its warning was acknowledged."""
        if self.transfer_mode == "experimental" and self.experimental.acknowledged:
            return "experimental"
        return "manual"

    # ---- io ----
    @classmethod
    def from_dict(cls, d: dict) -> "AreaSelectSettings":
        d = d or {}
        mod = str(d.get("modifier") or "alt")
        try:
            keys = parse_modifier(mod)
            # Ctrl alone would hijack the Ctrl-clicks manual mode relies on.
            if keys == frozenset({"ctrl"}):
                raise ValueError("ctrl alone is reserved for Ctrl-click")
            mod = "+".join(k for k in ("ctrl", "alt", "shift") if k in keys)
        except ValueError as e:
            log.warning("area_select.modifier %r invalid (%s); using alt", mod, e)
            mod = "alt"
        mode = d.get("transfer_mode", "manual")
        if mode not in TRANSFER_MODES:
            log.warning("area_select.transfer_mode %r invalid; using manual", mode)
            mode = "manual"
        order = d.get("order", "column_serpentine")
        if order not in ORDERS:
            order = "column_serpentine"
        grids = d.get("grids") or ["macros.inventory_dump"]
        if isinstance(grids, str):
            grids = [grids]
        occ = d.get("occupancy") or {}
        return cls(
            enabled=bool(d.get("enabled", True)),
            modifier=mod,
            grids=tuple(str(g) for g in grids),
            start_margin_px=_int(d.get("start_margin_px"), 12, 0, 500),
            click_threshold_px=_int(d.get("click_threshold_px"), 6, 0, 100),
            order=order,
            detect_items=bool(d.get("detect_items", True)),
            skip_empty=bool(d.get("skip_empty", True)),
            occupancy_std_min=_num(occ.get("std_min"), 14.0, 0.0, 255.0),
            occupancy_mean_min=_num(occ.get("mean_min"), 70.0, 0.0, 255.0),
            manual_clear_after_s=_int(d.get("manual_clear_after_s"), 30, 0, 3600),
            debug=bool(d.get("debug", False)),
            transfer_mode=mode,
            overlay=OverlaySettings.from_dict(d.get("overlay")),
            experimental=ExperimentalSettings.from_dict(d.get("experimental")),
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "modifier": self.modifier,
            "grids": list(self.grids),
            "start_margin_px": self.start_margin_px,
            "click_threshold_px": self.click_threshold_px,
            "order": self.order,
            "detect_items": self.detect_items,
            "skip_empty": self.skip_empty,
            "occupancy": {"std_min": self.occupancy_std_min,
                          "mean_min": self.occupancy_mean_min},
            "manual_clear_after_s": self.manual_clear_after_s,
            "debug": self.debug,
            "transfer_mode": self.transfer_mode,
            "overlay": dataclasses.asdict(self.overlay),
            "experimental": dataclasses.asdict(self.experimental),
        }

    @classmethod
    def load(cls, cfg: Any) -> "AreaSelectSettings":
        return cls.from_dict(cfg.get(SECTION) or {})

    def save(self, cfg: Any) -> None:
        cfg.set(SECTION, self.to_dict())
        cfg.save_user_overrides([SECTION])

    def replace(self, **changes: Any) -> "AreaSelectSettings":
        return dataclasses.replace(self, **changes)
