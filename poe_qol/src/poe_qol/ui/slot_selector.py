"""Visual grid slot selector – reusable across containers.

Renders a rows×cols grid of toggle buttons rooted at any config path
(`macros.inventory_dump`, `macros.map_stash_dump`, …). Selection is
synced to `<cfg_path>.selected_slots`.

Provides:
    * Bulk select all/none/invert
    * Save/load named slot profiles in `<cfg_path>.slot_profile_dir`
    * Live overlay window highlighting the selected slots at real
      screen coordinates (resolved via vision/window.py)
    * Calibrate dialog (cursor + global hotkey)

Highlight-only by design: nothing here sends input to the game. The
player Ctrl-clicks the highlighted slots themselves. (The old "Dump"
sweep clicked up to 72 slots per key press, which breaks GGG's
one-action-per-key-press rule; see docs/COMPLIANCE_REVIEW.md.)

The config namespaces (`macros.inventory_dump`, `macros.map_stash_dump`)
keep their historical names so existing calibration and selections in
config/user.yaml keep working.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import yaml
from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QBoxLayout, QComboBox, QGridLayout, QHBoxLayout, QInputDialog, QLayout,
    QMessageBox, QPushButton, QSizePolicy, QToolButton, QWidget,
)

from ..core.config import ConfigStore


CELL_SIZE_PX = 40   # starting cell size; cells then scale to the card
CELL_MIN_PX = 18
CELL_MAX_PX = 64
CELL_GAP_PX = 6
SIDE_W_PX = 280     # width of the stats/overlay/profile column
NARROW_PX = 760     # below this page width the side column moves under the grid


class SlotSelector(QWidget):
    def __init__(self, cfg: ConfigStore,
                 cfg_path: str = "macros.inventory_dump",
                 title: str = "Inventory",
                 on_change: Callable[[], None] | None = None,
                 scheduler=None):
        super().__init__()
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.title = title
        self.on_change = on_change or (lambda: None)
        self._scheduler = scheduler
        self._buttons: dict[tuple[int, int], QToolButton] = {}
        self._overlay: Optional["_OverlayWindow"] = None
        self._build()

    # ---- key helper ----
    def _k(self, *parts: str) -> str:
        return ".".join((self.cfg_path, *parts))

    # ---- construction ----
    def _build(self) -> None:
        from . import styles as S
        from .components import StatCard, card
        from .icons import icon

        # Side by side when there is room; the side cards drop below the
        # grid in a narrow window (see resizeEvent).
        root = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)
        self._root = root

        rows = self.cfg.get(self._k("grid", "rows"), 5)
        cols = self.cfg.get(self._k("grid", "cols"), 12)

        # ---- left: the grid ----
        bulk = QHBoxLayout()
        bulk.setSpacing(8)
        for label, fn in (("All", self._select_all),
                          ("None", self._clear),
                          ("Invert", self._invert)):
            btn = QPushButton(label)
            btn.setProperty("role", "pill")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(fn)
            bulk.addWidget(btn)
        grid_card, gv = card(
            f"{rows} × {cols} Slots",
            "Click slots to pick them. Green = highlighted in game.",
            right=bulk, icon="inventory")

        # The grid widget takes whatever space the card has and the cells
        # are resized to fit it (see _fit_cells), so the grid never clips
        # and never stops the window from shrinking.
        grid_w = QWidget()
        grid_w.setSizePolicy(QSizePolicy.Policy.Ignored,
                             QSizePolicy.Policy.Ignored)
        grid = QGridLayout(grid_w)
        grid.setSpacing(CELL_GAP_PX)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        grid_w.setMinimumHeight(rows * 26)
        self._grid_w = grid_w
        self._grid_dims = (rows, cols)
        grid_w.installEventFilter(self)
        selected = {tuple(s) for s in
                    (self.cfg.get(self._k("selected_slots")) or [])}
        for r in range(rows):
            for c in range(cols):
                b = QToolButton()
                b.setObjectName("SlotCell")
                b.setCheckable(True)
                b.setChecked((r, c) in selected)
                b.setFixedSize(CELL_SIZE_PX, CELL_SIZE_PX)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setToolTip(f"Row {r + 1}, Column {c + 1}")
                b.toggled.connect(lambda _v, rr=r, cc=c: self._on_toggle(rr, cc))
                self._style_button(b)
                grid.addWidget(b, r, c)
                self._buttons[(r, c)] = b
        gv.addWidget(grid_w, 1)
        root.addWidget(grid_card, 1)

        # ---- right: stats + actions ----
        side = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(18)
        self._side = side
        self._summary_card = StatCard(
            "Selected", help="How many slots will be highlighted.",
            icon="select")
        self._summary = self._summary_card.value
        side.addWidget(self._summary_card)

        ov_card, ov = card("Overlay", (
            "Draws green boxes over the chosen slots in game. "
            "<b>Highlight only</b>: you Ctrl-click them yourself; nothing "
            "is clicked for you. Needs windowed or windowed-fullscreen."),
            icon="eye")
        self.overlay_btn = QPushButton("Show Overlay")
        self.overlay_btn.setCheckable(True)
        self.overlay_btn.setProperty("size", "big")
        self.overlay_btn.setProperty("role", "primary")
        self.overlay_btn.setIcon(icon("eye", "#1A1200"))
        self.overlay_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overlay_btn.toggled.connect(self._on_overlay_toggle)
        ov.addWidget(self.overlay_btn)

        self.calibrate_btn = QPushButton("Calibrate…")
        self.calibrate_btn.setIcon(icon("target", S.FG_1))
        self.calibrate_btn.setToolTip(
            "Point at three slots with the cursor so the overlay lines up "
            "with your game window.")
        self.calibrate_btn.clicked.connect(self._on_calibrate)
        cal_row = QHBoxLayout()
        cal_row.addWidget(self.calibrate_btn, 1)
        from .components import HelpBadge
        cal_row.addWidget(HelpBadge(
            "Do this once (and after changing resolution): hover the "
            "top-left slot, the one to its right and the one below, "
            "pressing the hotkey on each."))
        ov.addLayout(cal_row)
        side.addWidget(ov_card)

        pr_card, pr = card("Profiles", (
            "Save the current selection under a name and switch between "
            "saved selections."), icon="folder")
        self.prof_combo = QComboBox()
        self.prof_combo.setEditable(False)
        self._refresh_profiles()
        self.prof_combo.currentTextChanged.connect(self._on_profile_changed)
        pr.addWidget(self.prof_combo)
        prow = QHBoxLayout()
        for label, fn in (("Save", self._save_profile_prompt),
                          ("Delete", self._delete_profile)):
            btn = QPushButton(label)
            btn.clicked.connect(fn)
            prow.addWidget(btn, 1)
        pr.addLayout(prow)
        side.addWidget(pr_card)
        side.addStretch(1)

        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(SIDE_W_PX)
        self._side_w = side_w
        self._narrow = False
        root.addWidget(side_w)
        self._refresh_summary()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        narrow = self.width() < NARROW_PX
        if narrow == self._narrow:
            return
        self._narrow = narrow
        last = self._side.count() - 1            # the trailing stretch
        if narrow:
            self._root.setDirection(QBoxLayout.Direction.TopToBottom)
            self._side.setDirection(QBoxLayout.Direction.LeftToRight)
            for i in range(last):
                self._side.setStretch(i, 1)
            self._side.setStretch(last, 0)
            self._side_w.setMinimumWidth(0)
            self._side_w.setMaximumWidth(16777215)
        else:
            self._root.setDirection(QBoxLayout.Direction.LeftToRight)
            self._side.setDirection(QBoxLayout.Direction.TopToBottom)
            for i in range(last):
                self._side.setStretch(i, 0)
            self._side.setStretch(last, 1)
            self._side_w.setFixedWidth(SIDE_W_PX)

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is getattr(self, "_grid_w", None) and ev.type() == QEvent.Type.Resize:
            self._fit_cells()
        return super().eventFilter(obj, ev)

    def _fit_cells(self) -> None:
        rows, cols = self._grid_dims
        w, h = self._grid_w.width(), self._grid_w.height()
        size = min((w - CELL_GAP_PX * (cols - 1)) // cols,
                   (h - CELL_GAP_PX * (rows - 1)) // rows)
        size = max(CELL_MIN_PX, min(CELL_MAX_PX, size))
        for b in self._buttons.values():
            if b.width() != size:
                b.setFixedSize(size, size)

    def _style_button(self, b: QToolButton) -> None:
        # Styling lives in ui/styles.py (QToolButton rules). Kept as a
        # hook so individual cells can opt into variants later without
        # touching callers.
        pass

    # ---- selection ----
    def _current_selected(self) -> list[tuple[int, int]]:
        return [rc for rc, b in self._buttons.items() if b.isChecked()]

    def _commit(self) -> None:
        sel = sorted(self._current_selected())
        self.cfg.set(self._k("selected_slots"), [list(p) for p in sel])
        self.cfg.set(self._k("active_slot_profile"), None)
        self._persist_selection()
        self._refresh_summary()
        if self._overlay:
            self._overlay.refresh(sel)
        self.on_change()

    def _persist_selection(self) -> None:
        """Write the current slot selection + active profile to
        config/user.yaml so they survive restart, matching how
        calibration is persisted."""
        try:
            self.cfg.save_user_overrides([
                self._k("selected_slots"),
                self._k("active_slot_profile"),
            ])
        except Exception:
            pass

    def _on_toggle(self, r: int, c: int) -> None:
        self._commit()

    def _select_all(self) -> None:
        for b in self._buttons.values():
            b.blockSignals(True); b.setChecked(True); b.blockSignals(False)
        self._commit()

    def _clear(self) -> None:
        for b in self._buttons.values():
            b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        self._commit()

    def _invert(self) -> None:
        for b in self._buttons.values():
            b.blockSignals(True); b.setChecked(not b.isChecked()); b.blockSignals(False)
        self._commit()

    def _refresh_summary(self) -> None:
        n = len(self._current_selected())
        total = len(self._buttons)
        self._summary_card.set(f"{n} / {total}",
                               "All Slots" if n == total else
                               ("None Yet" if n == 0 else ""))

    # ---- profiles ----
    def _profile_dir(self) -> Path:
        return Path(self.cfg.get(self._k("slot_profile_dir"),
                                 "config/slot_profiles"))

    def _refresh_profiles(self) -> None:
        self.prof_combo.blockSignals(True)
        self.prof_combo.clear()
        self.prof_combo.addItem("(None)", "")
        d = self._profile_dir()
        if d.exists():
            for p in sorted(d.glob("*.yaml")):
                self.prof_combo.addItem(p.stem)
        active = self.cfg.get(self._k("active_slot_profile"))
        if active:
            i = self.prof_combo.findText(active)
            if i >= 0:
                self.prof_combo.setCurrentIndex(i)
        self.prof_combo.blockSignals(False)

    def _on_profile_changed(self, name: str) -> None:
        if not name or name == "(None)":
            self.cfg.set(self._k("active_slot_profile"), None)
            self._persist_selection()
            return
        path = self._profile_dir() / f"{name}.yaml"
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text()) or {}
        slots = {tuple(s) for s in data.get("slots") or []}
        for rc, b in self._buttons.items():
            b.blockSignals(True); b.setChecked(rc in slots); b.blockSignals(False)
        self.cfg.set(self._k("active_slot_profile"), name)
        self.cfg.set(self._k("selected_slots"),
                     [list(s) for s in sorted(slots)])
        self._persist_selection()
        self._refresh_summary()
        if self._overlay:
            self._overlay.refresh(sorted(slots))

    def _save_profile_prompt(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Slot Profile", "Name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        d = self._profile_dir()
        d.mkdir(parents=True, exist_ok=True)
        slots = sorted(self._current_selected())
        (d / f"{name}.yaml").write_text(yaml.safe_dump(
            {"name": name, "slots": [list(s) for s in slots]},
            sort_keys=False))
        self._refresh_profiles()
        i = self.prof_combo.findText(name)
        if i >= 0:
            self.prof_combo.setCurrentIndex(i)

    def _delete_profile(self) -> None:
        name = self.prof_combo.currentText()
        if name in ("", "(None)"):
            return
        ok = QMessageBox.question(self, "Delete Profile",
                                  f"Delete Slot Profile '{name}'?")
        if ok != QMessageBox.StandardButton.Yes:
            return
        p = self._profile_dir() / f"{name}.yaml"
        if p.exists():
            p.unlink()
        self._refresh_profiles()

    # ---- calibration ----
    def _on_calibrate(self) -> None:
        from .calibrate_dialog import CalibrateDialog
        scheduler = getattr(self, "_scheduler", None)
        if scheduler:
            scheduler.hotkeys.unbind_all()
        try:
            dlg = CalibrateDialog(self.cfg, self, cfg_path=self.cfg_path,
                                  title=self.title)
            if dlg.exec():
                if self._overlay:
                    self._overlay._reposition()
                    self._overlay.refresh(self._current_selected())
        finally:
            if scheduler:
                scheduler._bind_hotkeys()

    # ---- overlay ----
    def _on_overlay_toggle(self, on: bool) -> None:
        if on:
            self._overlay = _OverlayWindow(self.cfg, self.cfg_path)
            self._overlay.refresh(self._current_selected())
            self._overlay.show()
            self.overlay_btn.setText("Hide Overlay")
            self.overlay_btn.setProperty("role", "")
            self.overlay_btn.setIcon(_eye(False))
        else:
            if self._overlay:
                self._overlay.close()
                self._overlay = None
            self.overlay_btn.setText("Show Overlay")
            self.overlay_btn.setProperty("role", "primary")
            self.overlay_btn.setIcon(_eye(True))
        from .styles import repolish
        repolish(self.overlay_btn)


def _eye(primary: bool):
    from . import styles as S
    from .icons import icon
    return icon("eye", "#1A1200" if primary else S.FG_0)


class _OverlayWindow(QWidget):
    """Frameless always-on-top window that draws highlighted squares
    at the resolved screen coordinates of the configured grid."""

    def __init__(self, cfg: ConfigStore, cfg_path: str):
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.cfg = cfg
        self.cfg_path = cfg_path
        self._selected: list[tuple[int, int]] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._reposition)
        self._timer.start(250)
        self._reposition()

    def _k(self, *parts: str) -> str:
        return ".".join((self.cfg_path, *parts))

    def _geometry(self):
        # Shared with the Alt+drag area selection: window-relative origin,
        # resolution scaling and grid.bounds are all handled there.
        from ..area_select.grid import load_geometry
        return load_geometry(self.cfg, self.cfg_path)

    def _reposition(self) -> None:
        self._geom = self._geometry()
        b = self._geom.bounds().expanded(4)
        screen = self.screen()
        self._dpr = float(screen.devicePixelRatio()) if screen else 1.0
        d = self._dpr
        x, y = int(b.left / d), int(b.top / d)
        self._frame = b.translated(x * d - b.left, y * d - b.top)  # snapped
        self.setGeometry(x, y, int(round(b.width / d)) + 1,
                         int(round(b.height / d)) + 1)
        self.update()

    def refresh(self, selected) -> None:
        self._selected = list(selected)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor(80, 220, 140, 90)
        border = QColor(80, 220, 140, 220)
        p.setBrush(fill); p.setPen(border)
        # Geometry is in physical px; the widget paints in logical px.
        d, f = self._dpr, self._frame
        size = min(self._geom.cell) / d
        for r, c in self._selected:
            cx, cy = self._geom.slot_center((r, c))
            lx = (cx - f.left) / d - size / 2
            ly = (cy - f.top) / d - size / 2
            p.drawRoundedRect(QRectF(lx, ly, size, size), 4, 4)
