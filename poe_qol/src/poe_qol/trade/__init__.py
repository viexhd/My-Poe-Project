"""Regex → PoE trade query pipeline.

Public API:
    parse(text)            -> ParsedQuery
    build_query(parsed, …) -> dict  (ready to POST to trade API)
    build_url(query, …)    -> str   (fills a search URL, optionally POSTs)
"""
from .parser import parse, ParsedQuery, Group, Atom  # noqa: F401
from .builder import build_query, build_url, ModMap    # noqa: F401
