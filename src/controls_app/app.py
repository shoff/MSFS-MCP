"""MSFS 2024 controls setup advisor — dark, minimal, Claude-assisted.

Run with ``msfs-controls`` or ``python -m controls_app``.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from checklist_app import theme

from . import advisor
from .bindings import ControlPlan, load_default_plans
from .devices import DEVICE_BY_ID, DEVICES, detect_connected

PRIORITY_COLORS = {"essential": theme.RED, "recommended": theme.ACCENT, "optional": theme.TEXT_FAINT}

CONTROLS_QSS = f"""
QTableWidget {{
    background: {theme.PANEL_ALT};
    alternate-background-color: {theme.BG};
    color: {theme.TEXT};
    border: 1px solid {theme.BORDER};
    border-radius: 8px;
    gridline-color: {theme.BORDER};
    font-size: 12px;
}}
QTableWidget::item {{ padding: 6px 8px; border: none; }}
QTableWidget::item:selected {{ background: {theme.ROW_HOVER}; color: {theme.TEXT}; }}
QHeaderView::section {{
    background: {theme.PANEL};
    color: {theme.TEXT_DIM};
    border: none;
    border-bottom: 1px solid {theme.BORDER};
    padding: 7px 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QTableCornerButton::section {{ background: {theme.PANEL}; border: none; }}
QTextBrowser {{
    background: {theme.PANEL_ALT};
    color: {theme.TEXT};
    border: 1px solid {theme.BORDER};
    border-radius: 8px;
    padding: 10px;
    font-size: 12px;
}}
QLineEdit {{
    background: {theme.PANEL_ALT};
    color: {theme.TEXT};
    border: 1px solid {theme.BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
QLineEdit:focus {{ border-color: {theme.ACCENT_DIM}; }}
QSplitter::handle {{ background: {theme.BORDER}; height: 1px; }}
QPushButton#AskButton {{
    background: {theme.ACCENT_DIM};
    color: {theme.TEXT};
    border-color: {theme.ACCENT_DIM};
    font-weight: 600;
}}
QPushButton#AskButton:hover {{ background: {theme.ACCENT}; color: #0b1016; }}
QPushButton#AskButton:disabled {{ background: {theme.PANEL_ALT}; color: {theme.TEXT_FAINT}; }}
"""


class AdvisorWorker(QThread):
    finished_plan = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, kwargs: dict):
        super().__init__()
        self.kwargs = kwargs

    def run(self):
        try:
            self.finished_plan.emit(advisor.suggest_plan(**self.kwargs))
        except advisor.AdvisorUnavailable as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # network/parse errors — keep the app alive
            self.failed.emit(f"Advisor error: {exc}")


def _aircraft_context(aircraft_key: str) -> str:
    """Pull reference data (V-speeds, checklist phases) from the checklist app."""
    try:
        from checklist_app.models import load_aircraft

        key_map = {"c172s": "Cessna 172S Skyhawk", "pa28_181": "Piper PA-28-181 Archer II"}
        for aircraft in load_aircraft():
            if aircraft.name == key_map.get(aircraft_key):
                speeds = "; ".join(f"{k}: {v}" for k, v in aircraft.vspeeds)
                phases = ", ".join(s.name for s in aircraft.sections)
                return f"V-speeds: {speeds}\nChecklist phases the pilot trains with: {phases}"
    except Exception:
        pass
    return ""


class MainWindow(QMainWindow):
    def __init__(self, plans: dict[str, ControlPlan], detected: dict[str, bool]):
        super().__init__()
        self.plans = plans
        self.detected = detected
        self.plan: ControlPlan | None = None
        self.worker: AdvisorWorker | None = None

        self.setWindowTitle("Flight Controls Setup")
        self.resize(1180, 820)
        self.setMinimumSize(760, 560)

        root = QWidget(objectName="Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = QListWidget(objectName="Sidebar")
        self.sidebar.setFixedWidth(230)
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.currentItemChanged.connect(self._on_device_change)
        body.addWidget(self.sidebar)
        body.addWidget(self._build_main_pane(), 1)
        outer.addLayout(body, 1)
        outer.addWidget(self._build_footer())

        self._populate_sidebar()
        self._load_plan_for_aircraft()

    # -------------------------------------------------------------- header
    def _build_header(self) -> QWidget:
        header = QWidget(objectName="Header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(16, 10, 12, 10)
        lay.setSpacing(10)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(QLabel("MSFS 2024 CONTROLS", objectName="AppSubtitle"))
        titles.addWidget(QLabel("Setup Advisor", objectName="AppTitle"))
        lay.addLayout(titles)
        lay.addStretch(1)

        self.aircraft_combo = QComboBox()
        self.aircraft_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for key, plan in self.plans.items():
            self.aircraft_combo.addItem(plan.aircraft_name, key)
        self.aircraft_combo.currentIndexChanged.connect(lambda _i: self._load_plan_for_aircraft())
        lay.addWidget(self.aircraft_combo)

        self.ask_btn = QPushButton("✦ Ask Claude", objectName="AskButton")
        self.ask_btn.setToolTip(
            "Send your aircraft, detected hardware and the current plan to Claude\n"
            "for a tailored review (needs ANTHROPIC_API_KEY)."
        )
        self.ask_btn.clicked.connect(self._ask_claude)
        lay.addWidget(self.ask_btn)

        pin = QToolButton()
        pin.setText("⏏ On top")
        pin.setCheckable(True)
        pin.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        pin.toggled.connect(self._on_pin_toggle)
        lay.addWidget(pin)
        return header

    # ------------------------------------------------------------ main pane
    def _build_main_pane(self) -> QWidget:
        pane = QWidget(objectName="Root")
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(16, 12, 16, 10)
        lay.setSpacing(8)

        title_row = QHBoxLayout()
        self.device_title = QLabel(objectName="SectionTitle")
        title_row.addWidget(self.device_title)
        title_row.addStretch(1)
        self.device_status = QLabel(objectName="SectionMeta")
        title_row.addWidget(self.device_status)
        lay.addLayout(title_row)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["CONTROL", "BIND TO", "SEARCH IN MSFS CONTROLS", "HOW TO USE IT"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setMaximumSectionSize(215)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 200)
        splitter.addWidget(self.table)

        self.guidance = QTextBrowser()
        self.guidance.setOpenExternalLinks(True)
        splitter.addWidget(self.guidance)
        splitter.setSizes([460, 240])
        lay.addWidget(splitter, 1)
        return pane

    # -------------------------------------------------------------- footer
    def _build_footer(self) -> QWidget:
        footer = QWidget(objectName="Footer")
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(8)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText(
            "Notes for Claude — e.g. \"no yoke yet, flying keyboard + Bravo\" or \"I want to practice IFR\"…"
        )
        lay.addWidget(self.notes, 1)
        self.status = QLabel("", objectName="Hint")
        lay.addWidget(self.status)
        return footer

    # ------------------------------------------------------------- sidebar
    def _populate_sidebar(self) -> None:
        header = QListWidgetItem("DEVICES")
        header.setFlags(Qt.ItemFlag.NoItemFlags)
        self.sidebar.addItem(header)
        first = None
        for device in DEVICES:
            on = self.detected.get(device.id, False)
            dot = "●" if on else "○"
            item = QListWidgetItem(f"{dot}  {device.name}")
            item.setData(Qt.ItemDataRole.UserRole, device.id)
            item.setForeground(QColor(theme.GREEN if on else theme.TEXT_DIM))
            self.sidebar.addItem(item)
            if first is None:
                first = item
        self.sidebar.setCurrentItem(first)

    # ---------------------------------------------------------------- plan
    def _current_aircraft_key(self) -> str:
        return self.aircraft_combo.currentData() or next(iter(self.plans))

    def _load_plan_for_aircraft(self) -> None:
        self.plan = self.plans[self._current_aircraft_key()]
        self.status.setText(f"Plan source: {self.plan.source}")
        self._refresh_views()

    def _current_device_id(self) -> str | None:
        item = self.sidebar.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_device_change(self, *_args) -> None:
        self._refresh_views()

    def _refresh_views(self) -> None:
        device_id = self._current_device_id()
        if not self.plan or not device_id:
            return
        device = DEVICE_BY_ID[device_id]
        on = self.detected.get(device_id, False)
        self.device_title.setText(device.name)
        self.device_status.setText(
            f"{device.manufacturer} · " + ("connected" if on else "not detected — plan shown anyway")
        )

        bindings = self.plan.devices.get(device_id, [])
        self.table.setRowCount(len(bindings))
        for row, b in enumerate(bindings):
            cells = [b.control, b.assignment, b.msfs_setting, b.usage_tip]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 1:
                    item.setForeground(QColor(PRIORITY_COLORS.get(b.priority, theme.TEXT)))
                    item.setToolTip(f"priority: {b.priority}")
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()
        self._render_guidance()

    def _render_guidance(self) -> None:
        p = self.plan
        steps = "".join(f"<li style='margin-bottom:6px'>{s}</li>" for s in p.coaching)
        legend = (
            f"<span style='color:{theme.RED}'>■ essential</span> &nbsp; "
            f"<span style='color:{theme.ACCENT}'>■ recommended</span> &nbsp; "
            f"<span style='color:{theme.TEXT_FAINT}'>■ optional</span>"
        )
        self.guidance.setHtml(
            f"<p style='color:{theme.TEXT_DIM}'>{p.summary}</p>"
            f"<p><b style='color:{theme.AMBER}'>Aircraft notes:</b> {p.aircraft_notes}</p>"
            f"<p><b>Setup &amp; flying guide</b></p><ol>{steps}</ol>"
            f"<p>{legend} &nbsp;·&nbsp; <span style='color:{theme.TEXT_FAINT}'>plan source: {p.source}</span></p>"
        )

    # -------------------------------------------------------------- Claude
    def _ask_claude(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        key = self._current_aircraft_key()
        self.ask_btn.setEnabled(False)
        self.ask_btn.setText("✦ Thinking…")
        self.status.setText("Asking Claude to review this setup…")
        self.worker = AdvisorWorker(
            {
                "aircraft_key": key,
                "aircraft_name": self.plans[key].aircraft_name,
                "aircraft_context": _aircraft_context(key),
                "detected": self.detected,
                "current_plan": self.plans[key],
                "user_notes": self.notes.text(),
            }
        )
        self.worker.finished_plan.connect(self._on_plan_ready)
        self.worker.failed.connect(self._on_plan_failed)
        self.worker.start()

    def _on_plan_ready(self, plan: ControlPlan) -> None:
        self.plans[plan.aircraft_key] = plan
        self._reset_ask_button()
        if plan.aircraft_key == self._current_aircraft_key():
            self.plan = plan
            self.status.setText(f"Plan source: {plan.source}")
            self._refresh_views()

    def _on_plan_failed(self, message: str) -> None:
        self._reset_ask_button()
        self.status.setText(message)

    def _reset_ask_button(self) -> None:
        self.ask_btn.setEnabled(True)
        self.ask_btn.setText("✦ Ask Claude")

    # -------------------------------------------------------------- window
    def _on_pin_toggle(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        if self.isVisible():
            self.show()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.QSS + CONTROLS_QSS)
    plans = load_default_plans()
    if not plans:
        print("No binding plans found in controls_app/data/plans", file=sys.stderr)
        return 1
    win = MainWindow(plans, detect_connected())
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
