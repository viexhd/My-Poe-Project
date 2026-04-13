"""Regex-style map-mod input → parsed preview → PoE trade link."""
from __future__ import annotations

import json
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from ..core.config import ConfigStore
from ..trade import ModMap, build_query, build_url, parse


class TradeWidget(QWidget):
    def __init__(self, cfg: ConfigStore):
        super().__init__()
        self.cfg = cfg
        self._modmap: ModMap | None = None
        self._current_query: dict | None = None
        self._build()
        self._reload_modmap()

    # ---- construction ----
    def _build(self) -> None:
        v = QVBoxLayout(self)

        v.addWidget(QLabel(
            "Map-mod query  (use  !  to exclude,  |  for OR,  ,  for AND)"))
        self.input = QLineEdit()
        self.input.setPlaceholderText(
            '!reflect|!no regen, !temporal chains   –   enter query then click Preview')
        self.input.textChanged.connect(self._on_text_changed)
        v.addWidget(self.input)

        # Presets row
        row = QHBoxLayout()
        row.addWidget(QLabel("Preset:"))
        self.preset = QComboBox()
        self.preset.addItem("(custom)")
        for name in (self.cfg.get("trade.presets") or {}).keys():
            self.preset.addItem(name)
        self.preset.currentTextChanged.connect(self._on_preset)
        row.addWidget(self.preset, 1)

        row.addWidget(QLabel("League:"))
        self.league = QLineEdit(self.cfg.get("trade.league", "Standard"))
        self.league.editingFinished.connect(
            lambda: self.cfg.set("trade.league", self.league.text()))
        row.addWidget(self.league, 1)
        v.addLayout(row)

        # Action row
        row2 = QHBoxLayout()
        self.preview_btn = QPushButton("Preview parsed mods")
        self.preview_btn.clicked.connect(self._preview)
        row2.addWidget(self.preview_btn)

        self.gen_btn = QPushButton("Generate Trade Link")
        self.gen_btn.clicked.connect(self._generate)
        row2.addWidget(self.gen_btn)

        self.copy_btn = QPushButton("Copy JSON")
        self.copy_btn.clicked.connect(self._copy_json)
        self.copy_btn.setEnabled(False)
        row2.addWidget(self.copy_btn)
        v.addLayout(row2)

        # Preview pane
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Parsed query + JSON appear here.")
        v.addWidget(self.preview, 1)

        # Result URL
        self.url_field = QLineEdit()
        self.url_field.setReadOnly(True)
        self.url_field.setPlaceholderText("Trade URL will appear here after Generate.")
        v.addWidget(self.url_field)

    # ---- helpers ----
    def _reload_modmap(self) -> None:
        path = Path(self.cfg.get("trade.mod_map_file",
                                 "config/map_mods.yaml"))
        if not path.exists():
            self.preview.setPlainText(f"[mod map missing: {path}]")
            return
        try:
            self._modmap = ModMap.load(path)
        except Exception as e:
            self.preview.setPlainText(f"[failed to load mod map: {e}]")

    def _on_text_changed(self, _: str) -> None:
        self.copy_btn.setEnabled(False)
        self._current_query = None

    def _on_preset(self, name: str) -> None:
        if not name or name == "(custom)":
            return
        text = (self.cfg.get("trade.presets") or {}).get(name, "")
        self.input.setText(text)

    # ---- actions ----
    def _preview(self) -> None:
        if not self._modmap:
            self._reload_modmap()
        if not self._modmap:
            return
        parsed = parse(self.input.text())
        lines: list[str] = []
        lines.append(f"Parsed:  {parsed}")
        lines.append("")
        unknown: list[str] = []
        for g in parsed.groups:
            parts = []
            for a in g.atoms:
                hit = self._modmap.resolve(a.mod)
                if hit:
                    parts.append(
                        ("NOT " if a.negate else "")
                        + f"{hit[0]} [{hit[1]}]"
                    )
                else:
                    parts.append(
                        ("NOT " if a.negate else "")
                        + f"{a.mod}  (UNKNOWN)"
                    )
                    unknown.append(a.mod)
            kind = "AND"
            if len(g.atoms) > 1:
                kind = "OR(all-neg→count≤N-1)" if g.all_negative else \
                       "OR(count≥1)" if g.all_positive else "OR(mixed)"
            lines.append(f"  [{kind}]  " + "  |  ".join(parts))
        query = build_query(
            parsed, self._modmap,
            league=self.cfg.get("trade.league", "Standard"),
            status=self.cfg.get("trade.status", "online"),
            item_category=self.cfg.get("trade.item_category", "map"),
        )
        self._current_query = query
        # JSON view without league marker
        view = {k: v for k, v in query.items() if not k.startswith("__")}
        lines.append("")
        lines.append("JSON payload:")
        lines.append(json.dumps(view, indent=2))
        if unknown:
            lines.append("")
            lines.append("Unknown mods (won't appear in URL): "
                         + ", ".join(sorted(set(unknown))))
        self.preview.setPlainText("\n".join(lines))
        self.copy_btn.setEnabled(True)

    def _generate(self) -> None:
        if self._current_query is None:
            self._preview()
        if self._current_query is None:
            return
        mode = self.cfg.get("trade.url_mode", "copy")
        try:
            url = build_url(
                self._current_query, mode=mode,
                base_site=self.cfg.get(
                    "trade.base_site",
                    "https://www.pathofexile.com/trade/search"),
                base_api=self.cfg.get(
                    "trade.base_api",
                    "https://www.pathofexile.com/api/trade/search"),
            )
        except Exception as e:
            QMessageBox.warning(self, "Trade link failed", str(e))
            return
        self.url_field.setText(url)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _copy_json(self) -> None:
        if self._current_query is None:
            return
        view = {k: v for k, v in self._current_query.items()
                if not k.startswith("__")}
        QGuiApplication.clipboard().setText(json.dumps(view, indent=2))
