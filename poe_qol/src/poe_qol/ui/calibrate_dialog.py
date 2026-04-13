"""Cursor-driven grid calibration.

Workflow:
    1. Open this dialog. A global hotkey (default F8) is bound while
       it is visible.
    2. Hover the centre of the *top-left* inventory slot in PoE,
       press F8.
    3. Hover the slot one column to the right, press F8.
    4. Hover the slot one row below the first, press F8.
    5. Click OK – writes origin + cell_size back to config. If the PoE
       window is detected, also writes `origin_relative_to_window` so
       moving / resizing the window survives.

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


# Order of capture steps.
_STEPS = ("tl", "r", "d")
_STEP_LABEL = {
    "tl": "Hover the TOP-LEFT inventory slot, then press the hotkey.",
    "r":  "Hover the slot ONE COLUMN to the right of top-left, then press the hotkey.",
    "d":  "Hover the slot ONE ROW below top-left, then press the hotkey.",
}


class CalibrateDialog(QDialog):
    # Cross-thread signal — the keyboard hook fires on its own thread.
    captured = Signal()

    def __init__(self, cfg: ConfigStore, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Calibrate inventory grid")
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
        self.lbl_r  = QLabel("—")
        self.lbl_d  = QLabel("—")
        form.addRow("Top-left:", self.lbl_tl)
        form.addRow("Right neighbour:", self.lbl_r)
        form.addRow("Below top-left:", self.lbl_d)
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
        {"tl": self.lbl_tl, "r": self.lbl_r, "d": self.lbl_d}[step].setText(text)

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

    def _refresh_summary(self) -> None:
        c = self._captures
        if not all(k in c for k in _STEPS):
            self.status.setText("")
            self.ok_btn.setEnabled(False)
            return
        cw = c["r"][0] - c["tl"][0]
        ch = c["d"][1] - c["tl"][1]
        self.status.setText(
            f"origin=({c['tl'][0]},{c['tl'][1]})  "
            f"cell_size=({cw},{ch})")
        self.ok_btn.setEnabled(cw > 0 and ch > 0)

    def _reset(self) -> None:
        self._captures.clear()
        self._step_idx = 0
        for lbl in (self.lbl_tl, self.lbl_r, self.lbl_d):
            lbl.setText("—")
        self._refresh_prompt()
        self._refresh_summary()

    def _redo_last(self) -> None:
        if self._step_idx == 0:
            return
        self._step_idx -= 1
        step = _STEPS[self._step_idx]
        self._captures.pop(step, None)
        {"tl": self.lbl_tl, "r": self.lbl_r,
         "d": self.lbl_d}[step].setText("—")
        self._refresh_prompt()
        self._refresh_summary()

    # ---- apply ----
    def _apply(self) -> None:
        c = self._captures
        if not all(k in c for k in _STEPS):
            return
        cw = c["r"][0] - c["tl"][0]
        ch = c["d"][1] - c["tl"][1]
        self.cfg.set("macros.inventory_dump.grid.origin",
                     [c["tl"][0], c["tl"][1]])
        self.cfg.set("macros.inventory_dump.grid.cell_size", [cw, ch])

        anchor = self.anchor_combo.currentText()
        if anchor and anchor != "(disabled)":
            try:
                from ..vision.window import find_window
                rect = find_window(
                    self.cfg.get(
                        "macros.inventory_dump.window.title_pattern",
                        "Path of Exile"),
                    self.cfg.get(
                        "macros.inventory_dump.window.class_pattern"),
                )
                if rect is None:
                    self.cfg.set(
                        "macros.inventory_dump.origin_relative_to_window",
                        None)
                    self.status.setText(
                        "Saved absolute origin. PoE window not detected, "
                        "so window-relative offset was not stored.")
                else:
                    ax, ay = rect.anchor(anchor)
                    dx = c["tl"][0] - ax
                    dy = c["tl"][1] - ay
                    self.cfg.set(
                        "macros.inventory_dump.origin_relative_to_window",
                        {"anchor": anchor, "offset": [dx, dy]})
            except Exception:
                pass
        else:
            self.cfg.set(
                "macros.inventory_dump.origin_relative_to_window", None)

        self._unbind_hotkey()
        self.accept()
