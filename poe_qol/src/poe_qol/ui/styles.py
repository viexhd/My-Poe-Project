"""App-wide QSS theme + design tokens.

Single source of truth for colors, spacing, and component styles.
Apply once at startup via ``apply_theme(qapp)``. Individual widgets can
opt into variants by setting ``widget.setProperty("role", "primary")``
etc., then calling ``style().unpolish / polish`` to re-apply QSS.

Layout language (see ui/components.py): a left sidebar for navigation
and a content area of large rounded cards, big numbers with small
labels, and a round "?" badge next to anything that needs explaining
instead of paragraphs of text.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication


# ---- Design tokens -------------------------------------------------------
# "Scarlet rot & gilt": warm obsidian surfaces, bone text, gilt gold for
# primary actions/focus, crimson rot for brand highlights. Same palette as
# the icon and banner (tools/build_brand.py, docs/BRAND.md).

# Surface
BG_0 = "#0D0A0B"
BG_1 = "#141012"
BG_2 = "#1C1518"
BG_3 = "#261C20"

# Border
LINE = "#33262A"
LINE_STRONG = "#4A363C"

# Text
FG_0 = "#EFE6DA"      # bone
FG_1 = "#BEB0A4"      # ash
FG_2 = "#85776E"

# Accents
ACCENT = "#D9B25A"    # gilt: primary buttons, focus, selection
ACCENT_HI = "#F2DE9F"
ROT = "#B3122E"       # scarlet rot: brand highlights
ROT_HI = "#E0482F"
INFO = "#6FA8DC"
SUCCESS = "#4FB286"
WARN = "#E3A64B"
DANGER = "#E5484D"

# Category tints (used by Map Search section headers)
CAT_BREAKING = "#C0303F"
CAT_DANGER = "#9A5BB4"
CAT_ANNOYING = "#D08A4A"
CAT_OTHER = "#5B86B4"

# Shape
RADIUS_CARD = 18
RADIUS_CONTROL = 10
FONT_STACK = ('"Segoe UI Variable Text", "Segoe UI", "Inter", '
              '"Helvetica Neue", Arial, sans-serif')


def rgba(hex_color: str, alpha: float) -> str:
    """``#RRGGBB`` + alpha (0..1) → ``rgba(r,g,b,a)`` for QSS."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{max(0.0, min(1.0, alpha)):.3f})"


_QSS = f"""
QWidget {{
    background: transparent;
    color: {FG_0};
    font-family: {FONT_STACK};
    font-size: 14px;
}}
QMainWindow, QDialog, QMessageBox, QInputDialog {{
    background: {BG_0};
}}
QWidget#Content, QStackedWidget#pages, QWidget#PageBody {{
    background: {BG_0};
}}

/* ---- sidebar ---- */
QFrame#Sidebar {{
    background: {BG_1};
    border-right: 1px solid {LINE};
}}
QLabel#BrandName {{
    color: {ACCENT};
    font-size: 26px;
    letter-spacing: 2px;
}}
QPushButton#NavButton {{
    background: transparent;
    border: 0;
    border-radius: 12px;
    color: {FG_1};
    font-size: 14px;
    font-weight: 500;
    padding: 11px 14px;
    text-align: left;
}}
QPushButton#NavButton:hover {{
    background: {BG_2};
    color: {FG_0};
}}
QPushButton#NavButton:checked {{
    background: {rgba(ROT_HI, 0.16)};
    color: {FG_0};
    font-weight: 600;
}}
QLabel#NavSection {{
    color: {FG_2};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 12px 14px 4px 14px;
}}
QLabel#StatusChip {{
    background: {BG_2};
    border: 1px solid {LINE};
    border-radius: 12px;
    color: {FG_1};
    font-size: 12px;
    padding: 8px 12px;
}}
QLabel#StatusChip[state="live"] {{
    color: {SUCCESS};
    border-color: {rgba(SUCCESS, 0.45)};
    background: {rgba(SUCCESS, 0.10)};
}}
QLabel#StatusChip[state="stopped"] {{
    color: {DANGER};
    border-color: {rgba(DANGER, 0.55)};
    background: {rgba(DANGER, 0.12)};
}}
QLabel#StatusChip[state="busy"] {{
    color: {ACCENT};
    border-color: {rgba(ACCENT, 0.5)};
    background: {rgba(ACCENT, 0.10)};
}}

/* ---- page header ---- */
QLabel#PageTitle {{
    font-size: 26px;
    font-weight: 700;
    color: {FG_0};
}}

/* ---- cards ---- */
QFrame#Card {{
    background: {BG_1};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#Card[variant="danger"] {{
    border-color: {rgba(DANGER, 0.55)};
    background: {rgba(DANGER, 0.06)};
}}
QFrame#Card[variant="gilt"] {{
    border-color: {rgba(ACCENT, 0.45)};
}}
QFrame#Tile {{
    background: {BG_1};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#Tile:hover, QFrame#Tile:focus {{
    border-color: {ACCENT};
    background: {BG_2};
}}
QLabel#CardTitle {{
    font-size: 15px;
    font-weight: 600;
    color: {FG_0};
}}
QLabel#StatLabel {{
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    color: {FG_2};
}}
QLabel#StatValue {{
    font-size: 32px;
    font-weight: 700;
    color: {FG_0};
}}
QLabel#HeroValue {{
    font-size: 52px;
    font-weight: 700;
    color: {ACCENT};
}}
QLabel#StatSub {{
    font-size: 12px;
    color: {FG_1};
}}
QLabel#FieldLabel {{
    font-size: 12px;
    font-weight: 600;
    color: {FG_1};
}}

/* ---- help badge ---- */
QToolButton#HelpBadge {{
    background: {BG_3};
    border: 1px solid {LINE_STRONG};
    border-radius: 9px;
    color: {FG_1};
    font-size: 11px;
    font-weight: 700;
    padding: 0;
}}
QToolButton#HelpBadge:hover {{
    background: {rgba(ACCENT, 0.18)};
    border-color: {ACCENT};
    color: {ACCENT_HI};
}}

/* ---- inputs ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BG_2};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CONTROL}px;
    padding: 8px 10px;
    min-height: 20px;
    color: {FG_0};
    selection-background-color: {ACCENT};
    selection-color: #1A1200;
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: {LINE_STRONG};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {FG_2};
    background: {BG_1};
}}
QComboBox::drop-down {{ border: 0; width: 28px; }}
QComboBox::down-arrow {{ image: url(@ARROWS@/down.svg); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url(@ARROWS@/down_off.svg); }}
QSpinBox, QDoubleSpinBox {{ padding-right: 26px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    width: 24px;
    border: 0;
    background: transparent;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right; margin-top: 4px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right; margin-bottom: 4px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {BG_3}; border-radius: 6px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url(@ARROWS@/up.svg); width: 10px; height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url(@ARROWS@/down.svg); width: 10px; height: 10px;
}}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled,
QSpinBox::up-arrow:off, QDoubleSpinBox::up-arrow:off {{
    image: url(@ARROWS@/up_off.svg);
}}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled,
QSpinBox::down-arrow:off, QDoubleSpinBox::down-arrow:off {{
    image: url(@ARROWS@/down_off.svg);
}}
QComboBox QAbstractItemView {{
    background: {BG_2};
    border: 1px solid {LINE_STRONG};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {BG_3};
    color: {FG_0};
    outline: 0;
}}
QTextEdit, QPlainTextEdit {{
    background: {BG_2};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CONTROL}px;
    padding: 8px;
    color: {FG_1};
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 12px;
}}

/* ---- buttons ---- */
QPushButton {{
    background: {BG_2};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CONTROL}px;
    padding: 9px 16px;
    color: {FG_0};
    font-weight: 500;
}}
QPushButton:hover {{
    background: {BG_3};
    border-color: {LINE_STRONG};
}}
QPushButton:pressed {{
    background: {BG_1};
}}
QPushButton:disabled {{
    color: {FG_2};
    border-color: {LINE};
    background: {BG_1};
}}
QPushButton:checked {{
    background: {rgba(SUCCESS, 0.18)};
    border: 1px solid {SUCCESS};
    color: {FG_0};
}}
QPushButton[size="big"] {{
    padding: 14px 20px;
    font-size: 15px;
    font-weight: 600;
    border-radius: 14px;
}}
QPushButton[role="pill"] {{
    border-radius: 15px;
    padding: 6px 14px;
    font-size: 13px;
}}

/* primary (gold) */
QPushButton[role="primary"] {{
    background: {ACCENT};
    color: #1A1200;
    border: 0;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HI}; }}
QPushButton[role="primary"]:pressed {{ background: {ACCENT}; }}
QPushButton[role="primary"]:disabled {{
    background: {rgba(ACCENT, 0.35)};
    color: {BG_1};
}}

/* info (blue) */
QPushButton[role="info"] {{
    background: {INFO};
    color: #0A1A26;
    border: 0;
    font-weight: 600;
}}
QPushButton[role="info"]:hover {{ background: #6FB8EB; }}

/* destructive (ghost by default, fills when armed via [armed="true"]) */
QPushButton[role="danger"] {{
    background: transparent;
    color: {DANGER};
    border: 1px solid {DANGER};
    font-weight: 600;
}}
QPushButton[role="danger"]:hover {{
    background: {rgba(DANGER, 0.12)};
}}
QPushButton[role="danger"][armed="true"] {{
    background: {DANGER};
    color: white;
}}

/* ---- slot-selector cells (QToolButton) ---- */
QToolButton#SlotCell {{
    background: {BG_2};
    border: 1px solid {LINE};
    border-radius: 8px;
}}
QToolButton#SlotCell:hover {{ border-color: {FG_1}; }}
QToolButton#SlotCell:checked {{
    background: {rgba(SUCCESS, 0.30)};
    border: 1px solid {SUCCESS};
}}

/* ---- segmented radio (Area Select transfer mode) ---- */
QRadioButton {{
    spacing: 10px;
    color: {FG_0};
    padding: 6px 2px;
}}
QRadioButton::indicator {{
    width: 14px; height: 14px;
    border-radius: 8px;
    border: 1px solid {LINE_STRONG};
    background: {BG_2};
}}
QRadioButton::indicator:checked {{
    border: 1px solid {ACCENT_HI};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {BG_0}, stop:0.36 {BG_0}, stop:0.42 {ACCENT}, stop:1 {ACCENT});
}}

/* ---- labels (via role) ---- */
QLabel[role="section"] {{
    font-size: 17px;
    font-weight: 600;
    color: {FG_0};
}}
QLabel[role="caption"] {{
    font-size: 12px;
    color: {FG_2};
}}
QLabel[role="muted"] {{
    color: {FG_1};
}}
QLabel[role="warn"] {{
    color: {DANGER};
    font-weight: 600;
}}
QLabel[role="note"] {{
    color: {WARN};
    font-weight: 600;
}}

/* ---- tables & lists ---- */
QTableWidget, QTableView, QListWidget {{
    background: {BG_1};
    alternate-background-color: {BG_2};
    border: 0;
    gridline-color: transparent;
    selection-background-color: {rgba(ACCENT, 0.18)};
    selection-color: {FG_0};
    outline: 0;
}}
QTableWidget::item, QTableView::item {{
    padding: 6px 8px;
    border: 0;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background: {rgba(ACCENT, 0.18)};
}}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {BG_1};
    color: {FG_2};
    border: 0;
    border-bottom: 1px solid {LINE};
    padding: 8px 8px;
    font-size: 12px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background: {BG_1}; border: 0; }}

/* ---- scroll areas ---- */
QScrollArea {{ border: 0; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {LINE_STRONG}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {FG_2}; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {LINE_STRONG}; border-radius: 4px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0; border: 0; background: transparent;
}}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- checkbox ---- */
QCheckBox {{ color: {FG_0}; spacing: 10px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid {LINE_STRONG};
    border-radius: 6px;
    background: {BG_2};
}}
QCheckBox::indicator:hover {{ border-color: {FG_1}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    image: none;
}}

/* ---- slider ---- */
QSlider::groove:horizontal {{
    height: 6px; border-radius: 3px; background: {BG_3};
}}
QSlider::sub-page:horizontal {{
    height: 6px; border-radius: 3px; background: {ACCENT};
}}
QSlider::handle:horizontal {{
    width: 18px; height: 18px; margin: -6px 0;
    border-radius: 9px; background: {FG_0};
}}

/* ---- menus & status bar ---- */
QMenuBar {{ background: {BG_0}; }}
QMenu {{
    background: {BG_2};
    border: 1px solid {LINE_STRONG};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{ padding: 8px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: {BG_3}; }}
QStatusBar {{
    background: {BG_0};
    color: {FG_1};
    border-top: 1px solid {LINE};
}}
QStatusBar::item {{ border: 0; }}

/* ---- tooltip ---- */
QToolTip {{
    background: {BG_3};
    color: {FG_0};
    border: 1px solid {LINE_STRONG};
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
}}
"""


def _arrow_dir() -> str:
    """Write the chevron images QSS needs (it can only load files) to a
    cache folder and return it as a forward-slash path."""
    import tempfile
    from pathlib import Path
    d = Path(tempfile.gettempdir()) / "twice-corrupted-ui"
    d.mkdir(parents=True, exist_ok=True)
    shapes = {"up": "M6 15l6-6 6 6", "down": "M6 9l6 6 6-6"}
    for name, path in shapes.items():
        for suffix, color in (("", FG_1), ("_off", LINE_STRONG)):
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
                   f'fill="none" stroke="{color}" stroke-width="2.6" '
                   f'stroke-linecap="round" stroke-linejoin="round">'
                   f'<path d="{path}"/></svg>')
            f = d / f"{name}{suffix}.svg"
            if not f.exists() or f.read_text() != svg:
                f.write_text(svg)
    return d.as_posix()


def stylesheet() -> str:
    try:
        arrows = _arrow_dir()
    except OSError:
        arrows = ""
    return _QSS.replace("@ARROWS@", arrows)


def apply_theme(app: QApplication) -> None:
    """Install the app-wide stylesheet. Safe to call multiple times."""
    app.setStyleSheet(stylesheet())


def repolish(widget) -> None:
    """Re-apply QSS after changing a dynamic property like ``role``."""
    s = widget.style()
    s.unpolish(widget)
    s.polish(widget)
