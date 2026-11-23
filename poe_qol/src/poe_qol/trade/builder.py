"""Turn a trade query payload into a PoE trade URL.

The payload itself is built by :func:`poe_qol.trade.map_query.build_map_query`.
Two URL modes, controlled by config:

    * "post"  – POST to pathofexile.com/api/trade/search/<league>,
                read the returned id, return the canonical short URL.
                Requires network access.
    * "copy"  – build a debug URL with the payload JSON in a `q` query
                parameter. Does NOT open in pathofexile.com (they
                require a hash URL) but is useful for copy/paste into
                browser dev tools or the API's raw endpoint.

PoE trade "stat group" cheat-sheet used below:

    {type: and,   filters: [...]}                   – all must match
    {type: not,   filters: [...]}                   – none may match
    {type: count, filters: [...], value: {min: N}}  – at least N match
    {type: count, filters: [...], value: {max: N}}  – at most  N match
"""
from __future__ import annotations

import json
import logging
import urllib.parse

log = logging.getLogger("poe_qol.trade")


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------

def _copy_url(query: dict, *, base: str) -> str:
    league = query.get("__league__", "Standard")
    payload = {k: v for k, v in query.items() if not k.startswith("__")}
    q = urllib.parse.quote(json.dumps(payload, separators=(",", ":")))
    return f"{base.rstrip('/')}/{urllib.parse.quote(league)}?q={q}"


_UNKNOWN_STAT_RE = __import__("re").compile(
    r"Unknown stat provided:\s*([A-Za-z0-9_.]+)")


def _strip_stat_id(payload: dict, stat_id: str) -> bool:
    """Remove every reference to ``stat_id`` from a trade payload.

    Returns True if anything was removed. Walks the ``query.stats`` list
    and drops matching inner filters; also drops any stat group that
    ends up empty so the API doesn't choke on an empty-filters group.
    """
    stats = payload.get("query", {}).get("stats")
    if not isinstance(stats, list):
        return False
    removed = False
    new_stats: list[dict] = []
    for group in stats:
        filters = group.get("filters") or []
        kept = [f for f in filters if f.get("id") != stat_id]
        if len(kept) != len(filters):
            removed = True
        if kept:
            group["filters"] = kept
            new_stats.append(group)
        # else: drop the whole group (empty filter list = 400)
    payload["query"]["stats"] = new_stats
    return removed


def _post_url(query: dict, *, base_api: str, base_site: str,
              timeout: float = 10.0) -> str:
    import urllib.error
    import urllib.request  # stdlib – avoid a new dep
    league = query.get("__league__", "Standard")
    payload = {k: v for k, v in query.items() if not k.startswith("__")}
    url = f"{base_api.rstrip('/')}/{urllib.parse.quote(league)}"
    # PoE's trade API sits behind Cloudflare and rejects generic
    # User-Agents with 400 / 403. A realistic browser UA gets through.
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.pathofexile.com",
        "Referer": f"{base_site.rstrip('/')}/{urllib.parse.quote(league)}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"),
    }

    # Auto-retry loop: if the API rejects a single stat as "unknown"
    # (map_mods.yaml got a stale id between leagues), strip it and
    # resend. Cap at len(stats) attempts so we can't spin forever.
    dropped: list[str] = []
    for _ in range(16):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            m = _UNKNOWN_STAT_RE.search(detail) if e.code == 400 else None
            if m and _strip_stat_id(payload, m.group(1)):
                dropped.append(m.group(1))
                log.warning("trade API rejected %s; retrying without it",
                            m.group(1))
                continue
            raise RuntimeError(
                f"trade API {e.code} {e.reason}: {detail[:400]}"
            ) from e
    else:  # pragma: no cover – only hit if every stat is stale
        raise RuntimeError(
            "trade API kept rejecting stats; giving up after stripping: "
            + ", ".join(dropped))

    hash_id = body.get("id")
    if not hash_id:
        raise RuntimeError(f"trade API returned no id: {body!r}")
    final = f"{base_site.rstrip('/')}/{urllib.parse.quote(league)}/{hash_id}"
    if dropped:
        log.warning("dropped stale stat ids from query: %s",
                    ", ".join(dropped))
    return final


def build_url(query: dict, *, mode: str = "copy",
              base_site: str = "https://www.pathofexile.com/trade/search",
              base_api: str = "https://www.pathofexile.com/api/trade/search") -> str:
    if mode == "post":
        return _post_url(query, base_api=base_api, base_site=base_site)
    return _copy_url(query, base=base_site)
