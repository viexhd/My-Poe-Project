"""Clipboard-driven item pricer.

Flow:
    1. user Ctrl+C on an item in PoE
    2. QClipboard.dataChanged → PricerWidget parses the text
    3. client queries pathofexile.com/api/trade for comparable listings
    4. UI shows floor + top listings + a "stale-floor" insight flagging
       inactive sellers so the user's real-world price target isn't
       anchored to dead listings.

Public API:
    :class:`ParsedItem` — structured clipboard parse.
    :func:`parse_item`  — text → ParsedItem, or ``None`` if non-item text.
    :class:`TradeClient` — thin stdlib HTTP client for /api/trade.
    :func:`price_item`  — ParsedItem → :class:`PriceResult`.
"""
from .parser import ParsedItem, Category, parse_item  # noqa: F401
from .search import PriceResult, Listing, TradeClient, price_item  # noqa: F401
