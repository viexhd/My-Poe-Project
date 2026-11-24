"""Main window: a sidebar dashboard.

Layout: a left sidebar (brand, page navigation, Trade Browser, About,
live status chip) and a stack of pages built from large cards.

Pages:
    * Home        – master switch, F12 emergency stop, hotkeys
    * Inventory   – 12×5 slot highlighter + slot profiles + overlay
    * Map Stash   – 12×6 slot highlighter for the Map stash tab
    * Area Select – Alt+drag multi-slot selection settings (manual /
                    experimental transfer)
    * Map Search  – visual map mod exclusion → pathofexile.com/trade link
    * Flipper     – poe.ninja-backed bulk currency flip ranking
    * Pricer      – clipboard-driven trade-site price lookup
    * Wealth      – stash sync from the PoE account (hourly), wealth
                    change over any time range, overlay

Ctrl+1 … Ctrl+8 jump between pages. The sidebar's Trade Browser opens
the in-app pathofexile.com/trade window; About shows GGG's required
third-party disclaimer.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, DISCLAIMER, __version__
from ..paths import app_root

from ..core.config import ConfigStore
from ..core.state import AppState
from ..engine.scheduler import Scheduler
from . import styles as S
from .area_select_widget import AreaSelectWidget
from .components import (
    CardRow, HelpBadge, Page, StatCard, Switch, Tile, caption, card,
)
from .flipper_widget import FlipperWidget
from .icons import icon
from .map_search_widget import MapSearchWidget
from .pricer_widget import PricerWidget
from .slot_selector import SlotSelector
from .wealth_widget import WealthWidget

log = logging.getLogger("poe_qol.ui.main_window")

_REPO = app_root()          # poe_qol/ from source; the exe's folder when packaged
_FONT_DIR = _REPO / "assets" / "brand" / "fonts"

# Short help for known macros (the Home page hotkey list).
_MACRO_HELP = {
    "coord_picker": "<b>capture</b> saves the cursor position. "
                    "<b>show</b> lists the saved positions.",
}

# One short line per page for the Home tiles (index = page index).
_TILE_LINES = {
    1: "Highlight slots to stash",
    2: "Highlight map slots",
    3: "Alt + drag to select",
    4: "Find maps without bad mods",
    5: "Best currencies to flip",
    6: "Ctrl+C an item to price it",
    7: "Divines per hour",
}

# (title, icon, help) for every page, in sidebar order.
_PAGES = [
    ("Home", "home",
     "The master switch and emergency stop for every hotkey."),
    ("Inventory", "inventory",
     "Pick inventory slots, then show the overlay to highlight them in "
     "game. <b>Highlight only</b>: you Ctrl-click the slots yourself."),
    ("Map Stash", "maps",
     "The same highlighter for a 12×6 map stash tab."),
    ("Area Select", "select",
     "Hold <b>Alt</b> and drag over your inventory to select slots, like "
     "selecting files on a desktop. <b>Esc</b> cancels. The drag only "
     "starts inside the calibrated grid, so Alt-clicking loot still works."),
    ("Map Search", "search",
     "Click the map mods you <b>don't</b> want, then open a pre-filled "
     "search on pathofexile.com/trade."),
    ("Flipper", "flip",
     "Ranks currencies worth bulk-flipping, using live poe.ninja prices. "
     "Higher score = more volume, steadier price, bigger margin."),
    ("Pricer", "tag",
     "Copy an item in game (<b>Ctrl+C</b>) and its price appears here."),
    ("Wealth", "wealth",
     "Syncs your stash tabs from your Path of Exile account (hourly if you "
     "like), prices them with poe.ninja and shows how much your wealth "
     "changed over any time range you pick."),
]
_SECTIONS = {0: "PLAY", 4: "TRADE"}


def _load_brand_fonts() -> str | None:
    """Register Six Caps; returns its family name (None if missing)."""
    path = _FONT_DIR / "SixCaps.ttf"
    if not path.exists():
        return None
    fid = QFontDatabase.addApplicationFont(str(path))
    fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
    return fams[0] if fams else None


class MainWindow(QMainWindow):
    def __init__(self, cfg: ConfigStore, state: AppState,
                 scheduler: Scheduler, area_select=None) -> None:
        super().__init__()
        self.cfg = cfg
        self.area_select = area_select   # AreaSelectController or None
        self.state = state
        self.scheduler = scheduler
        self._trade_browser = None   # created on first use

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 780)
        self.setMinimumSize(900, 600)

        root = QWidget()
        root.setObjectName("Content")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.setCentralWidget(root)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")

        open_in_app = (self.open_trade_browser
                       if cfg.get("trade_browser.enabled", True) else None)
        self._wealth = WealthWidget(
            cfg, ninja_cache=_REPO / "logs" / "ninja_cache")
        widgets = [
            self._build_home(),
            SlotSelector(cfg, cfg_path="macros.inventory_dump",
                         title="Inventory", scheduler=scheduler),
            SlotSelector(cfg, cfg_path="macros.map_stash_dump",
                         title="Map Stash", scheduler=scheduler),
            AreaSelectWidget(cfg, area_select),
            MapSearchWidget(cfg, open_in_app=open_in_app),
            # Flipper caches poe.ninja under <repo>/logs/ninja_cache.
            FlipperWidget(cfg, _REPO, open_in_app=open_in_app),
            PricerWidget(cfg),
            self._wealth,
        ]
        for i, ((title, _ic, help_), w) in enumerate(zip(_PAGES, widgets)):
            if i == 0:
                self.pages.addWidget(w)         # Home is already a Page
                continue
            page = Page(title, help_)
            for a in getattr(w, "header_actions", lambda: [])():
                page.add_action(a)
            page.body.addWidget(w, 1)
            if hasattr(w, "footer"):
                page.set_footer(w.footer())
            self.pages.addWidget(page)

        h.addWidget(self._build_sidebar())
        h.addWidget(self.pages, 1)

        # Qt-level fallback shortcut for emergency stop. The primary
        # path is the global `keyboard` hook (input/hotkeys.py), but
        # that fails silently when:
        #   * PoE runs as admin and this app doesn't (Windows UIPI)
        #   * the `keyboard` package isn't installed / lacks privileges
        # In those cases F12 still fires when *our* window has focus,
        # so Alt-Tabbing here and pressing F12 remains a reliable kill.
        self._estop_shortcut = QShortcut(QKeySequence("F12"), self)
        self._estop_shortcut.setContext(
            Qt.ShortcutContext.ApplicationShortcut)
        self._estop_shortcut.activated.connect(self.scheduler.emergency_stop)
        for i in range(len(_PAGES)):
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda i=i: self._nav_select(i))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(400)
        self._refresh_status()

    # ---- sidebar ----
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        v = QVBoxLayout(side)
        v.setContentsMargins(16, 20, 16, 16)
        v.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        from .branding import resolve_icon_path
        ip = resolve_icon_path(_REPO)
        if ip is not None:
            from PySide6.QtGui import QPixmap
            pm = QPixmap(str(ip))
            if not pm.isNull():
                dpr = self.devicePixelRatioF() or 1.0
                pm = pm.scaled(int(38 * dpr), int(38 * dpr),
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                pm.setDevicePixelRatio(dpr)
                logo.setPixmap(pm)
        brand.addWidget(logo)
        name = QLabel("TWICE CORRUPTED")
        name.setObjectName("BrandName")
        fam = _load_brand_fonts()
        if fam:
            name.setStyleSheet(f'font-family:"{fam}"; font-size:30px;')
        else:
            name.setStyleSheet("font-size:15px; font-weight:700;")
        brand.addWidget(name)
        brand.addStretch(1)
        v.addLayout(brand)
        v.addSpacing(14)

        self._nav = QButtonGroup(self)
        self._nav.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        for i, (title, ic, _help) in enumerate(_PAGES):
            if i in _SECTIONS:
                sec = QLabel(_SECTIONS[i])
                sec.setObjectName("NavSection")
                v.addWidget(sec)
            b = QPushButton(f"  {title}")
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setIcon(icon(ic, S.FG_2, checked_color=S.ROT_HI))
            b.setIconSize(QSize(20, 20))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(f"{title}  (Ctrl+{i + 1})")
            self._nav.addButton(b, i)
            self._nav_buttons.append(b)
            v.addWidget(b)
        self._nav.idClicked.connect(self._nav_select)
        self._nav_buttons[0].setChecked(True)

        v.addStretch(1)

        sec = QLabel("TOOLS")
        sec.setObjectName("NavSection")
        v.addWidget(sec)
        trade = QPushButton("  Trade Browser")
        trade.setObjectName("NavButton")
        trade.setIcon(icon("globe", S.FG_2))
        trade.setIconSize(QSize(20, 20))
        trade.setCursor(Qt.CursorShape.PointingHandCursor)
        trade.setToolTip("Open pathofexile.com/trade in an app window. "
                         "Log in there yourself.")
        trade.clicked.connect(lambda: self.open_trade_browser(None))
        v.addWidget(trade)
        about = QPushButton("  About")
        about.setObjectName("NavButton")
        about.setIcon(icon("info", S.FG_2))
        about.setIconSize(QSize(20, 20))
        about.setCursor(Qt.CursorShape.PointingHandCursor)
        about.clicked.connect(self._show_about)
        v.addWidget(about)
        v.addSpacing(12)

        self.status = QLabel("Live")
        self.status.setObjectName("StatusChip")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.status)
        return side

    def _nav_select(self, i: int) -> None:
        if 0 <= i < self.pages.count():
            self.pages.setCurrentIndex(i)
            self._nav_buttons[i].setChecked(True)

    # ---- home page ----
    def _build_home(self) -> QWidget:
        page = Page("Home", _PAGES[0][2])

        top = QGridLayout()
        top.setHorizontalSpacing(18)
        top.setVerticalSpacing(18)

        # Master switch
        mc = StatCard("Macros", "", help=(
            "Master switch for every hotkey. Pressing <b>F12</b> turns it "
            "off; switch it back on to resume."), icon="power")
        mc.value.hide()
        self.master = Switch("On", big=True)
        self.master.setChecked(self.cfg.get("app.global_enabled", True))
        self.master.stateChanged.connect(self._on_master)
        self.master.toggled.connect(
            lambda on: self.master.setText("On" if on else "Off"))
        self.master.setText("On" if self.master.isChecked() else "Off")
        mc.body.insertWidget(1, self.master)
        top.addWidget(mc, 0, 0)

        # Emergency stop
        ec = StatCard("Emergency stop", "", variant="danger", help=(
            "Stops everything at once. <b>F12</b> works from anywhere, "
            "even in game. Lights up red while stopped."), icon="stop",
            accent=S.DANGER)
        ec.value.hide()
        self.estop = QPushButton("Stop  ·  F12")
        # Themed via ui/styles.py: ghost-red by default, fills solid red
        # when armed (`armed` property flipped on by _refresh_status).
        self.estop.setProperty("role", "danger")
        self.estop.setProperty("size", "big")
        self.estop.setProperty("armed", False)
        self.estop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.estop.clicked.connect(self.scheduler.emergency_stop)
        ec.body.insertWidget(1, self.estop)
        top.addWidget(ec, 0, 1)

        # Active macros
        self.active_card = StatCard("Running", "0", help=(
            "Hotkey actions working right now."), icon="refresh")
        top.addWidget(self.active_card, 0, 2)
        for c in range(3):
            top.setColumnStretch(c, 1)
        page.body.addLayout(top)

        # Hotkeys
        hk, body = card("Hotkeys", "Click a box and type a new key combo, "
                        "e.g. <b>ctrl+alt+c</b>. Saved when you leave the box.",
                        icon="target")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        row = 0
        for name, macro in self.scheduler.macros.items():
            cb = Switch(name.replace("_", " ").capitalize())
            cb.setChecked(macro.enabled)
            cb.stateChanged.connect(
                lambda s, n=name:
                self.cfg.set(f"macros.{n}.enabled", bool(s)))
            grid.addWidget(cb, row, 0)
            col = 1
            help_ = _MACRO_HELP.get(name)
            if help_:
                grid.addWidget(HelpBadge(help_), row, col)
            col += 1
            # One line-edit per action in HOTKEYS so macros with
            # several bindings are fully editable from the UI.
            for action, path in macro.HOTKEYS.items():
                lab = QLabel(action)
                lab.setObjectName("FieldLabel")
                grid.addWidget(lab, row, col, Qt.AlignmentFlag.AlignRight)
                le = QLineEdit(self.cfg.get(path, "") or "")
                le.setFixedWidth(130)
                le.setPlaceholderText(action)
                le.editingFinished.connect(
                    lambda le=le, p=path: self._rebind(p, le.text()))
                grid.addWidget(le, row, col + 1)
                col += 2
            row += 1
        grid.setColumnStretch(99, 1)
        body.addLayout(grid)
        if not self.scheduler.macros:
            body.addWidget(caption("No hotkey actions loaded."))

        # Surface any hotkey collision the router detected at
        # bind-time so the user sees it instead of only learning
        # about it via the logs.
        self.conflict_label = QLabel("")
        self.conflict_label.setProperty("role", "note")
        self.conflict_label.setWordWrap(True)
        body.addWidget(self.conflict_label)
        page.body.addWidget(hk)

        # Quick-access tiles
        tiles = []
        for i, line in _TILE_LINES.items():
            title, ic, _help = _PAGES[i]
            t = Tile(title, line, ic)
            t.clicked.connect(lambda i=i: self._nav_select(i))
            tiles.append(t)
        tile_rows = QVBoxLayout()
        tile_rows.setSpacing(18)
        tile_rows.addWidget(CardRow(tiles[:4], min_w=150))
        tile_rows.addWidget(CardRow(tiles[4:] + [QWidget()], min_w=150))
        page.body.addLayout(tile_rows)
        page.body.addStretch(1)
        return page

    # ---- slots ----
    def _on_master(self, s: int) -> None:
        on = bool(s)
        self.cfg.set("app.global_enabled", on)
        self.state.set("global_enabled", on)
        # Re-enabling clears any latched emergency-stop so macros can
        # actually fire again. Without this the app looks healthy but
        # every macro.guard() still returns False.
        if on:
            self.state.clear_emergency()

    def about_text(self) -> str:
        return "\n".join([
            f"{APP_NAME} {__version__}",
            "",
            "A quality-of-life companion for Path of Exile.",
            "It never reads or changes game memory or game files, and "
            "never runs game input on a timer.",
            "The optional experimental area transfer (off by default) "
            "Ctrl-clicks several slots per gesture, which GGG's rules do "
            "not allow.",
            "",
            DISCLAIMER,
        ])

    def open_trade_browser(self, url: str | None = None) -> None:
        """Show the in-app trade browser, optionally at ``url``."""
        from .trade_browser import HOME_URL, create_trade_browser
        league = self.cfg.get("trade.league", "Standard")
        try:
            if self._trade_browser is None:
                self._trade_browser = create_trade_browser(league)
            self._trade_browser.open(url or HOME_URL.format(league=league),
                                     league=league)
        except Exception as e:  # QtWebEngine missing / failed to start
            log.exception("trade browser unavailable")
            QMessageBox.warning(
                self, "Trade Browser",
                f"The in-app browser could not start ({e}). Opening your "
                "normal browser instead.")
            import webbrowser
            webbrowser.open(url or HOME_URL.format(league=league))

    def closeEvent(self, e) -> None:  # noqa: N802
        self._wealth.shutdown()
        if self._trade_browser is not None:
            self._trade_browser.close()
        super().closeEvent(e)

    def _show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        ip = None
        from .branding import resolve_icon_path
        ip = resolve_icon_path(_REPO)
        if ip is not None:
            from PySide6.QtGui import QPixmap
            pm = QPixmap(str(ip))
            if not pm.isNull():
                box.setIconPixmap(pm.scaled(
                    72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        box.setText(self.about_text())
        box.exec()

    def _rebind(self, cfg_path: str, combo: str) -> None:
        self.cfg.set(cfg_path, combo)
        self.scheduler.hotkeys.unbind_all()
        self.scheduler._bind_hotkeys()

    def _set_chip(self, text: str, state: str) -> None:
        if self.status.text() != text:
            self.status.setText(text)
        if self.status.property("state") != state:
            self.status.setProperty("state", state)
            S.repolish(self.status)

    def _refresh_status(self) -> None:
        # Keep the master switch in sync with state so an F12 press
        # (which flips global_enabled off) is visible in the UI.
        want = bool(self.cfg.get("app.global_enabled", True))
        if self.master.isChecked() != want:
            self.master.blockSignals(True)
            self.master.setChecked(want)
            self.master.setText("On" if want else "Off")
            self.master.blockSignals(False)

        # Surface any hotkey conflict reported by the router.
        conflict = getattr(self.scheduler.hotkeys, "last_conflict", None)
        if conflict and self.conflict_label.text() != conflict:
            self.conflict_label.setText(conflict)
        elif not conflict and self.conflict_label.text():
            self.conflict_label.setText("")

        tripped = self.state.stop_event.is_set()
        if self.estop.property("armed") != tripped:
            self.estop.setProperty("armed", tripped)
            S.repolish(self.estop)
        if tripped:
            self._set_chip("● Stopped  ·  switch Macros on", "stopped")
            self.active_card.set("0", "Stopped by F12", color=S.DANGER)
            return

        # Progress-aware active list. Macros expose `progress` as
        # (current, total) while working so we can render
        # "name 5/60" instead of just the name.
        parts: list[str] = []
        for n, m in self.scheduler.macros.items():
            if not m.running:
                continue
            prog = getattr(m, "progress", None)
            if prog:
                parts.append(f"{n} {prog[0]}/{prog[1]}")
            else:
                parts.append(n)
        self.active_card.set(str(len(parts)), ", ".join(parts), color="")
        if parts:
            self._set_chip("● Running: " + ", ".join(parts), "busy")
        elif want:
            self._set_chip("● Live", "live")
        else:
            self._set_chip("○ Macros off", "")
