"""League picker shared by Map Search, Flipper, Pricer and the Trade
Browser.

The first entry is always "Latest (<league>)", which follows the newest
challenge league automatically (stored as ``auto`` in config). The rest
of the list comes from the trade site. A saved league that has ended,
or that *is* the latest, is switched back to automatic, so the app keeps
up with new leagues without anyone touching settings.
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QComboBox

from ..paths import app_root
from ..trade.leagues import AUTO, LeagueDirectory, is_auto

log = logging.getLogger("poe_qol.ui.league")


class LeagueService(QObject):
    """App-wide league list. ``updated`` fires (on the GUI thread) when
    a background fetch brings new data."""

    updated = Signal()

    def __init__(self, directory: LeagueDirectory) -> None:
        super().__init__()
        self.directory = directory
        self._busy = False

    @property
    def leagues(self) -> list[str]:
        return list(self.directory.leagues)

    @property
    def latest(self) -> str:
        return self.directory.latest

    def resolve(self, value) -> str:
        return self.directory.resolve(value)

    def start(self, *, force: bool = False) -> None:
        """Fetch the league list in the background (no-op while one runs)."""
        if self._busy:
            return
        self._busy = True

        def work() -> None:
            before = (self.directory.leagues[:], self.directory.latest)
            try:
                self.directory.refresh(force=force)
            finally:
                self._busy = False
            if (self.directory.leagues, self.directory.latest) != before:
                self.updated.emit()      # queued to the GUI thread

        threading.Thread(target=work, name="league-fetch", daemon=True).start()


_service: LeagueService | None = None


def league_service() -> LeagueService:
    global _service
    if _service is None:
        _service = LeagueService(
            LeagueDirectory(app_root() / "logs" / "leagues.json"))
    return _service


def current_league(cfg, key: str = "trade.league") -> str:
    """The league a config key points at, with ``auto`` resolved."""
    return league_service().resolve(cfg.get(key, AUTO))


class LeagueBox(QComboBox):
    """Dropdown bound to a config key. ``league()`` is the real league
    name; ``league_changed`` fires whenever that name changes."""

    league_changed = Signal(str)

    def __init__(self, cfg, key: str) -> None:
        super().__init__()
        self.cfg = cfg
        self.key = key
        raw = cfg.get(key)
        self._value = AUTO if is_auto(raw) else str(raw).strip()
        self._svc = league_service()
        self._effective = self._svc.resolve(self._value)
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self._rebuild()
        self.currentIndexChanged.connect(self._on_pick)
        self._svc.updated.connect(self._rebuild)

    # ---- public ----
    def value(self) -> str:
        """``auto`` or a fixed league name (what is saved in config)."""
        return self._value

    def league(self) -> str:
        return self._svc.resolve(self._value)

    # ---- internals ----
    def _persist(self) -> None:
        self.cfg.set(self.key, self._value)
        try:
            self.cfg.save_user_overrides([self.key])
        except Exception:
            log.exception("failed to save %s", self.key)

    def _rebuild(self) -> None:
        leagues = self._svc.leagues
        latest = self._svc.latest
        if (not is_auto(self._value) and leagues
                and (self._value == latest or self._value not in leagues)):
            log.info("%s: %r -> latest league (%s)", self.key, self._value, latest)
            self._value = AUTO
            self._persist()

        self.blockSignals(True)
        self.clear()
        self.addItem(f"Latest ({latest})", AUTO)
        for name in leagues:
            self.addItem(name, name)
        if not is_auto(self._value) and self.findData(self._value) < 0:
            self.addItem(self._value, self._value)
        self.setCurrentIndex(max(0, self.findData(self._value)))
        self.blockSignals(False)
        self.setToolTip(f"Using {self.league()}")
        self._emit_if_changed()

    def _on_pick(self, _idx: int) -> None:
        data = self.currentData()
        self._value = AUTO if is_auto(data) else str(data)
        self._persist()
        self.setToolTip(f"Using {self.league()}")
        self._emit_if_changed()

    def _emit_if_changed(self) -> None:
        eff = self.league()
        if eff != self._effective:
            self._effective = eff
            self.league_changed.emit(eff)
