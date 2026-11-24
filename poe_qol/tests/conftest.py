"""Keep the test suite offline and independent of the machine's state.

* The league picker normally reads the saved league list from
  ``logs/leagues.json`` and fetches a fresh one from the trade site.
  Tests get an empty, never-fetching league service instead, so results
  don't depend on the network, on test order, or on what league is live.
* The Wealth tab keeps its stash history and sign-in token in the
  per-user data folder. Every test run gets a throwaway one.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["TWICE_CORRUPTED_DATA"] = tempfile.mkdtemp(prefix="tc_data_")


@pytest.fixture(autouse=True)
def _offline_league_service(monkeypatch):
    import poe_qol.ui.league as UL
    from poe_qol.trade.leagues import LeagueDirectory
    svc = UL.LeagueService(LeagueDirectory(
        Path(tempfile.mkdtemp()) / "leagues.json"))
    monkeypatch.setattr(svc, "start", lambda **_k: None)
    monkeypatch.setattr(UL, "_service", svc)
    yield
