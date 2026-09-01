"""Application theming: colour palettes and the generated Qt stylesheet.

A single accent-driven palette is defined per theme; the stylesheet is built
from it so colours only ever need changing in one place.
"""

from dataclasses import dataclass

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QFont

ORG_NAME = "UAVDesign"
APP_NAME = "UAVDesignOrganizer"


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str          # window background
    surface: str     # panels, group boxes
    surface_alt: str # inputs, list rows
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    success: str
    warning: str
    danger: str


DARK = Palette(
    name="dark",
    bg="#1b1f26",
    surface="#232830",
    surface_alt="#2b313b",
    border="#39414d",
    text="#e6e9ee",
    muted="#98a2b0",
    accent="#4a90e2",
    accent_hover="#5ea1ef",
    accent_text="#ffffff",
    success="#41b957",
    warning="#d9a323",
    danger="#e5534b",
)

LIGHT = Palette(
    name="light",
    bg="#f4f6f9",
    surface="#ffffff",
    surface_alt="#eef1f5",
    border="#d3d9e0",
    text="#1f2328",
    muted="#5f6b7a",
    accent="#2f6fd0",
    accent_hover="#3d7fe0",
    accent_text="#ffffff",
    success="#1f8b3a",
    warning="#9a6700",
    danger="#c0392b",
)

THEMES = {"dark": DARK, "light": LIGHT}


def build_stylesheet(p: Palette) -> str:
    return f"""
QWidget {{
    background-color: {p.bg};
    color: {p.text};
    font-size: 13px;
}}

QMainWindow, QDialog {{ background-color: {p.bg}; }}

/* ---------- Menus & status ---------- */
QMenuBar {{
    background-color: {p.surface};
    border-bottom: 1px solid {p.border};
    padding: 2px;
}}
QMenuBar::item {{ padding: 6px 12px; border-radius: 4px; }}
QMenuBar::item:selected {{ background-color: {p.surface_alt}; }}
QMenu {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    padding: 4px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: {p.accent}; color: {p.accent_text}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 8px; }}

QStatusBar {{
    background-color: {p.surface};
    border-top: 1px solid {p.border};
    color: {p.muted};
}}
QStatusBar::item {{ border: none; }}

/* ---------- Buttons ---------- */
QPushButton {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 7px 14px;
    color: {p.text};
}}
QPushButton:hover {{ border-color: {p.accent}; }}
QPushButton:pressed {{ background-color: {p.border}; }}
QPushButton:disabled {{ color: {p.muted}; border-color: {p.border}; }}
QPushButton[accent="true"] {{
    background-color: {p.accent};
    border: 1px solid {p.accent};
    color: {p.accent_text};
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{ background-color: {p.accent_hover}; }}
QPushButton[danger="true"]:hover {{ border-color: {p.danger}; color: {p.danger}; }}

/* ---------- Inputs ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border-color: {p.accent};
}}
QLineEdit:read-only {{ color: {p.muted}; background-color: {p.surface}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}

/* ---------- Containers ---------- */
QGroupBox {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {p.muted};
}}

QScrollArea, QScrollArea > QWidget > QWidget {{ background-color: transparent; border: none; }}

QSplitter::handle {{ background-color: {p.border}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}

QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: {p.border}; }}

/* ---------- Lists ---------- */
QListWidget, QTreeWidget {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 6px 8px;
    border-radius: 4px;
}}
QListWidget::item:hover, QTreeWidget::item:hover {{ background-color: {p.surface_alt}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {p.accent};
    color: {p.accent_text};
}}
QListWidget#sidebar {{
    background-color: {p.surface};
    font-size: 14px;
    padding: 6px;
}}
QListWidget#sidebar::item {{ padding: 11px 10px; margin: 2px 0; }}
QHeaderView::section {{
    background-color: {p.surface_alt};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 6px;
    color: {p.muted};
}}

/* ---------- Tabs ---------- */
QTabWidget::pane {{
    border: 1px solid {p.border};
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 7px 14px;
    margin-right: 2px;
    color: {p.muted};
}}
QTabBar::tab:selected {{
    background-color: {p.surface_alt};
    color: {p.text};
    border-bottom: 2px solid {p.accent};
}}
QTabBar::tab:hover {{ color: {p.text}; }}

/* ---------- Dock ---------- */
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 7px;
    text-align: left;
}}

/* ---------- Check boxes ---------- */
QCheckBox {{ spacing: 8px; padding: 2px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {p.border};
    border-radius: 4px;
    background-color: {p.surface_alt};
}}
QCheckBox::indicator:checked {{
    background-color: {p.accent};
    border-color: {p.accent};
}}
QCheckBox:disabled {{ color: {p.muted}; }}

/* ---------- Scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent; width: 11px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p.border}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {p.border}; border-radius: 5px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---------- Semantic labels ---------- */
QLabel[role="title"] {{ font-size: 22px; font-weight: 700; }}
QLabel[role="heading"] {{ font-size: 17px; font-weight: 700; }}
QLabel[role="subtle"] {{ color: {p.muted}; }}
QLabel[role="required"] {{ color: {p.text}; font-weight: 600; }}
QLabel[role="dropzone"] {{
    color: {p.muted};
    border: 1px dashed {p.border};
    border-radius: 8px;
    padding: 18px;
}}

QToolTip {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    padding: 4px 6px;
}}
"""


def load_theme_name() -> str:
    """Theme chosen on a previous run, defaulting to dark."""
    settings = QSettings(ORG_NAME, APP_NAME)
    name = settings.value("theme", "dark")
    return name if name in THEMES else "dark"


def save_theme_name(name: str) -> None:
    QSettings(ORG_NAME, APP_NAME).setValue("theme", name)


def apply_theme(app, name: str) -> Palette:
    """Apply a named theme to the QApplication and remember the choice."""
    palette = THEMES.get(name, DARK)
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet(palette))
    save_theme_name(palette.name)
    return palette


def monospace_font(point_size: int = 10) -> QFont:
    font = QFont("Consolas")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(point_size)
    return font
