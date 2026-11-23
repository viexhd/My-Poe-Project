"""Parse a Wealthy Exile "Export CSV" file into one wealth snapshot.

The user exports the file themselves on wealthyexile.com
(Stash -> "more actions" -> Export CSV). This module only reads that
local file: no Wealthy Exile login, cookie or private endpoint is used.
See docs/WEALTHY_EXILE_INTEGRATION.md.

Wealthy Exile does not document the CSV layout, so headers are matched
loosely. Its on-site stash table shows Name, Tab, Quantity, Price and
Total; any header with a quantity column plus a price or total column
works. One file = one snapshot taken at the file's modified time.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = ["CsvFormatError", "Snapshot", "parse_number", "parse_snapshot"]


class CsvFormatError(ValueError):
    """The file isn't a CSV layout we can read."""


@dataclass(frozen=True)
class Snapshot:
    path: Path
    taken_at: datetime
    total: float          # sum of row totals, in `unit`
    unit: str             # "chaos" | "divine" | "unknown"
    rows: int             # rows that contributed to `total`
    skipped: int          # rows that could not be parsed


_SPACES = re.compile(r"[\s   ]+")


def parse_number(text: str) -> float:
    """Parse ``1,234.5`` / ``1 234,5`` / ``1.234,5`` / ``0,5`` style numbers."""
    s = _SPACES.sub("", str(text or ""))
    if not s:
        raise ValueError("empty number")
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "")
        s = s.replace(",", ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if s.count(",") > 1 or (len(tail) == 3 and head.lstrip("-")):
            s = s.replace(",", "")          # thousands separators
        else:
            s = s.replace(",", ".")         # decimal comma
    elif s.count(".") > 1:
        s = s.replace(".", "")              # 1.234.567
    return float(s)


def _unit_of(header: str) -> str:
    h = header.lower()
    if "div" in h:
        return "divine"
    if "chaos" in h or re.search(r"\(c\)|\bc\b", h):
        return "chaos"
    return "unknown"


def _find_columns(header: list[str]) -> dict[str, int]:
    norm = [h.strip().lstrip("﻿").lower() for h in header]
    cols: dict[str, int] = {}

    def first(pred) -> int | None:
        return next((i for i, h in enumerate(norm)
                     if i not in cols.values() and pred(h)), None)

    for key, pred in (
        ("total", lambda h: "total" in h),
        ("quantity", lambda h: any(w in h for w in
                                   ("quantity", "qty", "count", "stack", "amount"))),
        ("price", lambda h: any(w in h for w in ("price", "each"))
                            or h.startswith("value") or h in ("chaos", "divine")),
        ("name", lambda h: "name" in h or "item" in h),
        ("tab", lambda h: "tab" in h),
    ):
        idx = first(pred)
        if idx is not None:
            cols[key] = idx
    return cols


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def parse_snapshot(path: str | Path, taken_at: datetime | None = None) -> Snapshot:
    path = Path(path)
    text = _read_text(path)
    first_line = text.splitlines()[0] if text.strip() else ""
    try:
        dialect = csv.Sniffer().sniff(first_line, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader, None) or []
    cols = _find_columns(header)
    if "quantity" not in cols or not ({"price", "total"} & cols.keys()):
        raise CsvFormatError(
            f"{path.name}: unrecognised columns {header!r}. Expected a "
            "quantity column plus a price or total column "
            "(e.g. Name, Tab, Quantity, Price, Total).")

    unit_header = header[cols["total"]] if "total" in cols else header[cols["price"]]
    unit = _unit_of(unit_header)
    if unit == "unknown" and "price" in cols:
        unit = _unit_of(header[cols["price"]])

    total = 0.0
    rows = skipped = 0
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        try:
            value = None
            if "total" in cols and cols["total"] < len(row) and row[cols["total"]].strip():
                value = parse_number(row[cols["total"]])
            else:
                qty = parse_number(row[cols["quantity"]])
                price = parse_number(row[cols["price"]])
                value = qty * price
            total += value
            rows += 1
        except (ValueError, IndexError, KeyError):
            skipped += 1

    when = taken_at or datetime.fromtimestamp(path.stat().st_mtime)
    return Snapshot(path=path, taken_at=when, total=total, unit=unit,
                    rows=rows, skipped=skipped)
