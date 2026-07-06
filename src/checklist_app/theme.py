"""Dark theme palette and Qt stylesheet."""

# Palette
BG = "#0d1117"
PANEL = "#131a22"
PANEL_ALT = "#0f151c"
ROW_HOVER = "#1a2230"
BORDER = "#1f2937"
TEXT = "#e6e9ee"
TEXT_DIM = "#8b94a3"
TEXT_FAINT = "#5c6572"
ACCENT = "#4d9fff"
ACCENT_DIM = "#2a5a94"
GREEN = "#3fca6b"
RED = "#ff5c5c"
RED_DIM = "#8a2f2f"
AMBER = "#ffb454"

QSS = f"""
* {{
    font-family: "Segoe UI", "Inter", "Cantarell", "Noto Sans", sans-serif;
    outline: none;
}}

QMainWindow, QWidget#Root {{
    background: {BG};
}}

/* ---------- header ---------- */
QWidget#Header {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
}}
QLabel#AppTitle {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#AppSubtitle {{
    color: {TEXT_FAINT};
    font-size: 10px;
    letter-spacing: 2px;
}}

QComboBox {{
    background: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 28px 6px 10px;
    font-size: 13px;
}}
QComboBox:hover {{ border-color: {ACCENT_DIM}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_DIM};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ROW_HOVER};
    selection-color: {TEXT};
    outline: none;
}}

QToolButton {{
    background: transparent;
    color: {TEXT_DIM};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 13px;
}}
QToolButton:hover {{
    color: {TEXT};
    border-color: {BORDER};
    background: {ROW_HOVER};
}}
QToolButton:checked {{
    color: {ACCENT};
    border-color: {ACCENT_DIM};
    background: {PANEL_ALT};
}}

/* ---------- sidebar ---------- */
QListWidget#Sidebar {{
    background: {PANEL_ALT};
    border: none;
    border-right: 1px solid {BORDER};
    padding: 6px 0;
    font-size: 12px;
}}
QListWidget#Sidebar::item {{
    color: {TEXT_DIM};
    padding: 6px 14px;
    border: none;
    border-left: 2px solid transparent;
}}
QListWidget#Sidebar::item:hover {{
    color: {TEXT};
    background: {ROW_HOVER};
}}
QListWidget#Sidebar::item:selected {{
    color: {TEXT};
    background: {ROW_HOVER};
    border-left: 2px solid {ACCENT};
}}
QListWidget#Sidebar::item:disabled {{
    color: {TEXT_FAINT};
    font-weight: 700;
    letter-spacing: 2px;
    padding-top: 14px;
    padding-bottom: 4px;
    background: transparent;
}}

/* ---------- checklist pane ---------- */
QLabel#SectionTitle {{
    color: {TEXT};
    font-size: 17px;
    font-weight: 700;
}}
QLabel#SectionTitle[emergency="true"] {{
    color: {RED};
}}
QLabel#SectionMeta {{
    color: {TEXT_FAINT};
    font-size: 11px;
}}
QLabel#CompleteBadge {{
    color: {GREEN};
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1px;
}}

QProgressBar {{
    background: {BORDER};
    border: none;
    border-radius: 2px;
    max-height: 4px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 2px;
}}
QProgressBar[emergency="true"]::chunk {{
    background: {RED};
}}

QScrollArea {{
    background: transparent;
    border: none;
}}
QWidget#ChecklistCanvas {{
    background: {BG};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

/* ---------- footer ---------- */
QWidget#Footer {{
    background: {PANEL};
    border-top: 1px solid {BORDER};
}}
QPushButton {{
    background: {PANEL_ALT};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
}}
QPushButton:hover {{
    color: {TEXT};
    border-color: {ACCENT_DIM};
}}
QPushButton#NextButton {{
    background: {ACCENT_DIM};
    color: {TEXT};
    border-color: {ACCENT_DIM};
    font-weight: 600;
}}
QPushButton#NextButton:hover {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #0b1016;
}}
QLabel#Hint {{
    color: {TEXT_FAINT};
    font-size: 11px;
}}

/* ---------- dialogs (debrief etc.) ---------- */
QDialog {{ background: {BG}; }}
QDialog QLabel {{ color: {TEXT}; }}
QTextBrowser {{
    background: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 12px;
    font-size: 13px;
}}
"""
