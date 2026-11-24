"""Account endpoints of the official Path of Exile API.

Reference: https://www.pathofexile.com/developer/docs/reference

==========================  ===================  =====================
Endpoint                    Scope                Used for
==========================  ===================  =====================
``GET /profile``            account:profile      account name
``GET /account/leagues``    account:leagues      league picker
``GET /stash/<league>``     account:stashes      list of stash tabs
``GET /stash/<league>/<id>[/<sub>]``             one tab with items
==========================  ===================  =====================

A realm other than ``pc`` (``xbox``, ``sony``, ``poe2``) goes between
the endpoint and the league: ``/stash/xbox/<league>``.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from typing import Callable

from .http import Response, Transport, urllib_transport
from .oauth import OAuthClient, OAuthError, Token, user_agent
from .ratelimit import RateLimiter

log = logging.getLogger("poe_qol.ggg.api")

API_BASE = "https://api.pathofexile.com"
REALMS = ("pc", "xbox", "sony", "poe2")


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class AuthExpired(ApiError):
    """The token is gone or was revoked: the player must connect again."""


class Cancelled(ApiError):
    pass


def _q(s: str) -> str:
    return urllib.parse.quote(str(s), safe="")


class PoeApi:
    """Authenticated client. Thread-safe enough for one sync worker plus
    the UI thread reading :attr:`token`."""

    def __init__(self, oauth: OAuthClient, token: Token, *,
                 on_token: Callable[[Token], None] | None = None,
                 transport: Transport | None = None,
                 limiter: RateLimiter | None = None,
                 base: str = API_BASE) -> None:
        self.oauth = oauth
        self.token = token
        self.on_token = on_token
        self.limiter = limiter or RateLimiter()
        self._send = transport or urllib_transport()
        self._base = base.rstrip("/")
        self._lock = threading.Lock()
        self.cancelled: Callable[[], bool] = lambda: False
        self.on_wait: Callable[[float], None] | None = None

    # ---- token ----
    def _fresh_token(self) -> Token:
        with self._lock:
            if self.token.expired():
                try:
                    self.token = self.oauth.refresh(self.token)
                except OAuthError as e:
                    raise AuthExpired(str(e), 401) from e
                if self.on_token:
                    self.on_token(self.token)
            return self.token

    # ---- transport ----
    def get(self, path: str, endpoint: str) -> dict:
        """GET ``path``; ``endpoint`` names the rate-limit bucket until the
        server tells us the real policy name."""
        for attempt in range(3):
            if not self.limiter.acquire(endpoint, self.cancelled, self.on_wait):
                raise Cancelled("Sync cancelled.")
            tok = self._fresh_token()
            r: Response = self._send("GET", self._base + path, {
                "Authorization": f"Bearer {tok.access_token}",
                "Accept": "application/json",
                "User-Agent": user_agent(self.oauth.client_id, self.oauth.contact),
            }, None)
            self.limiter.update(endpoint, r, r.status)
            if r.status == 200:
                try:
                    data = r.json()
                except (ValueError, json.JSONDecodeError) as e:
                    raise ApiError("pathofexile.com sent a broken reply.") from e
                return data if isinstance(data, dict) else {}
            if r.status == 401:
                if attempt == 0 and self.token.refresh_token:
                    # token revoked/expired early: force one refresh
                    with self._lock:
                        self.token.expires_at = 0
                    continue
                raise AuthExpired("pathofexile.com no longer accepts the "
                                  "sign-in. Connect your account again.", 401)
            if r.status == 403:
                raise AuthExpired("Missing permission. Connect your account "
                                  "again and allow stash access.", 403)
            if r.status == 429:
                log.warning("rate limited on %s; waiting", endpoint)
                continue                       # limiter now holds us back
            if r.status == 404:
                raise ApiError("Not found (league or stash tab).", 404)
            if 500 <= r.status < 600 and attempt < 2:
                continue
            raise ApiError(f"pathofexile.com answered HTTP {r.status}.", r.status)
        raise ApiError("pathofexile.com kept refusing; try again later.", 429)

    @staticmethod
    def _realm(realm: str | None) -> str:
        return "" if not realm or realm == "pc" else f"/{_q(realm)}"

    # ---- endpoints ----
    def profile(self) -> dict:
        return self.get("/profile", "profile")

    def leagues(self, realm: str | None = None) -> list[dict]:
        d = self.get(f"/account/leagues{self._realm(realm)}", "leagues")
        return [x for x in d.get("leagues") or [] if isinstance(x, dict)]

    def list_stashes(self, league: str, realm: str | None = None) -> list[dict]:
        d = self.get(f"/stash{self._realm(realm)}/{_q(league)}", "stash-list")
        return [x for x in d.get("stashes") or [] if isinstance(x, dict)]

    def get_stash(self, league: str, stash_id: str, substash_id: str | None = None,
                  realm: str | None = None) -> dict | None:
        path = f"/stash{self._realm(realm)}/{_q(league)}/{_q(stash_id)}"
        if substash_id:
            path += f"/{_q(substash_id)}"
        d = self.get(path, "stash")
        s = d.get("stash")
        return s if isinstance(s, dict) else None
