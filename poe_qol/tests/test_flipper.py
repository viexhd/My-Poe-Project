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


if __name__ == "__main__":
    unittest.main()
