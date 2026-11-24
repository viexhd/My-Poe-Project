"""Visual map-search tab.

Replaces the old regex-style ``TradeWidget``. Workflow:

    1. Pick an Item Type (defaults to Tier 16 Map).
    2. Set Rarity / Corrupted / Min # Modifiers filters.
       Min # Modifiers emits the trade-site "# Modifiers" pseudo
       (pseudo.pseudo_number_of_affix_mods, e.g. 8 for 8-mod rares).
    3. Toggle mods in the category sections – selected = *excluded*.
    4. Optionally save the current selection as a named user preset
       (right-click a preset button to delete it).
    5. Click **Open Trade** to POST the query to pathofexile.com and
       open the resulting canonical search URL in the browser.

All mod data (names, stat ids, categories, item types) lives in
``config/map_mods.yaml``; nothing is hard-coded here. User presets
live in the per-user config, not the shipped YAML.
"""
from __future__ import annotations

import json
import logging
import webbrowser
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore
from .text import capitalise
from ..trade import MapDataset, build_map_query, build_url

log = logging.getLogger("poe_qol.ui.map_search")


# Config dot-paths persisted via cfg.save_user_overrides() so the last
# selection survives a restart.
_CFG_EXCLUDED = "trade.excluded_mods"
_CFG_ITEM_TYPE = "trade.item_type_id"
_CFG_LEAGUE = "trade.league"
_CFG_STATUS = "trade.status"
_CFG_RARITY = "trade.rarity"
_CFG_CORRUPTED = "trade.corrupted"
_CFG_MIN_MODS = "trade.min_modifiers"
# User-defined presets: list of {"name": str, "excluded": [mod_id, ...]}.
# Kept separate from dataset.presets so the YAML can stay free of
# personal bookmarks and upgrades to map_mods.yaml won't clobber them.
_CFG_USER_PRESETS = "trade.user_presets"

# Dropdowns: label shown to user -> trade-API value (None disables).
_RARITY_OPTIONS: list[tuple[str, str | None]] = [
    ("Any",        None),
    ("Non-Unique", "nonunique"),
    ("Rare",       "rare"),
    ("Magic",      "magic"),
    ("Normal",     "normal"),
    ("Unique",     "unique"),
]
_CORRUPTED_OPTIONS: list[tuple[str, str | None]] = [
    ("Any",        None),
    ("Corrupted",  "true"),
    ("Not Corrupted", "false"),
]


def _tint_rgba(hex_color: str, alpha: float) -> str:
    """``#RRGGBB`` + alpha (0..1) → ``rgba(r,g,b,a)`` for QSS.

    Used so category colors from ``map_mods.yaml`` can be rendered as
    soft translucent fills in dark mode without precomputing variants.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return hex_color
    a = max(0.0, min(1.0, alpha))
    return f"rgba({r},{g},{b},{a:.3f})"


class _ModButton(QPushButton):
    """Checkable button wired to a single mod id. Stays visually
    distinct in checked state via styleSheet (Qt default is subtle)."""

    def __init__(self, mod_id: str, label: str, color: str) -> None:
        super().__init__(label)
        self.mod_id = mod_id
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        # Checked uses a translucent fill with a solid category-colored
        # border so neighboring chips don't visually clash on dark bg.
        # `_tint_rgba` keeps alpha independent of the source hex.
        tint = _tint_rgba(color, 0.28)
        self.setMinimumHeight(40)
        self.setToolTip(label)
        self.setStyleSheet(
            "QPushButton { padding: 8px 12px; border: 1px solid #33262A;"
            " border-radius: 10px; background:#1C1518; color:#EFE6DA;"
            " text-align:left; font-size:13px; }"
            f"QPushButton:checked {{ background: {tint};"
            f" border: 1px solid {color}; color:#FFFFFF;"
            " font-weight: 600; }"
            "QPushButton:hover { border: 1px solid #4A363C;"
            " background:#261C20; }"
        )


class MapSearchWidget(QWidget):
    def __init__(self, cfg: ConfigStore,
                 open_in_app: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        # Opens a URL in the in-app trade browser (MainWindow supplies
        # it). None = use the system browser.
        self._open_in_app = open_in_app
        self.dataset: MapDataset | None = None
        self._buttons: dict[str, _ModButton] = {}
        self._category_rows: list[tuple[str, QWidget]] = []
        self._build()
        self._reload_dataset()
        self._restore_selection()

    # -----------------------------------------------------------------
    # Construction
    # -----------------------------------------------------------------
    def _build(self) -> None:
        from . import styles as S
        from .components import card, field
        from .icons import icon

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        # ---- filters card ----
        fc, fl = card()
        g = QGridLayout()
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(14)
        self.type_box = QComboBox()
        self.type_box.currentIndexChanged.connect(self._on_type_changed)
        g.addWidget(field("Item", self.type_box), 0, 0, 1, 2)

        from .league import LeagueBox
        self.league_box = LeagueBox(self.cfg, _CFG_LEAGUE)
        g.addWidget(field("League", self.league_box,
                          "<b>Latest</b> always follows the newest "
                          "challenge league."), 0, 2)

        self.status_box = QComboBox()
        for label, value in (("Online", "online"),
                             ("Online In League", "onlineleague"),
                             ("Any", "any")):
            self.status_box.addItem(label, value)
        self.status_box.setCurrentIndex(max(0, self.status_box.findData(
            self.cfg.get(_CFG_STATUS, "online"))))
        self.status_box.currentIndexChanged.connect(
            lambda _i: self.cfg.set(_CFG_STATUS, self.status_box.currentData()))
        g.addWidget(field("Sellers", self.status_box,
                          "<b>online</b>: sellers online now. "
                          "<b>any</b>: include offline sellers."), 0, 3)

        # "# Modifiers" is the trade-site pseudo stat
        # (pseudo.pseudo_number_of_affix_mods). The trade API rejects
        # map_filters.map_num_mods, but this pseudo is accepted and is
        # what pathofexile.com/trade emits when you pick "# Modifiers"
        # from the stat search. Spin value 0 means "don't emit".
        # Default values are populated in _apply_dataset_defaults() once
        # the dataset has loaded — we need its .defaults block to know
        # what to preselect.
        self.rarity_box = QComboBox()
        for label, value in _RARITY_OPTIONS:
            self.rarity_box.addItem(label, value)
        self.rarity_box.currentIndexChanged.connect(
            lambda _=0: self._persist_filter(
                _CFG_RARITY, self.rarity_box.currentData()))
        g.addWidget(field("Rarity", self.rarity_box), 1, 0)

        self.corrupted_box = QComboBox()
        for label, value in _CORRUPTED_OPTIONS:
            self.corrupted_box.addItem(label, value)
        self.corrupted_box.currentIndexChanged.connect(
            lambda _=0: self._persist_filter(
                _CFG_CORRUPTED, self.corrupted_box.currentData()))
        g.addWidget(field("Corrupted", self.corrupted_box), 1, 1)

        self.min_mods_spin = QSpinBox()
        self.min_mods_spin.setRange(0, 8)          # 0 = off
        self.min_mods_spin.setSpecialValueText("Off")
        self.min_mods_spin.valueChanged.connect(
            lambda v: self._persist_filter(_CFG_MIN_MODS, int(v)))
        g.addWidget(field("Min Mods", self.min_mods_spin,
                          "Fewest mods the map must have. <b>8</b> finds "
                          "8-mod corrupted rares. <b>Off</b> = any."), 1, 2)
        for c in range(4):
            g.setColumnStretch(c, 1)
        # Combos size to their longest entry by default, which would
        # push the page wider than a small window.
        for box in (self.type_box, self.status_box, self.rarity_box,
                    self.corrupted_box):
            box.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(6)
        fl.addLayout(g)
        root.addWidget(fc)

        # ---- mods card ----
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search Mods…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(150)
        self.search_edit.textChanged.connect(self._apply_search)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setProperty("role", "pill")
        self.clear_btn.setToolTip("Un-pick every mod.")
        self.clear_btn.clicked.connect(self._clear_selection)
        right = QHBoxLayout()
        right.setSpacing(8)
        right.addWidget(self.search_edit)
        right.addWidget(self.clear_btn)
        mc, ml = card("Mods To Avoid", (
            "Click every mod you <b>don't</b> want. Picked mods turn "
            "coloured and are left out of the search."),
            right=right, icon="search")

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(220)
        self.scroll_body = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_body)
        self.scroll_layout.setContentsMargins(0, 0, 6, 0)
        self.scroll_layout.setSpacing(14)
        self.scroll.setWidget(self.scroll_body)
        ml.addWidget(self.scroll, 1)

        # ---- presets row ----
        self.preset_row_frame = QFrame()
        self.preset_row = QHBoxLayout(self.preset_row_frame)
        self.preset_row.setContentsMargins(0, 0, 0, 0)
        self.preset_row.setSpacing(8)
        ml.addWidget(self.preset_row_frame)
        root.addWidget(mc, 1)

        # ---- bottom bar: summary + actions ----
        bc, bl = card(variant="gilt", padding=16)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.preview = QLabel("No Mods Excluded")
        self.preview.setWordWrap(False)
        self.preview.setProperty("role", "muted")
        actions.addWidget(self.preview, 1)

        self.copy_url_btn = QPushButton()
        self.copy_url_btn.setIcon(icon("copy", S.FG_1))
        self.copy_url_btn.setToolTip("Copy the search link")
        self.copy_url_btn.setAccessibleName("Copy link")
        self.copy_url_btn.clicked.connect(self._copy_url)
        actions.addWidget(self.copy_url_btn)

        self.copy_json_btn = QPushButton("{ }")
        self.copy_json_btn.setToolTip("Copy the raw trade query (JSON)")
        self.copy_json_btn.setAccessibleName("Copy JSON")
        self.copy_json_btn.clicked.connect(self._copy_json)
        actions.addWidget(self.copy_json_btn)

        self.open_ext_btn = QPushButton()
        self.open_ext_btn.setIcon(icon("external", S.FG_1))
        self.open_ext_btn.setToolTip("Open in your normal browser")
        self.open_ext_btn.setAccessibleName("Open in my browser")
        self.open_ext_btn.clicked.connect(lambda: self._open_trade(external=True))
        actions.addWidget(self.open_ext_btn)

        self.open_btn = QPushButton("Open Trade")
        self.open_btn.setProperty("role", "primary")
        self.open_btn.setProperty("size", "big")
        self.open_btn.setIcon(icon("globe", "#1A1200"))
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.setToolTip(
            "Open the pre-filled search on pathofexile.com/trade "
            "(in the Trade Browser window when it is enabled).")
        self.open_btn.clicked.connect(self._open_trade)
        actions.addWidget(self.open_btn)
        bl.addLayout(actions)
        self.action_bar = bc
        root.addWidget(bc)

    def footer(self) -> QWidget:
        """The summary + Open Trade bar; MainWindow pins it to the page
        bottom so it stays visible while the mod list scrolls."""
        return self.action_bar

    # -----------------------------------------------------------------
    # Dataset loading / rendering
    # -----------------------------------------------------------------
    def _reload_dataset(self) -> None:
        path = Path(self.cfg.get("trade.mod_map_file",
                                 "config/map_mods.yaml"))
        if not path.exists():
            self.preview.setText(f"[Mod Data Missing: {path}]")
            return
        try:
            self.dataset = MapDataset.load(path)
        except Exception as e:
            log.exception("failed to load map dataset")
            self.preview.setText(f"[Failed To Load Mod Data: {e}]")
            return
        self._populate_type_box()
        self._populate_categories()
        self._populate_presets()
        self._apply_dataset_defaults()

    def _populate_type_box(self) -> None:
        assert self.dataset is not None
        self.type_box.blockSignals(True)
        self.type_box.clear()
        for t in self.dataset.item_types:
            self.type_box.addItem(t.name, t.id)
        # Default: config value, else Map (Tier 16), else first entry.
        want = self.cfg.get(_CFG_ITEM_TYPE) or "map_t16"
        idx = self.type_box.findData(want)
        self.type_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.type_box.blockSignals(False)

    def _populate_categories(self) -> None:
        assert self.dataset is not None
        # Clear existing category widgets.
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._buttons.clear()
        self._category_rows.clear()

        for cat in self.dataset.categories:
            section = QFrame()
            sec_v = QVBoxLayout(section)
            sec_v.setContentsMargins(0, 0, 0, 0)
            sec_v.setSpacing(8)

            # A coloured dot + name keeps the category tint visible at a
            # glance without shouting over the chips inside it.
            header = QLabel(
                f"<span style='color:{cat.color}; font-size:16px'>●</span>"
                f"&nbsp; {cat.name}")
            header.setStyleSheet(
                "color:#EFE6DA; font-weight:600; font-size:14px;")
            sec_v.addWidget(header)

            from .components import FlowLayout
            grid_host = QWidget()
            flow = FlowLayout(grid_host, spacing=8)

            for m in self.dataset.mods_in_category(cat.id):
                btn = _ModButton(m.id, capitalise(m.name), cat.color)
                btn.toggled.connect(self._on_mod_toggled)
                flow.addWidget(btn)
                self._buttons[m.id] = btn
            sec_v.addWidget(grid_host)

            self.scroll_layout.addWidget(section)
            self._category_rows.append((cat.id, section))
        self.scroll_layout.addStretch(1)

    def _populate_presets(self) -> None:
        """Render user-defined preset buttons + Save/Delete controls.

        We no longer ship default presets — users build their own
        named exclusion sets via *Save Preset*. Any `dataset.presets`
        entries (for back-compat with YAMLs that still have them) are
        rendered as read-only buttons after the user ones.
        """
        assert self.dataset is not None
        # Clear existing preset widgets.
        while self.preset_row.count():
            item = self.preset_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        lab = QLabel("Presets")
        lab.setObjectName("FieldLabel")
        self.preset_row.addWidget(lab)
        from .components import HelpBadge
        self.preset_row.addWidget(HelpBadge(
            "Saved sets of mods. Click to apply, right-click to delete."))

        # User-defined presets (stored in cfg).
        for idx, p in enumerate(self._user_presets()):
            name = str(p.get("name") or "unnamed")
            excluded = list(p.get("excluded") or [])
            b = QPushButton(name)
            b.setProperty("role", "pill")
            b.setToolTip(
                f"Apply user preset '{name}' ({len(excluded)} mod(s)). "
                "Right-click to delete.")
            b.clicked.connect(
                lambda _=False, ex=excluded: self._apply_excluded_ids(ex))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda _pos, i=idx: self._delete_user_preset(i))
            self.preset_row.addWidget(b)

        # Any legacy YAML presets — still honoured if present.
        for p in self.dataset.presets:
            b = QPushButton(p.name)
            b.setProperty("role", "pill")
            if p.description:
                b.setToolTip(p.description + " (from map_mods.yaml)")
            b.clicked.connect(lambda _checked=False, pid=p.id:
                              self._apply_preset(pid))
            self.preset_row.addWidget(b)

        # Save-current-selection button.
        save = QPushButton("+ Save")
        save.setProperty("role", "pill")
        save.setToolTip(
            "Save the current exclusion set as a named preset (stored "
            "in your user config).")
        save.clicked.connect(self._save_user_preset)
        self.preset_row.addWidget(save)
        self.preset_row.addStretch(1)

    # ---- user presets ----
    def _user_presets(self) -> list[dict]:
        raw = self.cfg.get(_CFG_USER_PRESETS) or []
        if not isinstance(raw, list):
            return []
        return [p for p in raw if isinstance(p, dict)]

    def _save_user_preset(self) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(
                self, "Save Preset",
                "Select At Least One Mod To Exclude Before Saving.")
            return
        name, ok = QInputDialog.getText(
            self, "Save Preset", "Preset Name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        presets = self._user_presets()
        # Overwrite any preset with the same name so users can iterate.
        presets = [p for p in presets if p.get("name") != name]
        presets.append({"name": name, "excluded": list(ids)})
        self.cfg.set(_CFG_USER_PRESETS, presets)
        try:
            self.cfg.save_user_overrides([_CFG_USER_PRESETS])
        except Exception:
            log.exception("failed to persist user preset")
        self._populate_presets()

    def _delete_user_preset(self, idx: int) -> None:
        presets = self._user_presets()
        if not (0 <= idx < len(presets)):
            return
        name = presets[idx].get("name", "?")
        if QMessageBox.question(
                self, "Delete Preset",
                f"Delete Preset '{name}'?") != QMessageBox.StandardButton.Yes:
            return
        del presets[idx]
        self.cfg.set(_CFG_USER_PRESETS, presets)
        try:
            self.cfg.save_user_overrides([_CFG_USER_PRESETS])
        except Exception:
            log.exception("failed to persist user preset deletion")
        self._populate_presets()

    def _apply_excluded_ids(self, ids: list[str]) -> None:
        wanted = set(ids)
        for mid, btn in self._buttons.items():
            btn.blockSignals(True)
            btn.setChecked(mid in wanted)
            btn.blockSignals(False)
        self._update_preview()
        self._persist_selection()

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------
    def _on_type_changed(self, _idx: int) -> None:
        tid = self.type_box.currentData()
        if tid is None:
            return
        self.cfg.set(_CFG_ITEM_TYPE, tid)
        self._persist_prefs()

    def _on_mod_toggled(self, _checked: bool) -> None:
        self._update_preview()
        self._persist_selection()

    def _apply_search(self, text: str) -> None:
        if not self.dataset:
            return
        needle = text.strip().lower()
        # Hide / show each category based on whether it has any visible mod.
        for cat_id, section in self._category_rows:
            any_visible = False
            for m in self.dataset.mods_in_category(cat_id):
                btn = self._buttons.get(m.id)
                if btn is None:
                    continue
                visible = m.matches(needle)
                btn.setVisible(visible)
                any_visible = any_visible or visible
            section.setVisible(any_visible)

    def _apply_preset(self, preset_id: str) -> None:
        if not self.dataset:
            return
        preset = self.dataset.preset(preset_id)
        if not preset:
            return
        # Replace (not merge) current selection.
        wanted = set(preset.excluded)
        for mid, btn in self._buttons.items():
            btn.blockSignals(True)
            btn.setChecked(mid in wanted)
            btn.blockSignals(False)
        self._update_preview()
        self._persist_selection()

    def _clear_selection(self) -> None:
        for btn in self._buttons.values():
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)
        self._update_preview()
        self._persist_selection()

    # -----------------------------------------------------------------
    # Selection / preview
    # -----------------------------------------------------------------
    def _selected_ids(self) -> list[str]:
        return [mid for mid, b in self._buttons.items() if b.isChecked()]

    def _update_preview(self) -> None:
        if not self.dataset:
            return
        ids = self._selected_ids()
        if not ids:
            self.preview.setText("No Mods Excluded")
            self.preview.setToolTip("")
            return
        # Show the nice name, grouped by category.
        by_cat: dict[str, list[str]] = {}
        for mid in ids:
            m = self.dataset.mod(mid)
            if m is None:
                continue
            by_cat.setdefault(m.category, []).append(m.name)
        parts: list[str] = []
        for cat in self.dataset.categories:
            names = by_cat.get(cat.id)
            if names:
                parts.append(f"<b>{cat.name}</b>: " + ", ".join(names))
        n = len(ids)
        self.preview.setText(
            f"<b style='color:#EFE6DA'>{n}</b> Mod{'s' if n != 1 else ''} "
            f"Excluded")
        self.preview.setToolTip("<br>".join(parts))

    def _restore_selection(self) -> None:
        saved = self.cfg.get(_CFG_EXCLUDED) or []
        for mid in saved:
            btn = self._buttons.get(mid)
            if btn is None:
                continue
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
        self._update_preview()

    def _persist_selection(self) -> None:
        self.cfg.set(_CFG_EXCLUDED, self._selected_ids())
        self._persist_prefs()

    def _persist_prefs(self) -> None:
        try:
            self.cfg.save_user_overrides(
                [_CFG_EXCLUDED, _CFG_ITEM_TYPE, _CFG_LEAGUE, _CFG_STATUS,
                 _CFG_RARITY, _CFG_CORRUPTED, _CFG_MIN_MODS,
                 _CFG_USER_PRESETS])
        except Exception:
            log.exception("failed to persist trade prefs")

    def _persist_filter(self, key: str, value) -> None:
        self.cfg.set(key, value)
        self._persist_prefs()

    def _apply_dataset_defaults(self) -> None:
        """Seed rarity / corrupted widgets from the user's saved value,
        falling back to ``dataset.defaults``. Called once after the
        dataset loads."""
        if not self.dataset:
            return
        d = self.dataset.defaults

        rarity = self.cfg.get(_CFG_RARITY, d.rarity)
        idx = self.rarity_box.findData(rarity)
        self.rarity_box.blockSignals(True)
        self.rarity_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.rarity_box.blockSignals(False)

        corrupted = self.cfg.get(_CFG_CORRUPTED, d.corrupted)
        idx = self.corrupted_box.findData(corrupted)
        self.corrupted_box.blockSignals(True)
        self.corrupted_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.corrupted_box.blockSignals(False)

        min_mods = self.cfg.get(_CFG_MIN_MODS, d.min_modifiers)
        try:
            mm_val = int(min_mods) if min_mods is not None else 0
        except (TypeError, ValueError):
            mm_val = 0
        self.min_mods_spin.blockSignals(True)
        self.min_mods_spin.setValue(max(0, min(8, mm_val)))
        self.min_mods_spin.blockSignals(False)

    # -----------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------
    def _current_query(self) -> dict | None:
        if not self.dataset:
            return None
        item_type_id = self.type_box.currentData() or "map_t16"
        return build_map_query(
            self.dataset,
            item_type_id=item_type_id,
            excluded_mod_ids=self._selected_ids(),
            league=self.league_box.league(),
            status=self.cfg.get(_CFG_STATUS, "online"),
            rarity=self.rarity_box.currentData(),
            corrupted=self.corrupted_box.currentData(),
            min_modifiers=self.min_mods_spin.value(),
        )

    def _build_url(self, mode: str) -> str | None:
        q = self._current_query()
        if q is None:
            QMessageBox.warning(self, "Trade", "Mod Data Not Loaded.")
            return None
        try:
            return build_url(
                q, mode=mode,
                base_site=self.cfg.get(
                    "trade.base_site",
                    "https://www.pathofexile.com/trade/search"),
                base_api=self.cfg.get(
                    "trade.base_api",
                    "https://www.pathofexile.com/api/trade/search"),
            )
        except Exception as e:
            QMessageBox.warning(self, "Trade Link Failed", str(e))
            return None

    def _open_trade(self, external: bool = False) -> None:
        # Default "copy" mode builds trade/search/<league>?q=<json>. The
        # trade site runs that search itself when the page loads (the
        # same link format Awakened PoE Trade opens), so no API call is
        # made from this app. "post" mode is the older API-call path.
        mode = self.cfg.get("trade.url_mode", "copy")
        url = self._build_url(mode if mode in ("post", "copy") else "copy")
        if not url:
            return
        if self._open_in_app and not external:
            self._open_in_app(url)
            return
        try:
            webbrowser.open(url)
        except Exception:
            log.exception("failed to open browser")
        # Also drop it on the clipboard so the user has a backup if
        # webbrowser.open silently fails (common on headless Linux).
        QGuiApplication.clipboard().setText(url)

    def _copy_url(self) -> None:
        url = self._build_url(self.cfg.get("trade.url_mode", "copy"))
        if url:
            QGuiApplication.clipboard().setText(url)

    def _copy_json(self) -> None:
        q = self._current_query()
        if q is None:
            return
        view = {k: v for k, v in q.items() if not k.startswith("__")}
        QGuiApplication.clipboard().setText(json.dumps(view, indent=2))
