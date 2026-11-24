"""Sign in with a Path of Exile account (OAuth 2.1, public client + PKCE).

This is the same flow Wealthy Exile and other GGG-approved tools use:

1. The app opens ``https://www.pathofexile.com/oauth/authorize`` in the
   player's own browser (RFC 8252: native apps use the system browser,
   never an embedded one). The player logs in on pathofexile.com and
   presses **Authorize** on GGG's consent page.
2. pathofexile.com redirects to ``http://127.0.0.1:<port>/oauth/callback``
   where a one-shot local server (:class:`LoopbackReceiver`) catches the
   ``code``.
3. The code is exchanged at ``/oauth/token`` together with the PKCE
   ``code_verifier``. The app never sees the player's password.

GGG requires each application to be registered (email
oauth@grindinggear.com, see https://www.pathofexile.com/developer/docs).
A *public* client has no secret, so its ``client_id`` can ship in
``config/default.yaml`` (``wealth.oauth.client_id``).
"""
from __future__ import annotations

import base64
import hashlib
import html
import secrets
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

from .. import __version__
from .http import Transport, urllib_transport

AUTHORIZE_URL = "https://www.pathofexile.com/oauth/authorize"
TOKEN_URL = "https://www.pathofexile.com/oauth/token"
REVOKE_URL = "https://www.pathofexile.com/oauth/token/revoke"
CALLBACK_PATH = "/oauth/callback"

# Least privilege: the Wealth tab only needs these three.
DEFAULT_SCOPES = ("account:profile", "account:leagues", "account:stashes")


class OAuthError(RuntimeError):
    """A sign-in or token failure, worded for the UI."""


def user_agent(client_id: str, contact: str | None = None) -> str:
    """GGG's required format: ``OAuth {clientId}/{version} (contact: …)``."""
    ua = f"OAuth {client_id or 'unregistered'}/{__version__}"
    if contact:
        ua += f" (contact: {contact})"
    return ua


# ---- PKCE -------------------------------------------------------------

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_verifier() -> str:
    """43-128 chars from the unreserved set (RFC 7636 §4.1)."""
    return _b64url(secrets.token_bytes(48))       # 64 chars


def challenge_for(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def redirect_uri(port: int) -> str:
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"


def authorize_url(client_id: str, *, redirect: str, state: str,
                  challenge: str, scopes=DEFAULT_SCOPES) -> str:
    q = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "redirect_uri": redirect,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }, quote_via=urllib.parse.quote)
    return f"{AUTHORIZE_URL}?{q}"


# ---- tokens -------------------------------------------------------------

@dataclass
class Token:
    access_token: str
    expires_at: float               # epoch seconds
    refresh_token: str | None = None
    scope: str = ""
    username: str = ""              # account name, e.g. "Arialebles#4334"
    sub: str = ""                   # stable account uuid
    token_type: str = "bearer"
    obtained_at: float = 0.0

    def expired(self, now: float | None = None, margin: float = 60.0) -> bool:
        return (now or time.time()) >= self.expires_at - margin

    def has_scope(self, scope: str) -> bool:
        return scope in self.scope.split()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Token":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in fields})

    @classmethod
    def from_response(cls, d: dict, *, previous: "Token | None" = None,
                      now: float | None = None) -> "Token":
        if not isinstance(d, dict) or not d.get("access_token"):
            raise OAuthError("pathofexile.com sent no access token.")
        now = now or time.time()
        return cls(
            access_token=str(d["access_token"]),
            expires_at=now + float(d.get("expires_in") or 3600),
            refresh_token=d.get("refresh_token") or (previous.refresh_token
                                                     if previous else None),
            scope=str(d.get("scope") or (previous.scope if previous else "")),
            username=str(d.get("username") or (previous.username if previous else "")),
            sub=str(d.get("sub") or (previous.sub if previous else "")),
            token_type=str(d.get("token_type") or "bearer"),
            obtained_at=now,
        )


class OAuthClient:
    """Token endpoint calls for one registered public client."""

    def __init__(self, client_id: str, *, contact: str | None = None,
                 transport: Transport | None = None) -> None:
        if not client_id:
            raise OAuthError(
                "No GGG OAuth client ID is set. Register the app with GGG "
                "(see the Wealth tab's help) and enter its client ID.")
        self.client_id = client_id
        self.contact = contact
        self._send = transport or urllib_transport()

    def _post(self, url: str, form: dict) -> dict:
        body = urllib.parse.urlencode(form).encode("ascii")
        r = self._send("POST", url, {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": user_agent(self.client_id, self.contact),
        }, body)
        try:
            data = r.json()
        except ValueError:
            data = None
        if r.status != 200:
            msg = ""
            if isinstance(data, dict):
                msg = data.get("error_description") or data.get("error") or ""
            raise OAuthError(f"pathofexile.com refused the request "
                             f"(HTTP {r.status}{': ' + msg if msg else ''}).")
        return data if isinstance(data, dict) else {}

    def exchange_code(self, code: str, *, verifier: str, redirect: str,
                      scopes=DEFAULT_SCOPES) -> Token:
        return Token.from_response(self._post(TOKEN_URL, {
            "client_id": self.client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "scope": " ".join(scopes),
            "code_verifier": verifier,
        }))

    def refresh(self, token: Token) -> Token:
        if not token.refresh_token:
            raise OAuthError("Session expired. Connect your account again.")
        return Token.from_response(self._post(TOKEN_URL, {
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
        }), previous=token)

    def revoke(self, token: Token) -> None:
        """Best effort: the local copy is deleted either way."""
        try:
            self._post(REVOKE_URL, {"token": token.access_token})
        except Exception:  # noqa: BLE001
            pass


# ---- loopback redirect receiver -----------------------------------------

_PAGE = """<!doctype html><meta charset="utf-8"><title>Twice Corrupted</title>
<body style="background:#0D0A0B;color:#E8DCCB;font:16px 'Segoe UI',sans-serif;
display:grid;place-items:center;height:90vh;margin:0">
<div style="text-align:center;max-width:32em"><h1 style="color:{color};
font-weight:600">{title}</h1><p>{text}</p></div></body>"""


@dataclass
class AuthResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


class LoopbackReceiver:
    """One-shot ``127.0.0.1`` HTTP server that waits for the redirect.

    Binds to loopback only, accepts exactly the callback path, and stops
    after the first callback (or :meth:`close`).
    """

    def __init__(self, port: int = 0) -> None:
        self.result: AuthResult | None = None
        self._done = threading.Event()
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parts = urllib.parse.urlsplit(self.path)
                if parts.path != CALLBACK_PATH:
                    self.send_error(404)
                    return
                q = urllib.parse.parse_qs(parts.query)
                one = lambda k: (q.get(k) or [None])[0]  # noqa: E731
                res = AuthResult(code=one("code"), state=one("state"),
                                 error=one("error_description") or one("error"))
                ok = bool(res.code) and not res.error
                page = _PAGE.format(
                    color="#4FB286" if ok else "#E5484D",
                    title="Connected" if ok else "Not connected",
                    text=("You can close this tab and return to Twice Corrupted."
                          if ok else html.escape(res.error or "No code received.")))
                data = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                if receiver.result is None:
                    receiver.result = res
                    receiver._done.set()

            def log_message(self, *_a):  # keep codes out of the logs
                pass

        try:
            self._server = HTTPServer(("127.0.0.1", port), Handler)
        except OSError as e:
            raise OAuthError(
                f"Port {port} on 127.0.0.1 is busy, so the sign-in "
                f"redirect can't be received ({e}).") from e
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._serve, daemon=True,
                                        name="oauth-loopback")
        self._thread.start()

    @property
    def redirect_uri(self) -> str:
        return redirect_uri(self.port)

    def _serve(self) -> None:
        self._server.timeout = 0.25
        while not self._done.is_set():
            self._server.handle_request()
        self._server.server_close()

    def wait(self, timeout: float) -> AuthResult | None:
        self._done.wait(timeout)
        return self.result

    def close(self) -> None:
        self._done.set()


@dataclass
class PendingLogin:
    """Everything a sign-in attempt needs, kept together."""
    url: str
    state: str
    verifier: str
    receiver: LoopbackReceiver

    @classmethod
    def start(cls, client_id: str, *, port: int = 0,
              scopes=DEFAULT_SCOPES) -> "PendingLogin":
        verifier = make_verifier()
        state = secrets.token_urlsafe(24)
        rx = LoopbackReceiver(port)
        url = authorize_url(client_id, redirect=rx.redirect_uri, state=state,
                            challenge=challenge_for(verifier), scopes=scopes)
        return cls(url=url, state=state, verifier=verifier, receiver=rx)

    def finish(self, oauth: OAuthClient, timeout: float = 300.0,
               scopes=DEFAULT_SCOPES) -> Token:
        try:
            res = self.receiver.wait(timeout)
        finally:
            self.receiver.close()
        if res is None:
            raise OAuthError("Sign-in timed out or was cancelled.")
        if res.error:
            raise OAuthError(f"pathofexile.com: {res.error}")
        if not res.code or not secrets.compare_digest(res.state or "", self.state):
            raise OAuthError("The sign-in reply didn't match; try again.")
        # GGG's authorization codes are short-lived: exchange right away.
        return oauth.exchange_code(res.code, verifier=self.verifier,
                                   redirect=self.receiver.redirect_uri,
                                   scopes=scopes)
