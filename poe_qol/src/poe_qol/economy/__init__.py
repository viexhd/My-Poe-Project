"""Economy analysis: poe.ninja data fetch + flip opportunity scoring.

Surfaced in the UI as the "Flipper" tab. Pure-Python (stdlib urllib);
no extra dependencies beyond what poe_qol already uses.
"""
from .ninja import NinjaClient, CurrencyLine, CurrencySnapshot  # noqa: F401
from .flipper import FlipOpportunity, score_currency_flips  # noqa: F401
