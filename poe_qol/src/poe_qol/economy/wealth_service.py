"""Everything the Wealth tab needs, without Qt.

Holds the sign-in token, the snapshot database and the price cache, and
builds a :class:`~poe_qol.ggg.api.PoeApi` on demand. The Qt widget only
calls into this from worker threads and displays results.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from ..ggg.api import PoeApi
from ..ggg.http import Transport
from ..ggg.oauth import DEFAULT_SCOPES, OAuthClient, PendingLogin, Token
from ..ggg.token_store import TokenStore
from .ninja import NinjaClient
from .pricing import PriceBook, build_price_book
from .stash_sync import StashSync, SyncResult, TabRef
from .wealth_store import WealthStore

log = logging.getLogger("poe_qol.economy.wealth_service")

PRICE_TTL_SEC = 30 * 60


class WealthService:
    def __init__(self, data_dir: Path, *, client_id: str | None,
                 contact: str | None = None, ninja_cache: Path | None = None,
                 transport: Transport | None = None,
                 ninja: NinjaClient | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.client_id = (client_id or "").strip()
        self.contact = contact
        self._transport = transport
        self.tokens = TokenStore(self.data_dir / "ggg_token.bin")
        self.store = WealthStore(self.data_dir / "wealth.sqlite")
        self.ninja = ninja or NinjaClient(ninja_cache or (self.data_dir / "ninja_cache"),
                                          freshness_sec=PRICE_TTL_SEC)
        self._token: Token | None = self.tokens.load()
        self._books: dict[str, PriceBook] = {}
        self._book_lock = threading.Lock()
        self._api: PoeApi | None = None

    # ---- account ----
    @property
    def configured(self) -> bool:
        return bool(self.client_id)

    @property
    def token(self) -> Token | None:
        return self._token

    @property
    def connected(self) -> bool:
        return self._token is not None

    @property
    def account(self) -> str:
        t = self._token
        return (t.username or t.sub) if t else ""

    def set_client_id(self, client_id: str | None) -> None:
        client_id = (client_id or "").strip()
        if client_id != self.client_id:
            self.client_id = client_id
            self._api = None

    def oauth(self) -> OAuthClient:
        return OAuthClient(self.client_id, contact=self.contact,
                           transport=self._transport)

    def begin_login(self, port: int = 0) -> PendingLogin:
        return PendingLogin.start(self.oauth().client_id, port=port,
                                  scopes=DEFAULT_SCOPES)

    def finish_login(self, pending: PendingLogin, timeout: float = 300.0) -> Token:
        tok = pending.finish(self.oauth(), timeout=timeout, scopes=DEFAULT_SCOPES)
        self._save_token(tok)
        if not tok.username:
            try:
                prof = self.api().profile()
                tok.username = str(prof.get("name") or "")
                tok.sub = tok.sub or str(prof.get("uuid") or "")
                self._save_token(tok)
            except Exception as e:  # noqa: BLE001
                log.warning("profile lookup failed: %s", e)
        return tok

    def _save_token(self, tok: Token) -> None:
        self._token = tok
        if self._api is not None:
            self._api.token = tok
        try:
            self.tokens.save(tok)
        except Exception:  # noqa: BLE001
            log.exception("could not save the sign-in token")

    def disconnect(self, revoke: bool = True) -> None:
        """Forget the sign-in. Revoking it at pathofexile.com runs in the
        background so the UI never waits on the network."""
        tok, self._token, self._api = self._token, None, None
        self.tokens.clear()
        if revoke and tok and self.client_id:
            threading.Thread(target=self.oauth().revoke, args=(tok,),
                             daemon=True, name="oauth-revoke").start()

    def api(self) -> PoeApi:
        if self._token is None:
            raise RuntimeError("Not connected.")
        if self._api is None or self._api.oauth.client_id != self.client_id:
            self._api = PoeApi(self.oauth(), self._token, on_token=self._save_token,
                               transport=self._transport)
        return self._api

    # ---- prices ----
    def price_book(self, league: str, *, progress: Callable[[str], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> PriceBook:
        with self._book_lock:
            book = self._books.get(league)
            if book and time.time() - book.fetched_at < PRICE_TTL_SEC and not book.stale:
                return book
        book = build_price_book(self.ninja, league, progress=progress,
                                cancelled=cancelled)
        with self._book_lock:
            self._books[league] = book
        return book

    # ---- sync ----
    def leagues(self, realm: str = "pc") -> list[str]:
        return [str(l.get("id")) for l in self.api().leagues(realm) if l.get("id")]

    def list_tabs(self, league: str, realm: str = "pc") -> list[TabRef]:
        return StashSync(self.api(), self.store, self.price_book).list_tabs(league, realm)

    def sync(self, league: str, realm: str = "pc", tab_ids: set[str] | None = None,
             progress=None, cancelled=None) -> SyncResult:
        def prices(lg: str) -> PriceBook:
            return self.price_book(
                lg, cancelled=cancelled,
                progress=(lambda m: progress(m, 0, 0)) if progress else None)
        return StashSync(self.api(), self.store, prices).run(
            account=self.account, league=league, realm=realm, tab_ids=tab_ids,
            progress=progress, cancelled=cancelled)

    def close(self) -> None:
        self.store.close()
