"""Cursor-driven grid calibration.

Workflow:
    1. Hover the centre of the *top-left* inventory slot in PoE.
    2. Click "Capture top-left".
    3. Hover the slot one column to the right, click "Capture right".
    4. Hover the slot one row below the first, click "Capture down".
    5. Click OK – writes origin + cell_size back to config. If the PoE
       window is detected, also writes `origin_relative_to_window` so
       moving / resizing the window survives.

No coordinates need to be typed.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout,
)

from ..core.config import ConfigStore

try:
    import pydirectinput as _di  # type: ignore
except Exception:  # pragma: no cover
    _di = None


def _cursor() -> tuple[int, int] | None:
    if _di is None:
        return None
    try:
        return tuple(_di.position())  # type: ignore[return-value]
    except Exception:
        return None


class CalibrateDialog(QDialog):
    def __init__(self, cfg: ConfigStore, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Calibrate inventory grid")
        self.setModal(True)
        self._top_left: tuple[int, int] | None = None
        self._right: tuple[int, int] | None = None
        self._down: tuple[int, int] | None = None
        self._build()

        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._tick_cursor)
        self._cursor_timer.start(50)

    def _build(self) -> None:
        v = QVBoxLayout(self)

        v.addWidget(QLabel(
            "Move the mouse over each slot and click the matching button.\n"
            "Nothing happens in PoE — this only reads the cursor."))

        self.cursor_label = QLabel("Cursor: —")
        self.cursor_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.cursor_label)

        form = QFormLayout()
        self.btn_tl = QPushButton("Capture top-left slot")
        self.btn_tl.clicked.connect(lambda: self._capture("tl"))
        self.lbl_tl = QLabel("—")
        form.addRow(self.btn_tl, self.lbl_tl)

        self.btn_r = QPushButton("Capture slot one to the right")
        self.btn_r.clicked.connect(lambda: self._capture("r"))
        self.lbl_r = QLabel("—")
        form.addRow(self.btn_r, self.lbl_r)

        self.btn_d = QPushButton("Capture slot one below top-left")
        self.btn_d.clicked.connect(lambda: self._capture("d"))
        self.lbl_d = QLabel("—")
        form.addRow(self.btn_d, self.lbl_d)
        v.addLayout(form)

        # Window anchor selector – optional
        anchor_row = QHBoxLayout()
        anchor_row.addWidget(QLabel("Save as window-relative from:"))
        self.anchor_combo = QComboBox()
        self.anchor_combo.addItems(["(disabled)", "top_left", "top_right",
                                    "bottom_left", "bottom_right"])
        self.anchor_combo.setCurrentText("top_right")   # PoE inventory anchors R
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

    # ---- live cursor ----
    def _tick_cursor(self) -> None:
        pos = _cursor()
        self.cursor_label.setText(
            f"Cursor: {pos[0]}, {pos[1]}" if pos else "Cursor: unavailable")

    # ---- captures ----
    def _capture(self, which: str) -> None:
        pos = _cursor()
        if not pos:
            self.status.setText("Could not read cursor position.")
            return
        if which == "tl":
            self._top_left = pos
            self.lbl_tl.setText(f"{pos[0]}, {pos[1]}")
        elif which == "r":
            self._right = pos
            self.lbl_r.setText(f"{pos[0]}, {pos[1]}")
        elif which == "d":
            self._down = pos
            self.lbl_d.setText(f"{pos[0]}, {pos[1]}")
        self._refresh()

    def _refresh(self) -> None:
        if not (self._top_left and self._right and self._down):
            self.status.setText("")
            self.ok_btn.setEnabled(False)
            return
        cw = self._right[0] - self._top_left[0]
        ch = self._down[1] - self._top_left[1]
        self.status.setText(
            f"origin=({self._top_left[0]},{self._top_left[1]})  "
            f"cell_size=({cw},{ch})")
        self.ok_btn.setEnabled(cw > 0 and ch > 0)

    # ---- apply ----
    def _apply(self) -> None:
        if not (self._top_left and self._right and self._down):
            return
        cw = self._right[0] - self._top_left[0]
        ch = self._down[1] - self._top_left[1]
        self.cfg.set("macros.inventory_dump.grid.origin",
                     [self._top_left[0], self._top_left[1]])
        self.cfg.set("macros.inventory_dump.grid.cell_size", [cw, ch])

        # Optionally compute window-relative offset.
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
                    dx = self._top_left[0] - ax
                    dy = self._top_left[1] - ay
                    self.cfg.set(
                        "macros.inventory_dump.origin_relative_to_window",
                        {"anchor": anchor, "offset": [dx, dy]})
            except Exception:
                pass
        else:
            self.cfg.set(
                "macros.inventory_dump.origin_relative_to_window", None)

        self.accept()
