"""Cursor-driven grid calibration.

Workflow:
    1. Open this dialog. A global hotkey (default F8) is bound while
       it is visible.
    2. Hover the centre of the *top-left* slot in PoE, press F8.
    3. Hover the centre of the *top-right* slot (last column of the
       first row) and press F8.
    4. Hover the centre of the *bottom-left* slot (first column of
       the last row) and press F8.
    5. Click OK – writes origin + cell_size back to config AND
       persists them to ``config/user.yaml`` so they survive a
       restart. If the PoE window is detected, also writes
       ``origin_relative_to_window`` so moving / resizing the window
       survives.

Measuring across the full grid (rather than adjacent neighbours)
divides the pixel-precision error by (cols-1) / (rows-1), so the
overlay highlights stay aligned all the way to the far corner.

The hotkey is rebindable from the Hotkey field in the dialog.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout,
)

from ..core.config import ConfigStore

try:
    import pydirectinput as _di  # type: ignore
except Exception:  # pragma: no cover
    _di = None

try:
    import keyboard as _kb  # type: ignore
except Exception:  # pragma: no cover
    _kb = None


def _cursor() -> Optional[tuple[int, int]]:
    if _di is None:
        return None
    try:
        return tuple(_di.position())  # type: ignore[return-value]
    except Exception:
        return None


# Order of capture steps. Corner-to-corner: this divides the
# per-capture pixel error by (cols-1) / (rows-1) instead of leaving
# it to compound across the grid.
_STEPS = ("tl", "tr", "bl")
_STEP_LABEL = {
    "tl": "Hover the TOP-LEFT slot, then press the hotkey.",
    "tr": "Hover the TOP-RIGHT slot (last column, first row), then press the hotkey.",
    "bl": "Hover the BOTTOM-LEFT slot (first column, last row), then press the hotkey.",
}


class CalibrateDialog(QDialog):
    # Cross-thread signal — the keyboard hook fires on its own thread.
    captured = Signal()

    def __init__(self, cfg: ConfigStore, parent=None,
                 cfg_path: str = "macros.inventory_dump",
                 title: str = "Inventory"):
        super().__init__(parent)
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.setWindowTitle(f"Calibrate {title} grid")
        self.setModal(True)
        self._captures: dict[str, tuple[int, int]] = {}
        self._step_idx: int = 0
        self._hotkey_handle = None
        self._hotkey_combo = "f8"
        self._build()

        self.captured.connect(self._on_captured)
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._tick_cursor)
        self._cursor_timer.start(50)

        self._bind_hotkey(self._hotkey_combo)

    def _k(self, *parts: str) -> str:
        return ".".join((self.cfg_path, *parts))

    # ---- construction ----
    def _build(self) -> None:
        v = QVBoxLayout(self)

        v.addWidget(QLabel(
            "Calibration uses a global hotkey so the cursor can stay over\n"
            "the game. Hover each requested slot in PoE, then tap the hotkey.\n"
            "(Nothing is clicked — only the cursor position is read.)"))

        # Hotkey row
        hk_row = QHBoxLayout()
        hk_row.addWidget(QLabel("Capture hotkey:"))
        self.hk_input = QLineEdit(self._hotkey_combo)
        self.hk_input.setMaximumWidth(120)
        self.hk_input.editingFinished.connect(
            lambda: self._bind_hotkey(self.hk_input.text().strip() or "f8"))
        hk_row.addWidget(self.hk_input)
        hk_row.addStretch(1)
        v.addLayout(hk_row)

        self.cursor_label = QLabel("Cursor: —")
        self.cursor_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.cursor_label)

        # Step prompt
        self.prompt = QLabel("")
        self.prompt.setStyleSheet("font-weight: bold; padding: 6px;")
        self.prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt.setWordWrap(True)
        v.addWidget(self.prompt)

        # Captured values
        form = QFormLayout()
        self.lbl_tl = QLabel("—")
        self.lbl_tr = QLabel("—")
        self.lbl_bl = QLabel("—")
        cols = self.cfg.get(self._k("grid", "cols"), 12)
        rows = self.cfg.get(self._k("grid", "rows"), 5)
        form.addRow("Top-left (0,0):", self.lbl_tl)
        form.addRow(f"Top-right (0,{cols - 1}):", self.lbl_tr)
        form.addRow(f"Bottom-left ({rows - 1},0):", self.lbl_bl)
        v.addLayout(form)

        # Reset / redo row
        ctl = QHBoxLayout()
        for label, fn in (("Reset", self._reset),
                          ("Redo last", self._redo_last)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            ctl.addWidget(b)
        v.addLayout(ctl)

        # Window anchor selector – optional
        anchor_row = QHBoxLayout()
        anchor_row.addWidget(QLabel("Save as window-relative from:"))
        self.anchor_combo = QComboBox()
        self.anchor_combo.addItems(["(disabled)", "top_left", "top_right",
                                    "bottom_left", "bottom_right"])
        self.anchor_combo.setCurrentText("top_right")
        anchor_row.addWidget(self.anchor_combo, 1)
        v.addLayout(anchor_row)

        self.status = QLabel("")
        v.addWidget(self.status)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._apply)
        box.rejected.connect(self.reject)
        v.addWidget(box)
        self.ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setEnabled(False)

        self._refresh_prompt()

    # ---- hotkey ----
    def _bind_hotkey(self, combo: str) -> None:
        self._unbind_hotkey()
        self._hotkey_combo = combo
        if _kb is None:
            self.status.setText(
                "WARNING: 'keyboard' library not available — "
                "calibration hotkey disabled.")
            return
        try:
            # Emit signal so we hop back to the Qt thread before touching UI.
            self._hotkey_handle = _kb.add_hotkey(
                combo, lambda: self.captured.emit(),
                suppress=False)
        except Exception as e:
            self.status.setText(f"Failed to bind {combo!r}: {e}")

    def _unbind_hotkey(self) -> None:
        if self._hotkey_handle is not None and _kb is not None:
            try:
                _kb.remove_hotkey(self._hotkey_handle)
            except Exception:
                pass
        self._hotkey_handle = None

    def closeEvent(self, e):  # noqa: N802 – Qt naming
        self._unbind_hotkey()
        super().closeEvent(e)

    def reject(self):  # noqa: D401 – Qt override
        self._unbind_hotkey()
        super().reject()

    # ---- live cursor ----
    def _tick_cursor(self) -> None:
        pos = _cursor()
        self.cursor_label.setText(
            f"Cursor: {pos[0]}, {pos[1]}" if pos else "Cursor: unavailable")

    # ---- capture flow ----
    def _on_captured(self) -> None:
        if self._step_idx >= len(_STEPS):
            return
        pos = _cursor()
        if not pos:
            self.status.setText("Could not read cursor position.")
            return
        step = _STEPS[self._step_idx]
        self._captures[step] = pos
        self._update_label(step, pos)
        self._step_idx += 1
        self._refresh_prompt()
        self._refresh_summary()

    def _update_label(self, step: str, pos: tuple[int, int]) -> None:
        text = f"{pos[0]}, {pos[1]}"
        {"tl": self.lbl_tl, "tr": self.lbl_tr, "bl": self.lbl_bl}[step].setText(text)

    def _refresh_prompt(self) -> None:
        if self._step_idx >= len(_STEPS):
            self.prompt.setText(
                "Done — review the captured points and click OK.")
        else:
            step = _STEPS[self._step_idx]
            self.prompt.setText(
                f"[{self._step_idx + 1}/{len(_STEPS)}]  "
                + _STEP_LABEL[step]
                + f"\n(hotkey: {self._hotkey_combo})"
            )

    def _cell_size(self) -> tuple[float, float]:
        """Derive (cell_w, cell_h) from the three captures using the
        FULL grid distance — cuts calibration drift to sub-pixel."""
        c = self._captures
        cols = self.cfg.get(self._k("grid", "cols"), 12)
        rows = self.cfg.get(self._k("grid", "rows"), 5)
        cw = (c["tr"][0] - c["tl"][0]) / max(1, cols - 1)
        ch = (c["bl"][1] - c["tl"][1]) / max(1, rows - 1)
        return cw, ch

    def _refresh_summary(self) -> None:
        c = self._captures
        if not all(k in c for k in _STEPS):
            self.status.setText("")
            self.ok_btn.setEnabled(False)
            return
        cw, ch = self._cell_size()
        self.status.setText(
            f"origin=({c['tl'][0]},{c['tl'][1]})  "
            f"cell_size=({cw:.2f},{ch:.2f})")
        self.ok_btn.setEnabled(cw > 0 and ch > 0)

    def _reset(self) -> None:
        self._captures.clear()
        self._step_idx = 0
        for lbl in (self.lbl_tl, self.lbl_tr, self.lbl_bl):
            lbl.setText("—")
        self._refresh_prompt()
        self._refresh_summary()

    def _redo_last(self) -> None:
        if self._step_idx == 0:
            return
        self._step_idx -= 1
        step = _STEPS[self._step_idx]
        self._captures.pop(step, None)
        {"tl": self.lbl_tl, "tr": self.lbl_tr,
         "bl": self.lbl_bl}[step].setText("—")
        self._refresh_prompt()
        self._refresh_summary()

    # ---- apply ----
    def _apply(self) -> None:
        c = self._captures
        if not all(k in c for k in _STEPS):
            return
        cw, ch = self._cell_size()
        # Round to 2dp so user.yaml stays readable; the sweep rounds
        # to int at the point of use so cumulative drift stays below
        # 1px even for large grids.
        self.cfg.set(self._k("grid", "origin"),
                     [c["tl"][0], c["tl"][1]])
        self.cfg.set(self._k("grid", "cell_size"),
                     [round(cw, 2), round(ch, 2)])

        anchor = self.anchor_combo.currentText()
        if anchor and anchor != "(disabled)":
            try:
                from ..vision.window import find_window
                rect = find_window(
                    self.cfg.get(
                        self._k("window", "title_pattern"),
                        "Path of Exile"),
                    self.cfg.get(
                        self._k("window", "class_pattern")),
                )
                if rect is None:
                    self.cfg.set(
                        self._k("origin_relative_to_window"),
                        None)
                    self.status.setText(
                        "Saved absolute origin. PoE window not detected, "
                        "so window-relative offset was not stored.")
                else:
                    ax, ay = rect.anchor(anchor)
                    dx = c["tl"][0] - ax
                    dy = c["tl"][1] - ay
                    # window_size lets the overlay / area select scale
                    # the grid when the game resolution changes.
                    self.cfg.set(
                        self._k("origin_relative_to_window"),
                        {"anchor": anchor, "offset": [dx, dy],
                         "window_size": [rect.width, rect.height]})
            except Exception:
                pass
        else:
            self.cfg.set(
                self._k("origin_relative_to_window"), None)

        # Persist calibration so it survives restart.
        try:
            self.cfg.save_user_overrides([
                self._k("grid", "origin"),
                self._k("grid", "cell_size"),
                self._k("origin_relative_to_window"),
            ])
        except Exception:
            pass

        self._unbind_hotkey()
        self.accept()
