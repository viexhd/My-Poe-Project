"""Trade-site query client for the clipboard pricer.

Two endpoints, chosen by item category:

    * Bulk exchange  (``/api/trade/exchange/<league>``)
      Currency, fragments, scarabs, div cards, essences — anything
      stackable that trades by the stack. Returns listings already
      denominated in ``have`` (defaults to chaos).

    * Search         (``/api/trade/search/<league>`` → ``/fetch``)
      Uniques, maps, gems, equipment. Query by type (+ name for
      uniques). Returns a search hash; ``fetch`` hydrates up to 10
      listings per call.

Both endpoints sit behind Cloudflare with a fair-use rate limit.
We:

    * Send a realistic browser User-Agent (empirically required).
    * Respect ``Retry-After`` on 429 with bounded backoff.
    * Cap results at 10 listings per search (one ``fetch`` call).

The "stale floor" insight — the thing that makes this pricer
non-trivial vs. pasting into pathofexile.com/trade — lives in
:func:`_summarise`. We treat a listing as stale when the seller's
``indexed`` timestamp is older than a threshold AND the account is
not currently online, then report the *effective floor* (cheapest
non-stale listing) alongside the raw floor. Users can anchor to the
effective floor without guessing which top listings are ghosts.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .parser import Category, ParsedItem

log = logging.getLogger("poe_qol.pricer.search")


_BASE_SEARCH = "https://www.pathofexile.com/api/trade/search"
_BASE_EXCHANGE = "https://www.pathofexile.com/api/trade/exchange"
_BASE_FETCH = "https://www.pathofexile.com/api/trade/fetch"
_SITE = "https://www.pathofexile.com/trade/search"
_STALE_HOURS_DEFAULT = 24

# Cloudflare rejects empty / python UAs with 403. Reuse the same UA
# the map-search builder settled on.
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.pathofexile.com",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"),
}


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------

@dataclass
class Listing:
    """One row returned by the trade API."""
    seller: str
    price_amount: float
    price_currency: str          # e.g. "chaos", "divine"
    indexed: _dt.datetime | None  # listing.indexed ISO8601
    online: bool                 # account currently online
    whisper: str = ""            # prebuilt "@SellerName …" string for convenience

    @property
    def stale(self) -> bool:
        """True if the listing looks like a ghost.

        Heuristic: indexed more than ``_STALE_HOURS`` ago AND seller
        not currently online. Either signal on its own is too noisy;
        both together catches the classic "logged off for 3 days with
        a stale listing" pattern that anchors floor prices artificially
        low.
        """
        if self.online:
            return False
        if self.indexed is None:
            # No timestamp → can't verify; treat as fresh to be safe.
            return False
        age = _dt.datetime.now(_dt.timezone.utc) - self.indexed
        return age.total_seconds() > _STALE_HOURS_DEFAULT * 3600


@dataclass
class PriceResult:
    query_label: str             # human label ("Chaos Orb", "Sire of Shards (Sage Wand)")
    search_url: str              # pathofexile.com/trade link the user can open
    total: int                   # total matching listings the API reports
    listings: list[Listing] = field(default_factory=list)

    # Derived summaries — None when data is insufficient.
    floor: float | None = None
    floor_currency: str = ""
    effective_floor: float | None = None
    stale_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def stale_fraction(self) -> float:
        if not self.listings:
            return 0.0
        return self.stale_count / len(self.listings)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class TradeClient:
    """Minimal JSON POST/GET with Retry-After handling.

    One instance per app; reuse it so rate-limit bookkeeping is shared
    across calls if we ever move to a token-bucket model.
    """

    def __init__(self, *, timeout: float = 10.0,
                 max_retries: int = 2,
                 base_search: str = _BASE_SEARCH,
                 base_exchange: str = _BASE_EXCHANGE,
                 base_fetch: str = _BASE_FETCH,
                 site: str = _SITE):
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_search = base_search
        self.base_exchange = base_exchange
        self.base_fetch = base_fetch
        self.site = site

    # ---- low-level ----
    def _request(self, url: str, *, data: dict | None = None,
                 method: str = "GET") -> dict:
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(url, data=body, headers=_HEADERS,
                                         method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < self.max_retries:
                    retry_after = _parse_retry_after(
                        e.headers.get("Retry-After"))
                    log.warning("trade API 429; sleeping %.1fs",
                                retry_after)
                    time.sleep(retry_after)
                    continue
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:400]
                except Exception:
                    pass
                raise RuntimeError(
                    f"trade API {e.code} {e.reason}: {detail}") from e
        # Should be unreachable; max_retries+1 iterations all returned or raised.
        raise RuntimeError("trade API request failed after retries")

    # ---- high-level ----
    def search(self, league: str, query: dict) -> tuple[str, list[str], int]:
        """POST to /search/<league>. Returns (id, first-page-hashes, total)."""
        url = f"{self.base_search.rstrip('/')}/{urllib.parse.quote(league)}"
        body = self._request(url, data=query, method="POST")
        return (body.get("id", ""),
                list(body.get("result") or []),
                int(body.get("total") or 0))

    def fetch(self, ids: list[str], search_id: str,
              *, exchange: bool = False) -> list[dict]:
        """GET /fetch/<ids>?query=<id>. Returns raw ``result`` objects."""
        if not ids:
            return []
        joined = ",".join(ids[:10])          # API caps at 10 per call
        q = urllib.parse.urlencode({"query": search_id})
        if exchange:
            q += "&exchange"
        url = f"{self.base_fetch.rstrip('/')}/{joined}?{q}"
        body = self._request(url, method="GET")
        return list(body.get("result") or [])

    def exchange(self, league: str, want: str, have: str = "chaos"
                 ) -> tuple[str, list[str], int]:
        """POST to /exchange/<league>. ``want`` / ``have`` are trade
        slug ids (e.g. ``divine``, ``chaos``)."""
        url = f"{self.base_exchange.rstrip('/')}/{urllib.parse.quote(league)}"
        query = {
            "exchange": {
                "status": {"option": "online"},
                "have": [have],
                "want": [want],
            }
        }
        body = self._request(url, data=query, method="POST")
        return (body.get("id", ""),
                list(body.get("result") or []),
                int(body.get("total") or 0))


def _parse_retry_after(v: str | None) -> float:
    if not v:
        return 2.0
    try:
        return max(1.0, float(v))
    except ValueError:
        return 2.0


# ---------------------------------------------------------------------------
# Pricing pipeline
# ---------------------------------------------------------------------------

def price_item(item: ParsedItem, *,
               league: str,
               client: TradeClient | None = None,
               have: str = "chaos",
               name_to_slug: dict[str, str] | None = None,
               ) -> PriceResult:
    """Look up comparable listings for ``item`` in ``league``.

    ``name_to_slug`` lets the caller supply a currency-name → exchange
    slug map (e.g. ``"Divine Orb" → "divine"``). If omitted we fall
    back to a naive kebab-case of the item name which works for most
    currencies but not all.
    """
    client = client or TradeClient()

    if item.is_stackable_currency_like:
        return _price_exchange(item, league, client, have, name_to_slug)
    if item.category == Category.UNIQUE:
        return _price_search_by_type(
            item, league, client,
            query={
                "query": {
                    "status": {"option": "online"},
                    "name": item.trade_name,
                    "type": item.trade_type,
                    "stats": [{"type": "and", "filters": []}],
                },
                "sort": {"price": "asc"},
            },
            label=f"{item.trade_name} ({item.trade_type})",
        )
    if item.category == Category.MAP:
        # Maps: type-only search. Rolled mod filters would be nicer
        # (that's what map_search_widget already builds) but for
        # "price the map I just copied" the type floor is usually the
        # right anchor.
        filters: dict[str, Any] = {}
        if item.map_tier is not None:
            filters["map_filters"] = {
                "filters": {"map_tier": {"min": item.map_tier,
                                         "max": item.map_tier}}
            }
        return _price_search_by_type(
            item, league, client,
            query={
                "query": {
                    "status": {"option": "online"},
                    "type": item.trade_type,
                    "filters": filters,
                    "stats": [{"type": "and", "filters": []}],
                },
                "sort": {"price": "asc"},
            },
            label=(f"{item.trade_type} (T{item.map_tier})"
                   if item.map_tier else item.trade_type),
        )
    if item.category in (Category.GEM, Category.JEWEL, Category.FLASK,
                         Category.EQUIPMENT):
        # MVP: type-only fallback. This will mis-price rolled rares —
        # surfaced as a ``notes`` entry so users know the floor is
        # "any <type>, not yours specifically".
        r = _price_search_by_type(
            item, league, client,
            query={
                "query": {
                    "status": {"option": "online"},
                    "type": item.trade_type,
                    "stats": [{"type": "and", "filters": []}],
                },
                "sort": {"price": "asc"},
            },
            label=item.trade_type,
        )
        if item.category == Category.EQUIPMENT and item.rarity.lower() == "rare":
            r.notes.append(
                "Rare rolls aren't matched yet — floor is for any "
                f"{item.trade_type}, not this specific roll.")
        return r

    raise RuntimeError(
        f"Don't know how to price category {item.category.value!r} "
        f"(item class {item.item_class!r})")


def _price_exchange(item: ParsedItem, league: str, client: TradeClient,
                    have: str,
                    name_to_slug: dict[str, str] | None) -> PriceResult:
    want = _resolve_slug(item.name, name_to_slug)
    search_id, hashes, total = client.exchange(league, want, have)
    raw = client.fetch(hashes, search_id, exchange=True)
    listings = [_listing_from_exchange(r) for r in raw if r]
    url = (f"{client.site.rstrip('/')}/"
           f"{urllib.parse.quote(league)}/exchange/{search_id}"
           if search_id else "")
    result = PriceResult(
        query_label=item.name,
        search_url=url,
        total=total,
        listings=listings,
    )
    _summarise(result)
    return result


def _price_search_by_type(item: ParsedItem, league: str, client: TradeClient,
                          *, query: dict, label: str) -> PriceResult:
    search_id, hashes, total = client.search(league, query)
    raw = client.fetch(hashes, search_id, exchange=False)
    listings = [_listing_from_search(r) for r in raw if r]
    url = (f"{client.site.rstrip('/')}/"
           f"{urllib.parse.quote(league)}/{search_id}"
           if search_id else "")
    result = PriceResult(
        query_label=label,
        search_url=url,
        total=total,
        listings=listings,
    )
    _summarise(result)
    return result


# ---------------------------------------------------------------------------
# Response → Listing
# ---------------------------------------------------------------------------

def _listing_from_search(r: dict) -> Listing:
    listing = r.get("listing") or {}
    price = listing.get("price") or {}
    account = listing.get("account") or {}
    return Listing(
        seller=str(account.get("lastCharacterName") or account.get("name") or ""),
        price_amount=float(price.get("amount") or 0.0),
        price_currency=str(price.get("currency") or ""),
        indexed=_parse_indexed(listing.get("indexed")),
        online=bool((account.get("online") or {}).get("status") == "online"
                    or account.get("online") not in (None, False, {})),
        whisper=str(listing.get("whisper") or ""),
    )


def _listing_from_exchange(r: dict) -> Listing:
    listing = r.get("listing") or {}
    # Exchange responses wrap the price under ``price`` with
    # ``exchange`` + ``item`` sub-objects. We report the *per-unit*
    # price in the ``have`` currency:
    #   exchange.amount  / item.amount   →   chaos per unit
    price = listing.get("price") or {}
    exch = price.get("exchange") or {}
    itm = price.get("item") or {}
    have_amt = float(exch.get("amount") or 0.0)
    want_amt = float(itm.get("amount") or 0.0) or 1.0
    unit = have_amt / want_amt if want_amt else 0.0
    account = listing.get("account") or {}
    return Listing(
        seller=str(account.get("lastCharacterName") or account.get("name") or ""),
        price_amount=unit,
        price_currency=str(exch.get("currency") or "chaos"),
        indexed=_parse_indexed(listing.get("indexed")),
        online=bool(account.get("online") not in (None, False, {})),
        whisper=str(listing.get("whisper") or ""),
    )


def _parse_indexed(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    # PoE trade ships RFC3339 strings ending in "Z" — fromisoformat
    # chokes on "Z" pre-3.11 but 3.11+ (our requires-python) handles it.
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Summarisation (stale-floor detection)
# ---------------------------------------------------------------------------

def _summarise(result: PriceResult) -> None:
    if not result.listings:
        result.notes.append("No active listings found.")
        return
    # Listings come back price-sorted (we asked for ``asc``), but fetch
    # does not re-sort; make sure we're honest about ordering here so
    # ``floor`` really is the minimum of what we fetched.
    sorted_ls = sorted(result.listings, key=lambda l: l.price_amount)
    result.listings = sorted_ls

    result.floor = sorted_ls[0].price_amount
    result.floor_currency = sorted_ls[0].price_currency
    fresh = [l for l in sorted_ls if not l.stale]
    result.stale_count = sum(1 for l in sorted_ls if l.stale)
    result.effective_floor = fresh[0].price_amount if fresh else None

    if result.effective_floor is None:
        result.notes.append(
            "Every visible listing looks stale. Refresh later or "
            "anchor your price manually.")
    elif (result.effective_floor is not None
          and result.floor is not None
          and result.effective_floor > result.floor * 1.10):
        gap_pct = (result.effective_floor / result.floor - 1.0) * 100.0
        result.notes.append(
            f"Top {result.stale_count} listing(s) look stale — "
            f"effective floor is {gap_pct:+.0f}% above the raw floor. "
            f"Undercut the effective floor, not the raw one.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_slug(name: str, table: dict[str, str] | None) -> str:
    if table:
        slug = table.get(name) or table.get(name.lower())
        if slug:
            return slug
    # Fall back to kebab-case — works for most currencies (e.g.
    # "Divine Orb" → "divine-orb").
    return name.lower().replace("'", "").replace(" ", "-")
