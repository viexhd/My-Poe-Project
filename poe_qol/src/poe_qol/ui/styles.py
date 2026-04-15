"""App-wide QSS theme + design tokens.

Single source of truth for colors, spacing, and component styles.
Apply once at startup via ``apply_theme(qapp)``. Individual widgets can
opt into variants by setting ``widget.setProperty("role", "primary")``
etc., then calling ``style().unpolish / polish`` to re-apply QSS.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication


# ---- Design tokens -------------------------------------------------------
# Surface
BG_0 = "#0E1116"
BG_1 = "#151A22"
BG_2 = "#1C222C"
BG_3 = "#242B37"

# Border
LINE = "#2A3240"
LINE_STRONG = "#3A4454"

# Text
FG_0 = "#E6EAF2"
FG_1 = "#A9B2C3"
FG_2 = "#6B7486"

# Accents
ACCENT = "#E8B057"
ACCENT_HI = "#F5C879"
INFO = "#4FA7E3"
SUCCESS = "#3FB27A"
WARN = "#E0A24A"
DANGER = "#D9544A"

# Category tints (used by Map Search section headers)
CAT_BREAKING = "#B04848"
CAT_DANGER = "#8E5BB4"
CAT_ANNOYING = "#C88448"
CAT_OTHER = "#5B7FB4"


_QSS = f"""
QWidget {{
    background: {BG_0};
    color: {FG_0};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background: {BG_0};
}}

/* ---- tabs: underline style ---- */
QTabWidget::pane {{
    border: 0;
    background: {BG_1};
    top: -1px;
}}
QTabBar {{
    background: {BG_0};
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    padding: 10px 18px;
    color: {FG_1};
    background: transparent;
    border: 0;
    margin-right: 4px;
}}
QTabBar::tab:hover {{
    color: {FG_0};
}}
QTabBar::tab:selected {{
    color: {FG_0};
    border-bottom: 2px solid {ACCENT};
}}

/* ---- inputs ---- */
QLineEdit, QSpinBox, QComboBox {{
    background: {BG_2};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 6px 8px;
    color: {FG_0};
    selection-background-color: {ACCENT};
    selection-color: #1A1200;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {FG_2};
    background: {BG_1};
}}
QComboBox::drop-down {{ border: 0; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {BG_2};
    border: 1px solid {LINE_STRONG};
    selection-background-color: {BG_3};
    color: {FG_0};
}}

/* ---- buttons ---- */
QPushButton {{
    background: {BG_2};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 8px 14px;
    color: {FG_0};
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
    background: rgba(63, 178, 122, 0.18);
    border: 1px solid {SUCCESS};
    color: {FG_0};
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

/* info (blue) — used for Dump */
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
    background: rgba(217, 84, 74, 0.12);
}}
QPushButton[role="danger"][armed="true"] {{
    background: {DANGER};
    color: white;
}}

/* ---- slot-selector cells (QToolButton) ---- */
QToolButton {{
    background: {BG_2};
    border: 1px solid {LINE};
    border-radius: 4px;
}}
QToolButton:hover {{ border-color: {FG_1}; }}
QToolButton:checked {{
    background: rgba(63, 178, 122, 0.22);
    border: 1px solid {SUCCESS};
}}

/* ---- labels (via role) ---- */
QLabel[role="section"] {{
    font-size: 16px;
    font-weight: 600;
    color: {FG_0};
}}
QLabel[role="caption"] {{
    font-size: 11px;
    color: {FG_2};
}}
QLabel[role="muted"] {{
    color: {FG_1};
}}

/* ---- status bar ---- */
QStatusBar {{
    background: {BG_0};
    color: {FG_1};
    border-top: 1px solid {LINE};
}}
QStatusBar::item {{ border: 0; }}

/* ---- scroll areas ---- */
QScrollArea {{ border: 0; background: {BG_1}; }}
QScrollBar:vertical {{
    background: {BG_1}; width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {LINE_STRONG}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {FG_2}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0; border: 0; background: transparent;
}}

/* ---- checkbox ---- */
QCheckBox {{ color: {FG_0}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {LINE_STRONG};
    border-radius: 3px;
    background: {BG_2};
}}
QCheckBox::indicator:hover {{ border-color: {FG_1}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    image: none;
}}

/* ---- tooltip ---- */
QToolTip {{
    background: {BG_3};
    color: {FG_0};
    border: 1px solid {LINE_STRONG};
    padding: 4px 6px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Install the app-wide stylesheet. Safe to call multiple times."""
    app.setStyleSheet(_QSS)


def repolish(widget) -> None:
    """Re-apply QSS after changing a dynamic property like ``role``."""
    s = widget.style()
    s.unpolish(widget)
    s.polish(widget)
