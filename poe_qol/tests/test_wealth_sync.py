"""Stash sync from the Path of Exile account (Wealth tab).

No network: GGG's API and token endpoint are faked through the
``Transport`` seam, poe.ninja through a fake client. Response shapes
follow https://www.pathofexile.com/developer/docs/reference.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poe_qol.economy.pricing import PriceBook, build_price_book  # noqa: E402
from poe_qol.economy.stash_sync import (  # noqa: E402
    StashSync, csv_to_snapshot, flatten_tabs,
)
from poe_qol.economy.stash_valuation import links_of, price_item  # noqa: E402
from poe_qol.economy.wealth_history import (  # noqa: E402
    compute_range, hourly_series, item_changes,
)
from poe_qol.economy.wealth_store import (  # noqa: E402
    ItemLine, NewSnapshot, WealthStore,
)
from poe_qol.ggg.api import ApiError, AuthExpired, PoeApi  # noqa: E402
from poe_qol.ggg.http import Response  # noqa: E402
from poe_qol.ggg.oauth import (  # noqa: E402
    AUTHORIZE_URL, OAuthClient, OAuthError, PendingLogin, Token,
    authorize_url, challenge_for, make_verifier, user_agent,
)
from poe_qol.ggg.ratelimit import RateLimiter, parse_rules  # noqa: E402
from poe_qol.ggg.token_store import TokenStore  # noqa: E402


# ---------------------------------------------------------------- fakes

class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def ok(body, headers=None, status=200) -> Response:
    return Response(status, headers or {}, json.dumps(body).encode())


class FakeGGG:
    """Answers token and API requests like pathofexile.com would."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, bytes | None]] = []
        self.stashes = [
            {"id": "t1", "name": "Currency", "type": "CurrencyStash", "index": 0},
            {"id": "f1", "name": "Loot", "type": "Folder", "index": 1,
             "children": [{"id": "t2", "name": "Dump", "type": "PremiumStash",
                           "index": 0}]},
            {"id": "m1", "name": "Maps", "type": "MapStash", "index": 2,
             "children": [{"id": "m1s16", "name": "Tier 16", "type": "MapStash",
                           "index": 0}]},
        ]
        self.items = {
            "t1": [{"typeLine": "Divine Orb", "baseType": "Divine Orb",
                    "frameType": 5, "stackSize": 3},
                   {"typeLine": "Chaos Orb", "baseType": "Chaos Orb",
                    "frameType": 5, "stackSize": 150}],
            "t2": [{"name": "<<set:MS>><<set:M>><<set:S>>Headhunter",
                    "typeLine": "Leather Belt", "baseType": "Leather Belt",
                    "frameType": 3},
                   {"name": "Doom Knuckle", "typeLine": "Iron Ring",
                    "baseType": "Iron Ring", "frameType": 2}],
            "m1/m1s16": [{"typeLine": "Crimson Temple Map",
                          "baseType": "Crimson Temple Map", "frameType": 0,
                          "properties": [{"name": "Map Tier",
                                          "values": [["16", 0]]}]}],
        }
        self.fail_next_401 = False

    def __call__(self, method, url, headers, body) -> Response:
        self.calls.append((method, url, headers, body))
        parts = urllib.parse.urlsplit(url)
        if parts.path == "/oauth/token":
            form = urllib.parse.parse_qs(body.decode())
            if form["grant_type"] == ["refresh_token"]:
                return ok({"access_token": "acc2", "expires_in": 36000,
                           "token_type": "bearer", "refresh_token": "ref2",
                           "scope": "account:stashes"})
            return ok({"access_token": "acc1", "expires_in": 36000,
                       "token_type": "bearer", "refresh_token": "ref1",
                       "scope": "account:profile account:leagues account:stashes",
                       "username": "Exile#1234", "sub": "uuid-1"})
        if parts.path == "/oauth/token/revoke":
            return ok({})
        rl = {"X-Rate-Limit-Policy": "stash-request-limit",
              "X-Rate-Limit-Rules": "Account",
              "X-Rate-Limit-Account": "30:60:60",
              "X-Rate-Limit-Account-State": "1:60:0"}
        if self.fail_next_401:
            self.fail_next_401 = False
            return Response(401, rl, b"{}")
        p = urllib.parse.unquote(parts.path)
        if p == "/profile":
            return ok({"uuid": "uuid-1", "name": "Exile#1234"}, rl)
        if p == "/account/leagues":
            return ok({"leagues": [{"id": "Mirage"}, {"id": "Standard"}]}, rl)
        if p == "/stash/Mirage":
            return ok({"stashes": self.stashes}, rl)
        if p.startswith("/stash/Mirage/"):
            key = p[len("/stash/Mirage/"):]
            if key not in self.items:
                return Response(404, rl, b"{}")
            sid = key.split("/")[-1]
            return ok({"stash": {"id": sid, "items": self.items[key]}}, rl)
        return Response(404, rl, b"{}")


def book() -> PriceBook:
    b = PriceBook(league="Mirage")
    b.add_stack("Divine Orb", 200.0, "Currency")
    b.add_stack("Scarab of Stability", 2.5, "Scarab")
    b.add_item_lines("UniqueAccessory", [
        {"name": "Headhunter", "baseType": "Leather Belt", "chaosValue": 6000},
    ])
    b.add_item_lines("Map", [
        {"name": "Crimson Temple Map", "mapTier": 16, "chaosValue": 4},
    ])
    b.add_item_lines("SkillGem", [
        {"name": "Enlighten Support", "gemLevel": 4, "gemQuality": 0,
         "corrupted": False, "chaosValue": 900},
    ])
    b.add_item_lines("UniqueArmour", [
        {"name": "Tabula Rasa", "baseType": "Simple Robe", "links": 0, "chaosValue": 10},
        {"name": "Tabula Rasa", "baseType": "Simple Robe", "links": 6, "chaosValue": 15},
    ])
    return b


def api_for(fake: FakeGGG, token: Token | None = None) -> PoeApi:
    clock = FakeClock()
    oauth = OAuthClient("tc-test", contact="dev@example.invalid", transport=fake)
    tok = token or Token("acc1", time.time() + 3600, "ref1", "account:stashes",
                         "Exile#1234", "uuid-1")
    return PoeApi(oauth, tok, transport=fake,
                  limiter=RateLimiter(clock=clock, sleep=clock.sleep))


# ---------------------------------------------------------------- oauth

class OAuthTests(unittest.TestCase):
    def test_pkce_rfc7636_vector(self) -> None:
        self.assertEqual(challenge_for("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
                         "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
        v = make_verifier()
        self.assertTrue(43 <= len(v) <= 128)

    def test_authorize_url(self) -> None:
        url = authorize_url("my-app", redirect="http://127.0.0.1:5000/oauth/callback",
                            state="xyz", challenge="abc")
        self.assertTrue(url.startswith(AUTHORIZE_URL + "?"))
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(q["response_type"], ["code"])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["scope"], ["account:profile account:leagues account:stashes"])
        self.assertEqual(q["redirect_uri"], ["http://127.0.0.1:5000/oauth/callback"])

    def test_user_agent_format(self) -> None:
        self.assertRegex(user_agent("my-app", "me@x.invalid"),
                         r"^OAuth my-app/[\w.]+ \(contact: me@x\.invalid\)$")

    def test_missing_client_id_is_explained(self) -> None:
        with self.assertRaises(OAuthError):
            OAuthClient("")

    def test_loopback_login_end_to_end(self) -> None:
        fake = FakeGGG()
        oauth = OAuthClient("tc-test", transport=fake)
        pending = PendingLogin.start("tc-test")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(pending.url).query)
        redirect = q["redirect_uri"][0]
        self.assertTrue(redirect.startswith("http://127.0.0.1:"))
        # the browser follows pathofexile.com's redirect
        with urllib.request.urlopen(
                f"{redirect}?code=CODE1&state={q['state'][0]}", timeout=5) as r:
            self.assertIn(b"Connected", r.read())
        tok = pending.finish(oauth, timeout=5)
        self.assertEqual(tok.access_token, "acc1")
        self.assertEqual(tok.username, "Exile#1234")
        form = urllib.parse.parse_qs(fake.calls[-1][3].decode())
        self.assertEqual(form["code"], ["CODE1"])
        self.assertEqual(form["code_verifier"], [pending.verifier])
        self.assertEqual(form["redirect_uri"], [redirect])
        self.assertNotIn("client_secret", form)

    def test_state_mismatch_is_rejected(self) -> None:
        pending = PendingLogin.start("tc-test")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(pending.url).query)
        urllib.request.urlopen(f"{q['redirect_uri'][0]}?code=X&state=evil",
                               timeout=5).read()
        with self.assertRaises(OAuthError):
            pending.finish(OAuthClient("tc-test", transport=FakeGGG()), timeout=5)

    def test_denied_consent(self) -> None:
        pending = PendingLogin.start("tc-test")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(pending.url).query)
        urllib.request.urlopen(f"{q['redirect_uri'][0]}?error=access_denied"
                               f"&state={q['state'][0]}", timeout=5).read()
        with self.assertRaises(OAuthError) as cm:
            pending.finish(OAuthClient("tc-test", transport=FakeGGG()), timeout=5)
        self.assertIn("access_denied", str(cm.exception))

    def test_token_store_roundtrip(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="tc_tok_"))
        store = TokenStore(tmp / "t.bin")
        self.assertIsNone(store.load())
        store.save(Token("a", 123.0, "r", "account:stashes", "Exile#1", "u"))
        got = store.load()
        self.assertEqual((got.access_token, got.username), ("a", "Exile#1"))
        if os.name == "posix":
            self.assertEqual((tmp / "t.bin").stat().st_mode & 0o777, 0o600)
        store.clear()
        self.assertIsNone(store.load())


# ---------------------------------------------------------------- limits

class RateLimitTests(unittest.TestCase):
    def test_parse_rules(self) -> None:
        r = parse_rules("30:300:300, 10:10:60")
        self.assertEqual([(x.hits, x.period, x.penalty) for x in r],
                         [(30, 300.0, 300.0), (10, 10.0, 60.0)])

    def test_stays_under_learned_limit(self) -> None:
        clock = FakeClock()
        rl = RateLimiter(clock=clock, sleep=clock.sleep)
        hdr = {"X-Rate-Limit-Policy": "p", "X-Rate-Limit-Rules": "Account",
               "X-Rate-Limit-Account": "4:10:60",
               "X-Rate-Limit-Account-State": "1:10:0"}
        rl.acquire("stash")
        rl.update("stash", hdr)
        self.assertEqual(rl.wait_time("stash"), 0)
        rl.acquire("stash"); rl.acquire("stash")
        # 3 sent, limit 4 minus one request of headroom → must wait
        self.assertGreater(rl.wait_time("stash"), 0)
        start = clock.t
        rl.acquire("stash")
        self.assertGreaterEqual(clock.t - start, 9.0)

    def test_restriction_and_retry_after(self) -> None:
        clock = FakeClock()
        rl = RateLimiter(clock=clock, sleep=clock.sleep)
        rl.update("stash", {"X-Rate-Limit-Policy": "p",
                            "X-Rate-Limit-Rules": "Ip",
                            "X-Rate-Limit-Ip": "10:10:60",
                            "X-Rate-Limit-Ip-State": "11:10:60"})
        self.assertAlmostEqual(rl.wait_time("stash"), 60, delta=0.01)
        rl2 = RateLimiter(clock=clock, sleep=clock.sleep)
        rl2.update("x", {"Retry-After": "17"}, status=429)
        self.assertAlmostEqual(rl2.wait_time("x"), 17, delta=0.01)


# ---------------------------------------------------------------- api

class ApiTests(unittest.TestCase):
    def test_list_and_get(self) -> None:
        fake = FakeGGG()
        api = api_for(fake)
        tabs = api.list_stashes("Mirage")
        self.assertEqual(len(tabs), 3)
        st = api.get_stash("Mirage", "m1", "m1s16")
        self.assertEqual(st["items"][0]["typeLine"], "Crimson Temple Map")
        _m, url, headers, _b = fake.calls[-1]
        self.assertEqual(url, "https://api.pathofexile.com/stash/Mirage/m1/m1s16")
        self.assertEqual(headers["Authorization"], "Bearer acc1")
        self.assertTrue(headers["User-Agent"].startswith("OAuth tc-test/"))

    def test_realm_in_path(self) -> None:
        fake = FakeGGG()
        try:
            api_for(fake).list_stashes("Mirage", "xbox")
        except ApiError:
            pass
        self.assertEqual(fake.calls[-1][1],
                         "https://api.pathofexile.com/stash/xbox/Mirage")

    def test_expired_token_is_refreshed(self) -> None:
        fake = FakeGGG()
        saved: list[Token] = []
        api = api_for(fake, Token("old", time.time() - 10, "ref1"))
        api.on_token = saved.append
        api.profile()
        self.assertEqual(saved[-1].access_token, "acc2")
        self.assertEqual(saved[-1].refresh_token, "ref2")
        self.assertEqual(fake.calls[-1][2]["Authorization"], "Bearer acc2")

    def test_401_refreshes_once_then_gives_up(self) -> None:
        fake = FakeGGG()
        fake.fail_next_401 = True
        api = api_for(fake)
        self.assertEqual(api.profile()["name"], "Exile#1234")
        api2 = api_for(fake, Token("acc", time.time() + 3600, None))
        fake.fail_next_401 = True
        with self.assertRaises(AuthExpired):
            api2.profile()


# ---------------------------------------------------------------- pricing

class ValuationTests(unittest.TestCase):
    def test_stackable(self) -> None:
        p = price_item({"typeLine": "Divine Orb", "baseType": "Divine Orb",
                        "frameType": 5, "stackSize": 4}, book())
        self.assertEqual((p.name, p.category, p.quantity), ("Divine Orb", "Currency", 4))
        self.assertAlmostEqual(p.total_chaos, 800)

    def test_unique_links(self) -> None:
        six = [{"group": 0}] * 6
        p = price_item({"name": "Tabula Rasa", "typeLine": "Simple Robe",
                        "baseType": "Simple Robe", "frameType": 3,
                        "sockets": six}, book())
        self.assertEqual(p.unit_chaos, 15)
        p = price_item({"name": "Tabula Rasa", "baseType": "Simple Robe",
                        "frameType": 3, "sockets": [{"group": 0}, {"group": 1}]},
                       book())
        self.assertEqual(p.unit_chaos, 10)
        self.assertEqual(links_of({"sockets": six}), 6)

    def test_map_gem_and_unpriced(self) -> None:
        m = price_item({"typeLine": "Crimson Temple Map", "baseType": "Crimson Temple Map",
                        "frameType": 0,
                        "properties": [{"name": "Map Tier", "values": [["16", 0]]}]},
                       book())
        self.assertEqual((m.name, m.unit_chaos), ("Crimson Temple Map (T16)", 4))
        g = price_item({"typeLine": "Enlighten Support", "frameType": 4,
                        "properties": [{"name": "Level", "values": [["4 (Max)", 0]]}]},
                       book())
        self.assertEqual(g.unit_chaos, 900)
        r = price_item({"name": "Doom Knuckle", "typeLine": "Iron Ring",
                        "frameType": 2}, book())
        self.assertIsNone(r.unit_chaos)

    def test_price_book_tolerates_missing_types(self) -> None:
        class FakeNinja:
            def fetch_currency(self, league, kind="Currency", force=False):
                if kind != "Currency":
                    raise RuntimeError("404")
                from poe_qol.economy.ninja import CurrencyLine, CurrencySnapshot
                line = CurrencyLine("Divine Orb", "divine-orb", None, 190.0, 0,
                                    None, None, 0, None, False, False)
                return CurrencySnapshot(league, time.time(), [line])

            def fetch_item_lines(self, league, kind, force=False):
                if kind == "Map":
                    return [{"name": "Strand Map", "mapTier": 16,
                             "chaosValue": 2}], time.time(), False
                raise RuntimeError("404")

        b = build_price_book(FakeNinja(), "Mirage")
        self.assertEqual(b.chaos_per_divine, 190.0)
        self.assertEqual(b.map_price("Strand Map", 16), 2)
        self.assertIn("Scarab", b.missing_types)


# ---------------------------------------------------------------- sync

class SyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = WealthStore(":memory:")

    def test_flatten_tabs(self) -> None:
        tabs = flatten_tabs(FakeGGG().stashes)
        self.assertEqual([(t.id, t.parent_id, t.label) for t in tabs], [
            ("t1", None, "Currency"),
            ("t2", None, "Loot / Dump"),          # folder child: own id
            ("m1s16", "m1", "Maps / Tier 16"),    # map section: parent/child
        ])

    def test_sync_prices_and_saves(self) -> None:
        fake = FakeGGG()
        sync = StashSync(api_for(fake), self.store, lambda league: book())
        steps: list[str] = []
        res = sync.run(account="Exile#1234", league="Mirage",
                       progress=lambda m, a, b: steps.append(m))
        # 3 divines (600) + 150 chaos + Headhunter 6000 + T16 map 4
        self.assertAlmostEqual(res.total_chaos, 6754)
        self.assertEqual(res.unpriced, 1)
        self.assertEqual(res.tabs, 3)
        self.assertTrue(any("Tab 3/3" in s for s in steps))
        head = self.store.latest("Exile#1234", "Mirage")
        self.assertAlmostEqual(head.total_chaos, 6754)
        self.assertEqual(head.chaos_per_divine, 200.0)
        names = {i.name for i in self.store.items(head.id)}
        self.assertEqual(names, {"Divine Orb", "Chaos Orb", "Headhunter",
                                 "Crimson Temple Map (T16)"})

    def test_sync_only_selected_tabs(self) -> None:
        sync = StashSync(api_for(FakeGGG()), self.store, lambda league: book())
        res = sync.run(account="a", league="Mirage", tab_ids={"t1"})
        self.assertEqual(res.tabs, 1)
        self.assertAlmostEqual(res.total_chaos, 750)

    def test_auth_failure_aborts(self) -> None:
        fake = FakeGGG()
        sync = StashSync(api_for(fake, Token("x", time.time() + 999, None)),
                         self.store, lambda league: book())
        fake.fail_next_401 = True
        with self.assertRaises(AuthExpired):
            sync.run(account="a", league="Mirage")
        self.assertIsNone(self.store.latest("a", "Mirage"))


# ---------------------------------------------------------------- history

def _snap(store, at, items, rate=200.0, account="a", league="L"):
    return store.add(NewSnapshot(
        account=account, league=league, taken_at=at, chaos_per_divine=rate,
        items=[ItemLine("t", "Tab", n, "Currency", q, u, q * u) for n, q, u in items]))


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.s = WealthStore(":memory:")
        h = 3600.0
        _snap(self.s, 0 * h, [("Divine Orb", 10, 200)])                      # 2000
        _snap(self.s, 1 * h, [("Divine Orb", 11, 200)])                      # 2200
        _snap(self.s, 2 * h, [("Divine Orb", 11, 200), ("Mirror", 1, 1000)])  # 3200
        _snap(self.s, 4 * h, [("Divine Orb", 14, 250), ("Mirror", 1, 1000)],
              rate=250)                                                       # 4500

    def test_range_uses_snapshot_at_or_before_start(self) -> None:
        r = compute_range(self.s, "a", "L", 1.5 * 3600, 4 * 3600)
        self.assertEqual(r.start.taken_at, 3600)          # newest ≤ start
        self.assertEqual(r.end.taken_at, 4 * 3600)
        self.assertAlmostEqual(r.delta_chaos, 2300)
        self.assertAlmostEqual(r.hours, 3)
        # one rate (the end's, 250) for both ends
        self.assertAlmostEqual(r.to_div(r.delta_chaos), 9.2)
        self.assertAlmostEqual(r.reading().divine_per_hour, 2300 / 3 / 250)

    def test_all_history_and_override_rate(self) -> None:
        r = compute_range(self.s, "a", "L", None, 10 * 3600, chaos_per_divine=100)
        self.assertEqual(r.start.taken_at, 0)
        self.assertAlmostEqual(r.to_div(r.delta_chaos), 25)
        self.assertEqual(len(r.series), 4)

    def test_needs_two_snapshots(self) -> None:
        r = compute_range(self.s, "a", "L", -10, 10)
        self.assertFalse(r.ok)
        self.assertIsNone(r.reading().divine_per_hour)
        empty = compute_range(self.s, "a", "Other", None, 10)
        self.assertIn("No syncs", empty.message)

    def test_item_changes_and_hourly(self) -> None:
        r = compute_range(self.s, "a", "L", 0, 4 * 3600)
        ch = {c.name: c for c in item_changes(self.s, r.start, r.end)}
        self.assertEqual(ch["Divine Orb"].qty_delta, 4)
        self.assertAlmostEqual(ch["Divine Orb"].value_delta, 1500)
        self.assertEqual(ch["Mirror"].qty_start, 0)
        hs = hourly_series(r.series)
        self.assertEqual([round(v) for _t, v in hs], [200, 1000, 650])

    def test_delete_history(self) -> None:
        self.assertEqual(self.s.delete_history("a", "L"), 4)
        self.assertIsNone(self.s.latest("a", "L"))

    def test_csv_import(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="tc_csv_"))
        p = tmp / "Wealthy-Exile-export-11_23_2026 2_05.csv"
        p.write_text('"Name","Tab","Quantity","Price","Total"\n'
                     '"Divine Orb","1","2","180","360"\n'
                     '"Scarab, of Stability","Scarabs","4","2.5","10"\n',
                     encoding="utf-8")
        snap = csv_to_snapshot(p, account="a", league="L")
        self.assertEqual(snap.chaos_per_divine, 180)
        self.assertAlmostEqual(snap.total_chaos, 370)
        self.assertEqual({i.name for i in snap.items},
                         {"Divine Orb", "Scarab, of Stability"})


# ---------------------------------------------------------------- UI

def _qapp():
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    return QApplication.instance() or QApplication([])


class WealthTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _qapp()

    def _widget(self, connected: bool):
        import shutil
        from poe_qol.core.config import ConfigStore
        from poe_qol.economy.wealth_service import WealthService
        from poe_qol.ui.wealth_widget import WealthWidget
        tmp = Path(tempfile.mkdtemp(prefix="tc_wtab_"))
        shutil.copytree(ROOT / "config", tmp / "config",
                        ignore=shutil.ignore_patterns("user.yaml"))
        cfg = ConfigStore(tmp)
        cfg.set("wealth.league", "Mirage")
        cfg.set("wealth.range", "6h")
        cfg.set("wealth.auto_sync", False)
        svc = WealthService(tmp / "data", client_id="tc-test", transport=FakeGGG())
        if connected:
            svc._save_token(Token("acc1", time.time() + 3600, "ref1",
                                  "account:stashes", "Exile#1234", "uuid-1"))
        now = time.time()
        _snap(svc.store, now - 2 * 3600, [("Divine Orb", 10, 200)],
              account=svc.account or "local", league="Mirage")
        _snap(svc.store, now - 60, [("Divine Orb", 14, 200)],
              account=svc.account or "local", league="Mirage")
        return WealthWidget(cfg, service=svc), svc

    def test_cards_chart_table(self) -> None:
        w, svc = self._widget(connected=True)
        try:
            # +800 c in ~2 h at 200 c/div = ~2 div/h
            self.assertIn("div/h", w.overlay_headline())
            self.assertTrue(w.overlay_headline().startswith("2.0"))
            self.assertIn("+4.00 div", w.change_card.value.text())
            self.assertEqual(len(w.chart.points()), 2)
            w.hourly_btn.click()
            self.assertEqual(len(w.chart.points()), 1)
            self.assertEqual(w.table.rowCount(), 1)
            self.assertEqual(w.table.item(0, 5).text(), "+4")
            self.assertIn("Exile#1234", w.account_label.text())
            self.assertEqual(w.connect_btn.text(), "Disconnect")
            self.assertTrue(w.sync_btn.isEnabled())
            self.assertEqual(w.interval_box.currentData(), 60)
            self.assertGreaterEqual(min(w.interval_box.itemData(i)
                                        for i in range(w.interval_box.count())), 15)
        finally:
            w.shutdown()
            w.close()

    def test_disconnected_state(self) -> None:
        w, svc = self._widget(connected=False)
        try:
            self.assertEqual(w.connect_btn.text(), "Connect account")
            self.assertFalse(w.sync_btn.isEnabled())
            self.assertFalse(w.sync_now())
        finally:
            w.shutdown()
            w.close()

    def test_sync_runs_in_background(self) -> None:
        from PySide6.QtCore import QCoreApplication, QEvent
        w, svc = self._widget(connected=True)
        try:
            svc.price_book = lambda league, **_k: book()
            before = len(svc.store.snapshots(svc.account, "Mirage"))
            self.assertTrue(w.sync_now(manual=True))
            self.assertTrue(w._task.wait(10_000))
            # deliver the worker's queued signals only; a full event loop
            # would also fire other test windows' timers (Flipper fetch)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
            self.assertEqual(len(svc.store.snapshots(svc.account, "Mirage")), before + 1)
            self.assertIn("Synced 3 tabs", w.status_label.text())
            # manual cooldown
            self.assertFalse(w.sync_now(manual=True))
        finally:
            w.shutdown()
            w.close()


if __name__ == "__main__":
    unittest.main()
