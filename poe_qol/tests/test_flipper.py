"""Unit tests for the poe.ninja parser + flip scorer.

These are pure-data tests — no network, no Qt — so they're safe to run
in CI on any platform.
"""
from __future__ import annotations

import unittest

from poe_qol.economy.ninja import _parse_lines
from poe_qol.economy.flipper import (
    _liquidity_factor, _spread_factor, _stability_factor, _volume_factor,
    score_currency_flips,
)


def _mk_line(name, pay_value, pay_count, recv_value, recv_count,
             *, change=0.0, low_conf=False, details_id=None):
    block = {
        "currencyTypeName": name,
        "detailsId": details_id or name.lower().replace(" ", "-"),
        "pay":     {"value": pay_value,  "count": pay_count},
        "receive": {"value": recv_value, "count": recv_count},
    }
    series = {"data": [0, change / 2, change], "totalChange": change}
    key_pay = "lowConfidencePaySparkLine" if low_conf else "paySparkLine"
    key_rcv = "lowConfidenceReceiveSparkLine" if low_conf else "receiveSparkLine"
    block[key_pay] = series
    block[key_rcv] = series
    return block


class FactorTests(unittest.TestCase):

    def test_volume_factor_monotone_bounded(self):
        self.assertEqual(_volume_factor(0), 0.0)
        self.assertLess(_volume_factor(10), _volume_factor(100))
        self.assertLess(_volume_factor(100), 1.0)
        # Asymptotic: very high volume saturates near (but below) 1.
        self.assertGreater(_volume_factor(10_000), 0.98)

    def test_spread_factor_rejects_negative(self):
        self.assertEqual(_spread_factor(None), 0.0)
        self.assertEqual(_spread_factor(-5.0), 0.0)
        self.assertEqual(_spread_factor(0.0), 0.0)
        self.assertAlmostEqual(_spread_factor(25.0), 0.5, places=3)
        self.assertEqual(_spread_factor(75.0), 1.0)  # capped

    def test_stability_factor_symmetric(self):
        # +/- should penalise equally.
        self.assertAlmostEqual(_stability_factor(10.0),
                               _stability_factor(-10.0), places=6)
        # Larger magnitude => smaller factor.
        self.assertGreater(_stability_factor(0),
                           _stability_factor(20))
        # Missing data is neutral, not punitive.
        self.assertEqual(_stability_factor(None), 0.6)

    def test_liquidity_factor_lopsided_book(self):
        # Balanced book.
        self.assertEqual(_liquidity_factor(100, 100), 1.0)
        # 4× ratio is still within the knee.
        self.assertEqual(_liquidity_factor(100, 25), 1.0)
        # Beyond the knee it decays.
        self.assertLess(_liquidity_factor(100, 10), 1.0)
        # One-sided book is unusable for round-trips.
        self.assertEqual(_liquidity_factor(100, 0), 0.0)


class ParseAndScoreTests(unittest.TestCase):

    def test_excludes_chaos_and_low_confidence_by_default(self):
        raw = {"lines": [
            _mk_line("Chaos Orb", 1.0, 999, 1.0, 999),
            _mk_line("Obscure Shard", 0.5, 50, 3.0, 40, low_conf=True),
            _mk_line("Divine Orb", 1 / 160.0, 200, 165.0, 180, change=0.8),
        ], "currencyDetails": []}
        lines = list(_parse_lines(raw))
        ops = score_currency_flips(lines)
        names = [o.name for o in ops]
        self.assertNotIn("Chaos Orb", names)
        self.assertNotIn("Obscure Shard", names)
        self.assertIn("Divine Orb", names)

    def test_min_volume_filter(self):
        raw = {"lines": [
            _mk_line("Thin A", 0.1, 2, 0.12, 3),
            _mk_line("Thick B", 1 / 160.0, 50, 165.0, 40),
        ], "currencyDetails": []}
        ops = score_currency_flips(list(_parse_lines(raw)), min_volume=10)
        self.assertEqual([o.name for o in ops], ["Thick B"])

    def test_stable_outranks_volatile(self):
        """Two currencies with identical volume/spread but different 7d
        stability — the stable one should rank first."""
        raw = {"lines": [
            _mk_line("Stable", 1 / 100.0, 100, 105.0, 100, change=0.5),
            _mk_line("Volatile", 1 / 100.0, 100, 105.0, 100, change=25.0),
        ], "currencyDetails": []}
        ops = score_currency_flips(list(_parse_lines(raw)))
        self.assertEqual(ops[0].name, "Stable")
        self.assertGreater(ops[0].score, ops[1].score)

    def test_score_breakdown_in_range(self):
        raw = {"lines": [
            _mk_line("Divine", 1 / 160.0, 200, 165.0, 180, change=0.8),
        ], "currencyDetails": []}
        ops = score_currency_flips(list(_parse_lines(raw)))
        self.assertEqual(len(ops), 1)
        o = ops[0]
        for f in (o.volume_factor, o.spread_factor, o.stability_factor,
                  o.confidence_factor, o.liquidity_factor, o.score):
            self.assertGreaterEqual(f, 0.0)
            self.assertLessEqual(f, 1.0)


def _exchange(lines, items=None, primary="chaos"):
    items = items or [{"id": l["id"], "name": l["id"].title() + " Orb",
                       "image": f"/gen/{l['id']}.png",
                       "detailsId": l["id"] + "-orb"} for l in lines]
    return {"core": {"primary": primary, "secondary": "divine",
                     "rates": {"divine": 1 / 160.0}},
            "lines": lines, "items": items}


def _xline(id_, value, volume, change=0.0, *, pair=None, rate=None,
           history=True):
    line = {"id": id_, "primaryValue": value, "volumePrimaryValue": volume,
            "sparkline": {"data": [0, change / 2, change] if history else [],
                          "totalChange": change}}
    if pair:
        line["maxVolumeCurrency"] = pair
        line["maxVolumeRate"] = rate
    return line


class ExchangeParseTests(unittest.TestCase):
    """poe.ninja's current endpoint (/poe1/api/economy/exchange/...)."""

    def test_parses_names_values_volume_and_trade_id(self):
        raw = _exchange([_xline("divine", 160.0, 320000.0, change=-2.0),
                         _xline("alch", 0.5, 2000.0)])
        lines = {l.name: l for l in _parse_lines(raw)}
        div = lines["Divine Orb"]
        self.assertEqual(div.trade_id, "divine")
        self.assertEqual(div.details_id, "divine-orb")
        self.assertAlmostEqual(div.chaos_equivalent, 160.0)
        self.assertEqual(div.daily_volume, 2000)          # 320000c / 160c
        self.assertAlmostEqual(div.receive_change_7d, -2.0)
        self.assertTrue(div.icon.startswith("https://"))
        self.assertIsNone(div.pay_chaos)
        self.assertFalse(div.has_book)

    def test_cross_pair_gap_either_rate_direction(self):
        # Exalt trades mostly against divine. 1 exalt = 0.1 div = 16c
        # implied, vs 15c on the chaos market: a +6.7% gap.
        for rate in (0.1, 10.0):     # div per exalt, or exalt per div
            raw = _exchange([_xline("divine", 160.0, 1e6),
                             _xline("exalted", 15.0, 5e4,
                                    pair="divine", rate=rate)])
            ex = next(l for l in _parse_lines(raw) if l.trade_id == "exalted")
            self.assertAlmostEqual(ex.cross_gap_pct, 6.67, places=1)
            self.assertAlmostEqual(ex.edge_pct, ex.cross_gap_pct)

    def test_absurd_cross_rate_is_ignored(self):
        raw = _exchange([_xline("divine", 160.0, 1e6),
                         _xline("exalted", 15.0, 5e4, pair="divine", rate=5.0)])
        ex = next(l for l in _parse_lines(raw) if l.trade_id == "exalted")
        self.assertIsNone(ex.cross_gap_pct)

    def test_no_history_is_low_confidence(self):
        raw = _exchange([_xline("mirror", 50000.0, 1e5, history=False)])
        (line,) = list(_parse_lines(raw))
        self.assertTrue(line.low_confidence_receive)

    def test_exchange_lines_score_and_rank(self):
        raw = _exchange([
            _xline("divine", 160.0, 800000.0, change=1.0),   # deep, steady
            _xline("fusing", 0.8, 300.0, change=30.0),       # thin, volatile
            _xline("chaos", 1.0, 1e6),                       # the unit
        ])
        ops = score_currency_flips(list(_parse_lines(raw)))
        self.assertEqual([o.trade_id for o in ops], ["divine", "fusing"])
        self.assertGreater(ops[0].score, ops[1].score)
        for o in ops:
            self.assertGreaterEqual(o.score, 0.0)
            self.assertLessEqual(o.score, 1.0)

    def test_gap_boosts_score(self):
        raw = _exchange([
            _xline("divine", 160.0, 1e6),
            _xline("a", 15.0, 5e4, pair="divine", rate=0.1),   # 6.7% gap
            _xline("b", 16.0, 5e4, pair="divine", rate=0.1),   # no gap
        ])
        ops = {o.trade_id: o for o in score_currency_flips(
            list(_parse_lines(raw)))}
        self.assertGreater(ops["a"].score, ops["b"].score)


class LegacyConfidenceTests(unittest.TestCase):
    def test_empty_main_series_means_low_confidence(self):
        """poe.ninja sends both series; an empty main one is the signal."""
        line = _mk_line("Thin", 0.1, 20, 12.0, 20, change=3.0)
        line["receiveSparkLine"] = {"data": [], "totalChange": 0}
        line["lowConfidenceReceiveSparkLine"] = {"data": [1, 2, 3],
                                                 "totalChange": 3.0}
        (parsed,) = list(_parse_lines({"lines": [line]}))
        self.assertTrue(parsed.low_confidence_receive)
        self.assertAlmostEqual(parsed.receive_change_7d, 3.0)


class ClientFallbackTests(unittest.TestCase):
    def test_stale_cache_used_when_offline(self):
        import json, os, tempfile, time, urllib.error
        from pathlib import Path
        from poe_qol.economy.ninja import NinjaClient
        tmp = Path(tempfile.mkdtemp())
        c = NinjaClient(tmp, freshness_sec=1)
        cache = c._cache_path("Mirage", "Currency")
        cache.write_text(json.dumps(_exchange([_xline("divine", 160.0, 1e6)])))
        old = time.time() - 3600
        os.utime(cache, (old, old))

        def boom(*_a, **_k):
            raise urllib.error.URLError("offline")
        c._http_get = boom
        snap = c.fetch_currency("Mirage")
        self.assertTrue(snap.stale)
        self.assertEqual(snap.source, "exchange")
        self.assertEqual(snap.lines[0].name, "Divine Orb")

    def test_no_cache_and_offline_raises_friendly_error(self):
        import tempfile, urllib.error
        from pathlib import Path
        from poe_qol.economy.ninja import NinjaClient, NinjaError
        c = NinjaClient(Path(tempfile.mkdtemp()))

        def boom(*_a, **_k):
            raise urllib.error.URLError("offline")
        c._http_get = boom
        with self.assertRaises(NinjaError) as cm:
            c.fetch_currency("Mirage")
        self.assertIn("reach poe.ninja", str(cm.exception))



class FlipperUiTests(unittest.TestCase):
    """Offscreen Qt checks for the Flipper page fixes."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def _widget(self):
        import shutil, tempfile, time
        from pathlib import Path
        from poe_qol.core.config import ConfigStore
        from poe_qol.economy.ninja import CurrencySnapshot
        from poe_qol.ui.flipper_widget import FlipperWidget
        root = Path(__file__).resolve().parents[1]
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(root / "config", tmp / "config",
                        ignore=shutil.ignore_patterns("user.yaml"))
        opened = []
        w = FlipperWidget(ConfigStore(tmp), tmp, open_in_app=opened.append)
        w.refresh = lambda *a, **k: None          # no network
        raw = _exchange([_xline("divine", 1200.0, 2e6),
                         _xline("alch", 9.5, 4e4),
                         _xline("fusing", 85.0, 3e3)])
        w._on_fetch_done(CurrencySnapshot("Mirage", time.time(),
                                          list(_parse_lines(raw))))
        self.addCleanup(w.close)
        self.addCleanup(w.shutdown)
        return w, opened

    def test_price_column_sorts_numerically(self):
        from PySide6.QtCore import Qt
        w, _ = self._widget()
        w.table.sortItems(1, Qt.SortOrder.AscendingOrder)
        prices = [w.table.item(r, 1).text() for r in range(w.table.rowCount())]
        self.assertEqual(prices, ["9.50 c", "85.0 c", "1,200 c"])

    def test_lowering_min_volume_brings_rows_back(self):
        w, _ = self._widget()
        w.min_vol.setValue(100)       # fusing: 3000c / 85c ≈ 35 units
        self.assertEqual(w.table.rowCount(), 2)
        w.min_vol.setValue(10)
        self.assertEqual(w.table.rowCount(), 3)

    def test_double_click_opens_bulk_exchange_query(self):
        import json, urllib.parse
        w, opened = self._widget()
        w._open_trade_for_item(w.table.item(0, 0))
        self.assertEqual(len(opened), 1)
        url = opened[0]
        self.assertTrue(url.startswith(
            "https://www.pathofexile.com/trade/exchange/Mirage?q="), url)
        q = json.loads(urllib.parse.unquote(url.split("?q=", 1)[1]))
        self.assertEqual(q["exchange"]["have"], ["chaos"])
        self.assertIn(q["exchange"]["want"][0], {"divine", "alch", "fusing"})

    def test_shutdown_abandons_a_hung_fetch(self):
        import threading, time
        w, _ = self._widget()
        del w.refresh                             # use the real one
        release = threading.Event()
        self.addCleanup(release.set)              # let the daemon finish

        class _Hung:                              # offline: blocks on I/O
            def fetch_currency(self, league, *, force=False):
                release.wait(30)
                raise OSError("timed out")
        w._client = _Hung()
        w.refresh(force=True)
        worker = w._worker
        self.assertTrue(worker.isRunning())

        t0 = time.monotonic()
        w.shutdown()
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertTrue(worker.isFinished())
        self.assertIsNone(w._worker)

    def test_shutdown_stops_timers_and_blocks_refresh(self):
        w, _ = self._widget()
        del w.refresh
        w.auto_box.setCurrentIndex(w.auto_box.findData(5))
        self.assertTrue(w._auto_timer.isActive())
        w.shutdown()
        for t in (w._initial_timer, w._auto_timer, w._age_timer):
            self.assertFalse(t.isActive())
        w.refresh(force=True)
        self.assertIsNone(w._worker)
        w.shutdown()                              # idempotent


if __name__ == "__main__":
    unittest.main()
