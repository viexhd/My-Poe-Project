"""Which leagues exist, and which one is the latest.

Source: the trade site's public league list,
``https://www.pathofexile.com/api/trade/data/leagues``::

    {"result": [{"id": "Covens", "realm": "pc", "text": "Covens"},
                {"id": "Hardcore Covens", "realm": "pc", ...},
                {"id": "Standard", ...}, {"id": "Hardcore", ...}, ...]}

The current challenge league (softcore, trade) is the one players
mean by "the league", so that is :func:`pick_latest`. The list is cached
to ``logs/leagues.json`` for 6 hours; offline, the last saved list is
used, and with nothing saved the latest league falls back to Standard.

"auto" (or an empty value) in config means "always the latest league".
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("poe_qol.trade.leagues")

LEAGUES_URL = "https://www.pathofexile.com/api/trade/data/leagues"
AUTO = "auto"
FALLBACK = "Standard"
FRESH_SEC = 6 * 3600

# Same browser-like headers the trade search uses (Cloudflare rejects
# bare Python user agents).
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
}

_PERMANENT = {"standard", "hardcore"}
_VARIANT_MARKERS = ("hardcore", "hc ", "ssf", "solo self-found", "ruthless")


def is_auto(value) -> bool:
    return value is None or str(value).strip().lower() in ("", AUTO)


def parse_leagues(raw: dict) -> list[str]:
    """League ids for the PC realm, in the trade site's order."""
    out: list[str] = []
    for item in (raw or {}).get("result") or []:
        if not isinstance(item, dict):
            continue
        realm = item.get("realm", "pc")
        lid = item.get("id") or item.get("text")
        if realm == "pc" and isinstance(lid, str) and lid and lid not in out:
            out.append(lid)
    return out


def pick_latest(leagues: list[str]) -> str:
    """The current softcore trade challenge league, else Standard."""
    for name in leagues:
        low = name.lower()
        if low in _PERMANENT:
            continue
        if any(m in low for m in _VARIANT_MARKERS):
            continue
        return name
    return FALLBACK


class LeagueDirectory:
    """Fetches and caches the league list. Thread-safe enough for one
    background fetch at a time; reads are plain attribute reads."""

    def __init__(self, cache_file: Path, *, timeout: float = 10.0) -> None:
        self.cache_file = Path(cache_file)
        self.timeout = timeout
        self.leagues: list[str] = []
        self.fetched_at = 0.0
        self._load_cache()

    @property
    def latest(self) -> str:
        return pick_latest(self.leagues)

    def resolve(self, value) -> str:
        """Config value → actual league name ("auto" → latest)."""
        return self.latest if is_auto(value) else str(value).strip()

    def _load_cache(self) -> None:
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            self.leagues = [x for x in data.get("leagues", []) if isinstance(x, str)]
            self.fetched_at = float(data.get("fetched_at", 0))
        except (OSError, ValueError, AttributeError):
            pass

    def _save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(
                {"leagues": self.leagues, "fetched_at": self.fetched_at}),
                encoding="utf-8")
        except OSError:
            log.warning("could not save league cache %s", self.cache_file)

    def is_fresh(self) -> bool:
        return bool(self.leagues) and time.time() - self.fetched_at < FRESH_SEC

    def refresh(self, *, force: bool = False) -> list[str]:
        """Fetch the list (unless the cache is fresh). Never raises:
        on failure the previous list is kept."""
        if not force and self.is_fresh():
            return self.leagues
        try:
            req = urllib.request.Request(LEAGUES_URL, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                leagues = parse_leagues(json.loads(r.read().decode("utf-8")))
        except Exception as e:  # noqa: BLE001
            log.warning("league list unavailable (%s); using %s", e,
                        "saved list" if self.leagues else FALLBACK)
            return self.leagues
        if leagues:
            self.leagues = leagues
            self.fetched_at = time.time()
            self._save_cache()
            log.info("leagues: %s (latest: %s)", ", ".join(leagues[:6]),
                     self.latest)
        return self.leagues
