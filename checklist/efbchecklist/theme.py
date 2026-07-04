"""Dark cockpit theme.

Color language follows glass-cockpit annunciator conventions:
white/off-white for pending items, green for completed, cyan for live data
and accents, amber for cautions/notes, red reserved for emergency procedures.
"""

BG = "#0b0e13"          # window background, near-black blue
PANEL = "#12161e"       # sidebar / cards
PANEL_ALT = "#171c26"   # hover / active rows
BORDER = "#232a38"
TEXT = "#e8ecf3"        # pending items
TEXT_DIM = "#77808f"    # secondary text, dot leaders
GREEN = "#3ddc84"       # completed
CYAN = "#4fc3f7"        # accent, data, focus
AMBER = "#ffc857"       # notes, cautions
RED = "#ff5252"         # emergency
RED_DIM = "#4a1f24"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif;
    outline: none;
}}
QMainWindow, QWidget#root {{
    background: {BG};
}}
QWidget {{
    color: {TEXT};
    background: transparent;
}}

/* ---------- header ---------- */
QWidget#header {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
}}
QComboBox {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 600;
    min-width: 220px;
}}
QComboBox:hover {{ border-color: {CYAN}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    selection-background-color: {BORDER};
    color: {TEXT};
}}
QLabel#subtitle {{
    color: {TEXT_DIM};
    font-size: 11px;
}}

QToolButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 600;
    color: {TEXT_DIM};
}}
QToolButton:hover {{ color: {TEXT}; border-color: {CYAN}; }}
QToolButton:checked {{ color: {CYAN}; border-color: {CYAN}; }}
QToolButton#emergencyButton {{ color: {RED}; border-color: {RED_DIM}; }}
QToolButton#emergencyButton:hover {{ border-color: {RED}; }}

QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
    background: {CYAN};
}}

/* ---------- sidebar ---------- */
QListWidget#sidebar {{
    background: {PANEL};
    border: none;
    border-right: 1px solid {BORDER};
    font-size: 13px;
    padding: 6px 0;
}}
QListWidget#sidebar::item {{
    padding: 8px 14px;
    border-left: 3px solid transparent;
}}
QListWidget#sidebar::item:hover {{ background: {PANEL_ALT}; }}
QListWidget#sidebar::item:selected {{
    background: {PANEL_ALT};
    border-left: 3px solid {CYAN};
    color: {TEXT};
}}

/* ---------- checklist pane ---------- */
QScrollArea {{ border: none; }}
QScrollBar:vertical {{
    background: {BG};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QLabel#checklistTitle {{
    font-size: 17px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QLabel#checklistTitleEmergency {{
    font-size: 17px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: {RED};
}}
QLabel#progressLabel {{
    color: {TEXT_DIM};
    font-size: 12px;
    font-weight: 600;
}}
QProgressBar {{
    background: {BORDER};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {GREEN};
    border-radius: 3px;
}}
QProgressBar#emergencyProgress::chunk {{ background: {RED}; }}

QPushButton#resetButton {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 14px;
    color: {TEXT_DIM};
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#resetButton:hover {{ color: {AMBER}; border-color: {AMBER}; }}

QLabel#footerHint {{
    color: {TEXT_DIM};
    font-size: 11px;
}}
"""
