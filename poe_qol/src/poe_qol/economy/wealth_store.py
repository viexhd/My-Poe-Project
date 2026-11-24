"""Local history of stash snapshots (SQLite, stdlib only).

One *snapshot* is the valued contents of the synced tabs at one moment.
Items are stored aggregated per tab and name, so a large stash costs a
few hundred rows per sync, not thousands. Times are epoch seconds (UTC).

The file lives in the user's data folder (see :func:`default_path`), not
in the repository, and only ever holds the player's own stash values.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account         TEXT NOT NULL,
    league          TEXT NOT NULL,
    realm           TEXT NOT NULL DEFAULT 'pc',
    taken_at        REAL NOT NULL,
    total_chaos     REAL NOT NULL,
    chaos_per_divine REAL,
    item_count      INTEGER NOT NULL DEFAULT 0,
    unpriced_count  INTEGER NOT NULL DEFAULT 0,
    tab_count       INTEGER NOT NULL DEFAULT 0,
    source          TEXT NOT NULL DEFAULT 'stash',
    note            TEXT
);
CREATE INDEX IF NOT EXISTS snapshot_by_time ON snapshot(account, league, taken_at);
CREATE TABLE IF NOT EXISTS snapshot_tab (
    snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
    stash_id    TEXT NOT NULL,
    name        TEXT NOT NULL,
    type        TEXT,
    total_chaos REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS tab_by_snapshot ON snapshot_tab(snapshot_id);
CREATE TABLE IF NOT EXISTS snapshot_item (
    snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
    stash_id    TEXT NOT NULL,
    tab_name    TEXT NOT NULL,
    name        TEXT NOT NULL,
    category    TEXT,
    quantity    REAL NOT NULL,
    unit_chaos  REAL NOT NULL,
    total_chaos REAL NOT NULL,
    icon        TEXT
);
CREATE INDEX IF NOT EXISTS item_by_snapshot ON snapshot_item(snapshot_id);
"""


@dataclass
class TabTotal:
    stash_id: str
    name: str
    type: str
    total_chaos: float


@dataclass
class ItemLine:
    stash_id: str
    tab_name: str
    name: str
    category: str
    quantity: float
    unit_chaos: float
    total_chaos: float
    icon: str = ""


@dataclass
class SnapshotHead:
    id: int
    account: str
    league: str
    realm: str
    taken_at: float
    total_chaos: float
    chaos_per_divine: float | None
    item_count: int
    unpriced_count: int
    tab_count: int
    source: str = "stash"
    note: str | None = None


@dataclass
class NewSnapshot:
    account: str
    league: str
    realm: str = "pc"
    taken_at: float = field(default_factory=time.time)
    chaos_per_divine: float | None = None
    unpriced_count: int = 0
    source: str = "stash"
    note: str | None = None
    tabs: list[TabTotal] = field(default_factory=list)
    items: list[ItemLine] = field(default_factory=list)

    @property
    def total_chaos(self) -> float:
        return sum(i.total_chaos for i in self.items)


_HEAD_COLS = ("id, account, league, realm, taken_at, total_chaos, chaos_per_divine, "
              "item_count, unpriced_count, tab_count, source, note")


class WealthStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- writes ----
    def add(self, snap: NewSnapshot) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO snapshot (account, league, realm, taken_at, total_chaos,"
                " chaos_per_divine, item_count, unpriced_count, tab_count, source, note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (snap.account, snap.league, snap.realm, snap.taken_at,
                 snap.total_chaos, snap.chaos_per_divine, len(snap.items),
                 snap.unpriced_count, len(snap.tabs), snap.source, snap.note))
            sid = int(cur.lastrowid)
            self._db.executemany(
                "INSERT INTO snapshot_tab VALUES (?,?,?,?,?)",
                [(sid, t.stash_id, t.name, t.type, t.total_chaos) for t in snap.tabs])
            self._db.executemany(
                "INSERT INTO snapshot_item VALUES (?,?,?,?,?,?,?,?,?)",
                [(sid, i.stash_id, i.tab_name, i.name, i.category, i.quantity,
                  i.unit_chaos, i.total_chaos, i.icon) for i in snap.items])
            return sid

    def delete(self, snapshot_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM snapshot WHERE id = ?", (snapshot_id,))

    def delete_history(self, account: str, league: str) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                "DELETE FROM snapshot WHERE account = ? AND league = ?",
                (account, league))
            return cur.rowcount

    # ---- reads ----
    def _heads(self, sql: str, args: tuple) -> list[SnapshotHead]:
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [SnapshotHead(*r) for r in rows]

    def snapshots(self, account: str, league: str, start: float | None = None,
                  end: float | None = None) -> list[SnapshotHead]:
        """Oldest first, optionally limited to ``start <= taken_at <= end``."""
        sql = f"SELECT {_HEAD_COLS} FROM snapshot WHERE account = ? AND league = ?"
        args: list = [account, league]
        if start is not None:
            sql += " AND taken_at >= ?"
            args.append(start)
        if end is not None:
            sql += " AND taken_at <= ?"
            args.append(end)
        return self._heads(sql + " ORDER BY taken_at", tuple(args))

    def latest(self, account: str, league: str,
               at_or_before: float | None = None) -> SnapshotHead | None:
        sql = f"SELECT {_HEAD_COLS} FROM snapshot WHERE account = ? AND league = ?"
        args: list = [account, league]
        if at_or_before is not None:
            sql += " AND taken_at <= ?"
            args.append(at_or_before)
        heads = self._heads(sql + " ORDER BY taken_at DESC LIMIT 1", tuple(args))
        return heads[0] if heads else None

    def first_after(self, account: str, league: str,
                    at_or_after: float) -> SnapshotHead | None:
        heads = self._heads(
            f"SELECT {_HEAD_COLS} FROM snapshot WHERE account = ? AND league = ?"
            " AND taken_at >= ? ORDER BY taken_at LIMIT 1",
            (account, league, at_or_after))
        return heads[0] if heads else None

    def items(self, snapshot_id: int) -> list[ItemLine]:
        with self._lock:
            rows = self._db.execute(
                "SELECT stash_id, tab_name, name, category, quantity, unit_chaos,"
                " total_chaos, icon FROM snapshot_item WHERE snapshot_id = ?"
                " ORDER BY total_chaos DESC", (snapshot_id,)).fetchall()
        return [ItemLine(*r[:7], icon=r[7] or "") for r in rows]

    def tabs(self, snapshot_id: int) -> list[TabTotal]:
        with self._lock:
            rows = self._db.execute(
                "SELECT stash_id, name, type, total_chaos FROM snapshot_tab"
                " WHERE snapshot_id = ? ORDER BY total_chaos DESC",
                (snapshot_id,)).fetchall()
        return [TabTotal(*r) for r in rows]

    def leagues(self, account: str) -> list[str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT league FROM snapshot WHERE account = ?",
                (account,)).fetchall()
        return [r[0] for r in rows]
