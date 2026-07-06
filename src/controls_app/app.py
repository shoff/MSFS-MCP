"""MSFS 2024 controls setup advisor — dark, minimal, LLM-assisted.

Run with ``msfs-controls`` or ``python -m controls_app``.

Features: live device visualizers (press a button on the Bravo and it lights
up), Learn mode to map physical inputs exactly, LLM-reviewed binding plans
(Claude, OpenAI, or a local Llama-style model — see MSFS_COMPANION_LLM), and
direct writing of bindings into MSFS input profiles (with backups).
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QEvent, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from companion_common import llm, theme

from . import advisor, msfs_profiles
from .bindings import ControlPlan, load_default_plans
from .device_views import DeviceView, build_views
from .devices import DEVICE_BY_ID, DEVICES, detect_connected
from .input_map import InputMap, load_maps, save_maps
from .input_monitor import InputMonitor

PRIORITY_COLORS = {"essential": theme.RED, "recommended": theme.ACCENT, "optional": theme.TEXT_FAINT}

# How each device is named inside MSFS profile XML <Device DeviceName="...">
MSFS_DEVICE_FRAGMENTS = {
    "honeycomb_alpha": "Alpha Flight Controls",
    "honeycomb_bravo": "Bravo Throttle",
    "velocityone_rudder": "Rudder",
}

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
QPushButton#AskButton, QPushButton#WriteButton {{
    background: {theme.ACCENT_DIM};
    color: {theme.TEXT};
    border-color: {theme.ACCENT_DIM};
    font-weight: 600;
}}
QPushButton#AskButton:hover, QPushButton#WriteButton:hover {{ background: {theme.ACCENT}; color: {theme.INK_ON_BRIGHT}; }}
QPushButton#AskButton:disabled {{ background: {theme.PANEL_ALT}; color: {theme.TEXT_FAINT}; }}
QLabel#RawInput {{
    color: {theme.AMBER};
    font-size: 11px;
    font-family: "Consolas", monospace;
}}
QDialog {{ background: {theme.BG}; }}
QDialog QLabel {{ color: {theme.TEXT}; font-size: 12px; }}
QListWidget {{
    background: {theme.PANEL_ALT};
    color: {theme.TEXT};
    border: 1px solid {theme.BORDER};
    border-radius: 8px;
    font-size: 12px;
}}
QListWidget::item {{ padding: 6px 10px; }}
QListWidget::item:selected {{ background: {theme.ROW_HOVER}; }}
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


class ProfileScanWorker(QThread):
    """Scan for MSFS profiles off the GUI thread (the walk can hit thousands
    of files on a large MS Store install and would otherwise freeze the UI)."""

    scanned = pyqtSignal(list)

    def __init__(self, extra):
        super().__init__()
        self.extra = extra

    def run(self):
        try:
            self.scanned.emit(msfs_profiles.find_profiles(self.extra))
        except Exception:
            self.scanned.emit([])


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


class WriteDialog(QDialog):
    """Pick an MSFS profile, preview the bindings, back up, and write."""

    def __init__(self, parent, plan: ControlPlan, device_id: str, input_map: InputMap):
        super().__init__(parent)
        self.plan = plan
        self.device_id = device_id
        self.input_map = input_map
        self.profiles: list[msfs_profiles.InputProfile] = []

        device = DEVICE_BY_ID[device_id]
        self.setWindowTitle(f"Write bindings to MSFS — {device.name}")
        self.resize(760, 620)

        lay = QVBoxLayout(self)
        intro = QLabel(
            f"<b>{plan.aircraft_name}</b> · {device.name}<br>"
            f"<span style='color:{theme.TEXT_DIM}'>Close MSFS (or at least the Controls menu) first. "
            "Bindings are written into an EXISTING profile — create one for this device in the MSFS "
            "Controls menu if you haven't. A timestamped backup is saved before any change "
            "(~/.msfs_companion/profile_backups).</span>"
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        row = QHBoxLayout()
        row.addWidget(QLabel("Profiles found:"))
        row.addStretch(1)
        rescan = QPushButton("Rescan")
        rescan.clicked.connect(self._scan)
        row.addWidget(rescan)
        browse = QPushButton("Browse folder…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        lay.addLayout(row)

        self.profile_list = QListWidget()
        self.profile_list.setMaximumHeight(140)
        lay.addWidget(self.profile_list)

        self.preview = QTableWidget(0, 3)
        self.preview.setHorizontalHeaderLabels(["MSFS ACTION", "BOUND TO", "FROM CONTROL"])
        self.preview.verticalHeader().setVisible(False)
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.preview.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.preview, 1)

        self.skipped_label = QLabel()
        self.skipped_label.setWordWrap(True)
        self.skipped_label.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        lay.addWidget(self.skipped_label)

        buttons = QDialogButtonBox()
        self.write_btn = buttons.addButton("Backup && Write", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._write)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._resolve()
        self._scan()

    def _resolve(self) -> None:
        device = DEVICE_BY_ID[self.device_id]
        control_ids = {c.label: c.id for c in device.inputs}
        bindings = self.plan.devices.get(self.device_id, [])
        self.resolved = msfs_profiles.resolve_writes(bindings, control_ids, self.input_map)

        self.preview.setRowCount(len(self.resolved.actions))
        for row, aw in enumerate(self.resolved.actions):
            for col, text in enumerate([aw.action_name, aw.keycode, aw.information]):
                self.preview.setItem(row, col, QTableWidgetItem(text))
        if self.resolved.skipped:
            lines = "; ".join(f"{c} ({r})" for c, r in self.resolved.skipped)
            self.skipped_label.setText(f"Set manually in the MSFS UI: {lines}")
        else:
            self.skipped_label.setText("")
        self.write_btn.setEnabled(bool(self.resolved.actions))

    def _scan(self, extra: list | None = None) -> None:
        # A new scan supersedes any in-flight one (e.g. the __init__ system
        # scan when the user immediately hits Browse). We don't drop the new
        # request; we tag it with a generation and ignore stale results.
        self._scan_gen = getattr(self, "_scan_gen", 0) + 1
        gen = self._scan_gen
        self.profile_list.clear()
        self.profile_list.addItem("Scanning for MSFS profiles…")
        worker = ProfileScanWorker(extra)
        worker.setParent(self)
        worker.scanned.connect(lambda profiles, g=gen: self._on_scanned(profiles, g))
        # keep prior workers alive until they finish (QThread must not be
        # destroyed while running), but prune the ones that already have.
        self._workers = [w for w in getattr(self, "_workers", []) if w.isRunning()]
        self._workers.append(worker)
        self._scan_worker = worker
        worker.start()

    def _on_scanned(self, profiles: list, gen: int = 0) -> None:
        if gen != getattr(self, "_scan_gen", 0):
            return  # a newer scan superseded this one
        self.profiles = profiles
        self.profile_list.clear()
        if not profiles:
            self.profile_list.addItem(
                "No MSFS input profiles found — is MSFS installed on this machine? Use Browse…"
            )
            return
        for prof in profiles:
            devices = ", ".join(prof.device_names)
            item = QListWidgetItem(f"{prof.friendly_name}   [{prof.source}]   ({devices})")
            item.setData(Qt.ItemDataRole.UserRole, prof)
            self.profile_list.addItem(item)
        # preselect a profile containing this device
        fragment = MSFS_DEVICE_FRAGMENTS.get(self.device_id, "").lower()
        for i, prof in enumerate(profiles):
            if any(fragment in d.lower() for d in prof.device_names):
                self.profile_list.setCurrentRow(i)
                break

    def done(self, result: int) -> None:  # noqa: N802 — wait out the scan threads
        for worker in getattr(self, "_workers", []):
            if worker.isRunning():
                worker.wait(3000)
        super().done(result)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Folder containing MSFS input profiles")
        if folder:
            from pathlib import Path

            self._scan([Path(folder)])

    def _write(self) -> None:
        item = self.profile_list.currentItem()
        prof = item.data(Qt.ItemDataRole.UserRole) if item else None
        if prof is None:
            QMessageBox.warning(self, "Pick a profile", "Select the MSFS profile to write into.")
            return
        fragment = MSFS_DEVICE_FRAGMENTS.get(self.device_id)
        if not fragment:
            QMessageBox.warning(self, "Not writable", "Keyboard/mouse bindings must be set in the MSFS UI.")
            return
        try:
            backup = msfs_profiles.write_bindings(prof.path, fragment, self.resolved.actions)
        except msfs_profiles.ProfileError as exc:
            QMessageBox.critical(self, "Write failed", str(exc))
            return
        except OSError as exc:
            QMessageBox.critical(self, "Write failed", f"Could not write the file: {exc}")
            return
        QMessageBox.information(
            self,
            "Bindings written",
            f"Wrote {len(self.resolved.actions)} bindings into '{prof.friendly_name}'.\n\n"
            f"Backup: {backup}\n\n"
            "Start (or restart) MSFS and select this profile in Options → Controls. "
            "If anything looks wrong in-game, restore the backup by copying it over the "
            "profile file.",
        )
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, plans: dict[str, ControlPlan], detected: dict[str, bool]):
        super().__init__()
        self.plans = plans
        self.detected = detected
        self.plan: ControlPlan | None = None
        self.worker: AdvisorWorker | None = None
        self.maps = load_maps()
        self.views: dict[str, DeviceView] = build_views()

        self.setWindowTitle("Flight Controls Setup")
        self.resize(1180, 980)
        self.setMinimumSize(820, 640)

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

        # live input
        self.monitor = InputMonitor(self)
        self.monitor.button_changed.connect(self._on_button)
        self.monitor.axis_changed.connect(self._on_axis)
        self.monitor.hat_changed.connect(self._on_hat)
        self.monitor.devices_changed.connect(self._on_devices_changed)
        self.monitor.start()
        QApplication.instance().installEventFilter(self)

        # make sure the shared MCP server is up (detached; survives app close)
        from companion_common.sim_link import McpAutostartWorker

        self.mcp_worker = McpAutostartWorker(self)
        self.mcp_worker.result.connect(self._on_mcp_autostart)
        self.mcp_worker.start()

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

        self.ask_btn = QPushButton("✦ Ask AI", objectName="AskButton")
        self.ask_btn.setToolTip(
            "Send your aircraft, detected hardware and the current plan to Claude\n"
            "for a tailored review (needs ANTHROPIC_API_KEY)."
        )
        self.ask_btn.clicked.connect(self._ask_claude)
        lay.addWidget(self.ask_btn)

        self.write_btn = QPushButton("⭳ Write to MSFS", objectName="WriteButton")
        self.write_btn.setToolTip(
            "Write this device's bindings directly into an MSFS input profile\n"
            "(backs the file up first)."
        )
        self.write_btn.clicked.connect(self._write_to_msfs)
        lay.addWidget(self.write_btn)

        self.verify_btn = QPushButton("▶ Verify live", objectName="WriteButton")
        self.verify_btn.setToolTip(
            "Guided check with MSFS running: operate each control when prompted;\n"
            "the app confirms the hardware moved AND the sim reacted."
        )
        self.verify_btn.clicked.connect(self._verify_live)
        lay.addWidget(self.verify_btn)

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
        self.raw_input = QLabel("", objectName="RawInput")
        title_row.addWidget(self.raw_input)
        self.learn_btn = QToolButton()
        self.learn_btn.setText("🎯 Learn")
        self.learn_btn.setCheckable(True)
        self.learn_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.learn_btn.setToolTip(
            "Learn mode: click a control on the diagram, then press/move the real thing.\n"
            "The mapping is saved and used for highlighting AND for writing MSFS profiles."
        )
        self.learn_btn.toggled.connect(self._on_learn_toggle)
        title_row.addWidget(self.learn_btn)
        rescan = QToolButton()
        rescan.setText("⟳ Rescan")
        rescan.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rescan.setToolTip("Re-detect connected hardware")
        rescan.clicked.connect(lambda: self.monitor.rescan())
        title_row.addWidget(rescan)
        self.device_status = QLabel(objectName="SectionMeta")
        title_row.addWidget(self.device_status)
        lay.addLayout(title_row)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.view_stack = QStackedWidget()
        for device_id, view in self.views.items():
            view.element_clicked.connect(self._on_element_clicked)
            self.view_stack.addWidget(view)
        splitter.addWidget(self.view_stack)

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
        splitter.setSizes([300, 330, 190])
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
        self.sidebar.clear()
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
        self.view_stack.setCurrentWidget(self.views[device_id])

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

    # ---------------------------------------------------------- live input
    def _on_devices_changed(self, detected: dict) -> None:
        self.detected = detected
        self._populate_sidebar()

    def _view_and_map(self, device_id: str) -> tuple[DeviceView, InputMap]:
        return self.views[device_id], self.maps[device_id]

    # -- Learn-mode capture (multi-slot, ordered) --------------------------
    def _control_kind(self, device_id: str, control_id: str) -> str:
        for c in DEVICE_BY_ID[device_id].inputs:
            if c.id == control_id:
                return c.kind
        return "button"

    def _spec_for_control(self, device_id: str, control_id: str):
        """The canonical SettingSpec this control is bound to in the active plan."""
        from .input_map import lookup_control
        from .settings_registry import spec_for_setting

        for b in self.plan.devices.get(device_id, []):
            if lookup_control(b.control, {c.label: c.id for c in DEVICE_BY_ID[device_id].inputs}) == control_id:
                return spec_for_setting(b.msfs_setting)
        return None

    def _begin_capture(self, device_id: str, control_id: str) -> None:
        kind = self._control_kind(device_id, control_id)
        spec = self._spec_for_control(device_id, control_id)
        if kind in ("axis", "lever"):
            self._learn = {"control": control_id, "is_axis": True, "labels": ["move it fully"], "buffer": []}
            prompt = "move the physical axis fully"
        else:
            labels = list(spec.slots) if (spec and spec.kind == "button" and len(spec.slots) > 1) else ["press it"]
            self._learn = {"control": control_id, "is_axis": False, "labels": labels, "buffer": []}
            prompt = labels[0]
        self.status.setText(f"Learn '{control_id}': {prompt}…")

    def _learn_active(self, control_id: str) -> bool:
        return getattr(self, "_learn", None) is not None and self._learn["control"] == control_id

    def _on_button(self, device_id: str, index: int, pressed: bool) -> None:
        view, imap = self._view_and_map(device_id)
        self.raw_input.setText(f"{device_id}: button {index} {'▼' if pressed else '▲'}")
        learn = getattr(self, "_learn", None)
        if pressed and view.learn_mode and learn and not learn["is_axis"]:
            if index in learn["buffer"]:
                return  # ignore a repeat of an already-captured slot
            learn["buffer"].append(index)
            view.pulse(learn["control"])
            if len(learn["buffer"]) >= len(learn["labels"]):
                imap.set_control_buttons(learn["control"], learn["buffer"])
                save_maps(self.maps)
                self.status.setText(
                    f"Learned {learn['control']} → buttons {learn['buffer']} (saved)"
                )
                self._learn = None
            else:
                nxt = learn["labels"][len(learn["buffer"])]
                self.status.setText(f"Learn '{learn['control']}': now {nxt}…")
            return
        control = imap.control_for_button(index)
        if control:
            view.set_pressed(control, pressed)

    def _on_axis(self, device_id: str, index: int, value: float) -> None:
        view, imap = self._view_and_map(device_id)
        self.raw_input.setText(f"{device_id}: axis {index} = {value:+.2f}")
        learn = getattr(self, "_learn", None)
        if view.learn_mode and learn and learn["is_axis"] and abs(value) > 0.75:
            imap.learn_axis(index, learn["control"])
            save_maps(self.maps)
            self.status.setText(f"Learned {learn['control']} → axis {index} (saved)")
            self._learn = None
        control = imap.control_for_axis(index)
        if control:
            view.set_value(control, value)

    def _on_hat(self, device_id: str, index: int, x: int, y: int) -> None:
        view, imap = self._view_and_map(device_id)
        if x or y:
            self.raw_input.setText(f"{device_id}: hat {index} = ({x},{y})")
            control = imap.hats.get(index)
            if control:
                view.pulse(control)

    def _on_element_clicked(self, control_id: str) -> None:
        view = self.view_stack.currentWidget()
        if isinstance(view, DeviceView) and view.learn_mode:
            view.set_selected(control_id)
            self._begin_capture(view.device_id, control_id)

    def _on_learn_toggle(self, on: bool) -> None:
        self._learn = None
        for view in self.views.values():
            view.learn_mode = on
            if not on:
                view.set_selected(None)
        self.status.setText(
            "Learn mode: click a control on the diagram, then press the real input(s) it prompts for."
            if on else ""
        )

    def eventFilter(self, obj, event):  # noqa: N802 — keyboard/mouse visualizer
        if self.isActiveWindow():
            view = self.views.get("keyboard_mouse")
            if event.type() == QEvent.Type.KeyPress and view:
                view.pulse("keys")
            elif event.type() == QEvent.Type.MouseButtonPress and view:
                view.pulse("mouse")
        return super().eventFilter(obj, event)

    # -------------------------------------------------------------- Claude
    def _ask_claude(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        key = self._current_aircraft_key()
        self.ask_btn.setEnabled(False)
        self.ask_btn.setText("✦ Thinking…")
        self.status.setText(f"Asking {llm.model_label()} to review this setup…")
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
        self.ask_btn.setText("✦ Ask AI")

    # ------------------------------------------------------------ profiles
    def _write_to_msfs(self) -> None:
        device_id = self._current_device_id()
        if not device_id or device_id == "keyboard_mouse":
            QMessageBox.information(
                self, "Pick a device",
                "Select the Alpha, Bravo or rudder pedals in the sidebar — keyboard/mouse "
                "bindings are quick to set in the MSFS UI itself.",
            )
            return
        dialog = WriteDialog(self, self.plan, device_id, self.maps[device_id])
        dialog.exec()

    def _verify_live(self) -> None:
        from .verify_dialog import VerifyDialog

        device_id = self._current_device_id()
        if not device_id or device_id == "keyboard_mouse":
            QMessageBox.information(
                self, "Pick a device",
                "Select the Alpha, Bravo or rudder pedals in the sidebar to verify.",
            )
            return
        bindings = self.plan.devices.get(device_id, [])
        dialog = VerifyDialog(self, device_id, bindings, self.maps[device_id], self.monitor)
        dialog.exec()

    def _on_mcp_autostart(self, status: str) -> None:
        message = {
            "started": "MCP server started ✓ (http://127.0.0.1:8787/mcp)",
            "already-running": "MCP server already running ✓",
            "failed": "MCP autostart failed — see ~/.msfs_companion/mcp-server.log",
        }.get(status)
        if message:
            self.status.setText(message)

    # -------------------------------------------------------------- window
    def _on_pin_toggle(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        if self.isVisible():
            self.show()

    def closeEvent(self, event):  # noqa: N802
        self.monitor.stop()
        # Wait out any in-flight worker threads so none is destroyed mid-run
        # (Qt aborts the process on "QThread destroyed while running").
        for attr in ("mcp_worker", "worker"):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                worker.wait(6000)
        super().closeEvent(event)


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
