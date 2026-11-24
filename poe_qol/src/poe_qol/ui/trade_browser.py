"""In-app browser for the official trade site.

Why this exists: the trade site sits behind Cloudflare, so scripted API
calls get blocked. Awakened PoE Trade works around that by reusing the
browser's cookies for its own API requests. Twice Corrupted doesn't do
that (docs/COMPLIANCE_REVIEW.md). Instead this window is an ordinary
browser that *you* use: you log in on pathofexile.com yourself, and Map
Search simply navigates it to a pre-filled ``/trade/search/<league>?q=``
link, which the site runs like any other page load.

Guarantees:
  * Only https://pathofexile.com and its subdomains load here; any other
    link opens in your normal browser.
  * The app never reads, copies or sends the cookies. They stay in this
    window's private profile (%APPDATA%\\twice-corrupted\\trade-browser),
    which "Sign out & clear" wipes.
  * No scripts are injected into the pages.
"""
from __future__ import annotations

import logging
import urllib.parse
from pathlib import Path

log = logging.getLogger("poe_qol.ui.trade_browser")

ALLOWED_DOMAIN = "pathofexile.com"
HOME_URL = "https://www.pathofexile.com/trade/search/{league}"


# "Sign in with Steam" on pathofexile.com goes through Steam's OpenID page.
_SIGN_IN_PAGES = (("steamcommunity.com", "/openid/"),)


def is_allowed_url(url: str) -> bool:
    """True for https URLs on pathofexile.com (or a subdomain), plus the
    Steam OpenID sign-in page used by pathofexile.com's login."""
    try:
        parts = urllib.parse.urlsplit(url or "")
    except ValueError:
        return False
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    if host == ALLOWED_DOMAIN or host.endswith("." + ALLOWED_DOMAIN):
        return True
    return any(host == h and parts.path.startswith(p) for h, p in _SIGN_IN_PAGES)


def profile_dir() -> Path:
    from PySide6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base) / "trade-browser"


def create_trade_browser(league: str = "Standard"):
    """Build the browser window. QtWebEngine is imported lazily so the
    rest of the app (and the tests) don't pay for it."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import (
        QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
        QVBoxLayout, QWidget,
    )

    class _GuardedPage(QWebEnginePage):
        """Keeps navigation on pathofexile.com; hands everything else to
        the system browser."""

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
            if not is_main_frame or is_allowed_url(url.toString()):
                return True
            log.info("opening off-site link externally: %s", url.host())
            QDesktopServices.openUrl(url)
            return False

        def createWindow(self, _type):  # noqa: N802
            # target=_blank / window.open: load in this same window.
            return self

    class TradeBrowserWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Trade Browser")
            self.resize(1200, 820)
            self._league = league

            store = profile_dir()
            store.mkdir(parents=True, exist_ok=True)
            self.profile = QWebEngineProfile("twice-corrupted-trade", self)
            self.profile.setPersistentStoragePath(str(store))
            self.profile.setCachePath(str(store / "cache"))

            self.view = QWebEngineView(self)
            self.view.setPage(_GuardedPage(self.profile, self.view))

            bar = QHBoxLayout()
            for label, slot in (("◀", self.view.back), ("▶", self.view.forward),
                                ("⟳", self.view.reload)):
                b = QPushButton(label)
                b.setFixedWidth(36)
                b.clicked.connect(slot)
                bar.addWidget(b)
            home = QPushButton("Trade Home")
            home.clicked.connect(lambda: self.open(HOME_URL.format(
                league=urllib.parse.quote(self._league))))
            bar.addWidget(home)
            self.address = QLabel("")
            self.address.setProperty("role", "muted")
            bar.addWidget(self.address, 1)
            ext = QPushButton("Open In My Browser")
            ext.clicked.connect(lambda: QDesktopServices.openUrl(self.view.url()))
            bar.addWidget(ext)
            signout = QPushButton("Sign Out && Clear")
            signout.setToolTip("Delete this window's cookies and cache.")
            signout.clicked.connect(self._clear)
            bar.addWidget(signout)

            note = QLabel("Log In On The Trade Site Here If You Want. Twice "
                          "Corrupted Never Reads This Window's Cookies.")
            note.setProperty("role", "caption")

            body = QWidget()
            v = QVBoxLayout(body)
            v.setContentsMargins(6, 6, 6, 6)
            v.addLayout(bar)
            v.addWidget(note)
            v.addWidget(self.view, 1)
            self.setCentralWidget(body)
            self.view.urlChanged.connect(
                lambda u: self.address.setText(u.toString()[:160]))

        def open(self, url: str, league: str | None = None) -> None:
            if league:
                self._league = league
            if not is_allowed_url(url):
                log.warning("refusing to open non-trade URL in browser: %s", url)
                QDesktopServices.openUrl(QUrl(url))
                return
            self.view.setUrl(QUrl(url))
            self.show()
            self.raise_()
            self.activateWindow()

        def _clear(self) -> None:
            ok = QMessageBox.question(
                self, "Sign Out & Clear",
                "Delete this window's cookies and cache? You will be "
                "signed out of pathofexile.com here.")
            if ok != QMessageBox.StandardButton.Yes:
                return
            self.profile.cookieStore().deleteAllCookies()
            self.profile.clearHttpCache()
            self.view.reload()

    return TradeBrowserWindow()
