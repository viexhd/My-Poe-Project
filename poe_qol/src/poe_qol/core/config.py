"""Config loading, profile merging, and hot-reload.

Contract:
    * default.yaml is the authoritative schema.
    * A profile file may override any subset of keys (deep-merged).
    * Nothing else in the codebase may read YAML directly – they all go
      through ConfigStore.get().
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class ConfigStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.default_path = self.root / "config" / "default.yaml"
        self.profile_dir = self.root / "config" / "profiles"
        # Per-user overrides written by the UI (calibration, last-used
        # slot selection, etc.). Layered on top of default + profile so
        # calibration survives restarts without touching the shared
        # profile file.
        self.user_overrides_path = self.root / "config" / "user.yaml"
        self._data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        default = yaml.safe_load(self.default_path.read_text()) or {}
        profile_name = default.get("app", {}).get("profile")
        if profile_name:
            p = self.profile_dir / f"{profile_name}.yaml"
            if p.exists():
                override = yaml.safe_load(p.read_text()) or {}
                default = _deep_merge(default, override)
        if self.user_overrides_path.exists():
            user = yaml.safe_load(self.user_overrides_path.read_text()) or {}
            default = _deep_merge(default, user)
        self._data = default

    # dot-path getter: cfg.get("macros.life_flask.key")
    def get(self, path: str, default=None) -> Any:
        cur: Any = self._data
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, path: str, value: Any) -> None:
        parts = path.split(".")
        cur = self._data
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    def save_profile(self, name: str) -> None:
        """Write current in-memory config back to a profile file."""
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        path = self.profile_dir / f"{name}.yaml"
        path.write_text(yaml.safe_dump(self._data, sort_keys=False))

    def save_user_overrides(self, paths: list[str]) -> None:
        """Persist the current values of the given dot-paths to
        ``config/user.yaml`` so they survive a restart. Merges into
        any existing overrides without dropping unrelated keys."""
        existing: dict[str, Any] = {}
        if self.user_overrides_path.exists():
            existing = yaml.safe_load(self.user_overrides_path.read_text()) or {}
        for path in paths:
            value = self.get(path)
            cur = existing
            parts = path.split(".")
            for p in parts[:-1]:
                nxt = cur.get(p)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[p] = nxt
                cur = nxt
            cur[parts[-1]] = value
        self.user_overrides_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_overrides_path.write_text(
            yaml.safe_dump(existing, sort_keys=False))

    @property
    def data(self) -> dict[str, Any]:
        return self._data
