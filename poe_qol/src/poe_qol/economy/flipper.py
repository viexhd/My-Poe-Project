"""Rank currencies by bulk-flip attractiveness.

The user's framing: *volume/day and 7-day value graph are the most
important aspects*. We combine them into a single composite score
rather than forcing the user to eyeball four columns:

    score = volume_factor * spread_factor * stability_factor
          * confidence_factor * liquidity_factor

where:

    volume_factor     — log-scaled daily trade count. A currency with
                        1000 trades/day is *not* 1000× better than 10/
                        day for bulk flipping; diminishing returns kick
                        in fast.
    spread_factor     — (receive - pay) / pay, clamped to [0, 0.5].
                        Negative spreads (bid above ask, usually stale
                        data) are dropped.
    stability_factor  — inverse of abs(7-day change). A rock-steady
                        price is safer to flip than something moving
                        ±30%. Penalises both directions — you don't
                        want to get caught holding a dumping currency,
                        and a pumping one means listings are stale.
    confidence_factor — 1.0 if poe.ninja has high-confidence data on
                        both sides, else 0.35. Low-confidence flips
                        are mostly noise.
    liquidity_factor  — penalises lopsided books. If pay_count and
                        receive_count differ by >5x the thinner side
                        bottlenecks the flip.

The individual factors stay in [0, 1] so the composite score is
interpretable (1.0 ≈ "perfect flip"). Users see both the score and
the contributing factors in tooltips.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .ninja import CurrencyLine


# Tunables. Exposed so the UI / config can override later.
_VOL_HALF = 80          # volume at which volume_factor = 0.5
_SPREAD_CAP = 0.50      # 50%+ spread contributes the same (probably wrong anyway)
_STABILITY_HALF = 10.0  # abs(7d change) at which stability_factor = 0.5
_LOW_CONF_MULT = 0.35
_LIQUIDITY_RATIO_KNEE = 5.0


@dataclass
class FlipOpportunity:
    line: CurrencyLine

    # Individual components (each in [0,1] except spread_pct which is %).
    volume_factor: float
    spread_factor: float
    stability_factor: float
    confidence_factor: float
    liquidity_factor: float
    score: float

    # Convenience accessors for UI columns.
    @property
    def name(self) -> str: return self.line.name
    @property
    def spread_pct(self) -> float | None: return self.line.spread_pct
    @property
    def spread_chaos(self) -> float | None: return self.line.spread_chaos
    @property
    def volume(self) -> int: return self.line.daily_volume
    @property
    def change_7d(self) -> float | None:
        # Report whichever side has data; prefer receive (the sell side
        # is what traders watch).
        return (self.line.receive_change_7d
                if self.line.receive_change_7d is not None
                else self.line.pay_change_7d)
    @property
    def chaos_value(self) -> float | None: return self.line.chaos_equivalent
    @property
    def low_confidence(self) -> bool:
        return (self.line.low_confidence_pay
                or self.line.low_confidence_receive)


def _volume_factor(vol: int) -> float:
    """0 at vol=0, 0.5 at vol=_VOL_HALF, →1 asymptotically.

    Closed form: vol / (vol + half). Cheap, monotonic, well-behaved.
    """
    if vol <= 0:
        return 0.0
    return vol / (vol + _VOL_HALF)


def _spread_factor(spread_pct: float | None) -> float:
    if spread_pct is None or spread_pct <= 0:
        return 0.0
    # spread_pct is in percent; compare to cap in percent.
    cap = _SPREAD_CAP * 100.0
    if spread_pct >= cap:
        return 1.0
    return spread_pct / cap


def _stability_factor(change_pct: float | None) -> float:
    if change_pct is None:
        # No signal => treat as neutral rather than penalising.
        return 0.6
    mag = abs(change_pct)
    # 1 / (1 + mag/half): half at mag=_STABILITY_HALF.
    return 1.0 / (1.0 + mag / _STABILITY_HALF)


def _liquidity_factor(pay_count: int, recv_count: int) -> float:
    thin = min(pay_count, recv_count)
    fat = max(pay_count, recv_count)
    if fat == 0:
        return 0.0
    if thin == 0:
        # One-sided book — can't round-trip.
        return 0.0
    ratio = fat / thin
    if ratio <= _LIQUIDITY_RATIO_KNEE:
        return 1.0
    # Asymptotic decay past the knee: ratio 10 → ~0.5, ratio 25 → ~0.2.
    return _LIQUIDITY_RATIO_KNEE / ratio


def _confidence_factor(line: CurrencyLine) -> float:
    if line.low_confidence_pay or line.low_confidence_receive:
        return _LOW_CONF_MULT
    return 1.0


def _score_one(line: CurrencyLine) -> FlipOpportunity | None:
    if line.chaos_equivalent is None or line.pay_chaos is None:
        return None
    vol = _volume_factor(line.daily_volume)
    # Use the receive-side change as the stability proxy; traders care
    # about the sell price more than the bid.
    stab = _stability_factor(line.receive_change_7d
                             if line.receive_change_7d is not None
                             else line.pay_change_7d)
    spread = _spread_factor(line.spread_pct)
    conf = _confidence_factor(line)
    liq = _liquidity_factor(line.pay_count, line.receive_count)

    score = vol * spread * stab * conf * liq
    return FlipOpportunity(
        line=line,
        volume_factor=vol,
        spread_factor=spread,
        stability_factor=stab,
        confidence_factor=conf,
        liquidity_factor=liq,
        score=score,
    )


def score_currency_flips(lines: Iterable[CurrencyLine], *,
                         min_volume: int = 10,
                         include_low_confidence: bool = False,
                         exclude: tuple[str, ...] = ("Chaos Orb",),
                         ) -> list[FlipOpportunity]:
    """Score and filter. Returns a list sorted by ``score`` desc.

    Defaults match the bulk-flipper brief: at least 10 daily trades,
    high-confidence only, and Chaos Orb itself excluded (it's the
    unit — flipping it against itself is nonsense).
    """
    skip = {s.lower() for s in exclude}
    out: list[FlipOpportunity] = []
    for l in lines:
        if l.name.lower() in skip:
            continue
        if l.daily_volume < min_volume:
            continue
        if not include_low_confidence and (
                l.low_confidence_pay or l.low_confidence_receive):
            continue
        op = _score_one(l)
        if op is None:
            continue
        if not math.isfinite(op.score):
            continue
        out.append(op)
    out.sort(key=lambda o: o.score, reverse=True)
    return out
