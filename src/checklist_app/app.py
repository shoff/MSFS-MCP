"""Electronic flight checklist — dark, minimal, MSFS-friendly.

Run with ``msfs-checklist`` or ``python -m checklist_app``.

Designed to sit alongside Microsoft Flight Simulator (borderless windowed
mode recommended): stays on top when pinned, fully keyboard-driven, and
adjustable opacity so it can float over the sim.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from companion_common import theme
from .models import Aircraft, ChecklistItem, ChecklistSection, load_aircraft
from companion_common.sim_link import McpAutostartWorker, STATE_CONNECTING, STATE_LIVE, STATE_OFFLINE, SimLink
from .verify import parse_verify, satisfied, vars_needed

GROUP_LABELS = {"Normal": "NORMAL PROCEDURES", "Emergency": "EMERGENCY", "Abnormal": "ABNORMAL"}
VSPEEDS_KEY = -1  # sidebar sentinel for the V-speeds reference page


class ItemRow(QWidget):
    """A single challenge → response checklist line, custom painted."""

    toggled = pyqtSignal(object)

    def __init__(self, item: ChecklistItem, emergency: bool, reference: bool = False):
        super().__init__()
        self.item = item
        self.emergency = emergency
        self.reference = reference  # non-checkable info row (V-speeds)
        self._current = False
        self._hover = False
        self.sim_live = False  # painted hint: sim can auto-verify this item
        try:
            self.conditions = parse_verify(item.verify) if item.verify else []
        except ValueError:
            self.conditions = []  # tolerate bad verify data (e.g. hand-edited JSON)
        self.setFixedHeight(38)
        self.setMouseTracking(True)
        if not reference:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- state -------------------------------------------------------------
    def set_current(self, current: bool) -> None:
        if self._current != current:
            self._current = current
            self.update()

    # -- events ------------------------------------------------------------
    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton and not self.reference:
            self.toggled.emit(self)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(6, 1, -6, -1)

        if self._current:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.ROW_HOVER))
            p.drawRoundedRect(r, 8, 8)
            p.setBrush(QColor(theme.RED if self.emergency else theme.ACCENT))
            p.drawRoundedRect(r.left(), r.top() + 6, 3, r.height() - 12, 1, 1)
        elif self._hover and not self.reference:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#141b25"))
            p.drawRoundedRect(r, 8, 8)

        cy = r.center().y() + 1
        x = r.left() + 16

        # status circle (skipped for reference rows)
        if not self.reference:
            cx = x + 8
            if self.item.checked:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.GREEN))
                p.drawEllipse(cx - 8, cy - 8, 16, 16)
                pen = QPen(QColor("#0b1016"), 2)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(cx - 4, cy, cx - 1, cy + 3)
                p.drawLine(cx - 1, cy + 3, cx + 4, cy - 3)
                if self.item.sim_checked:  # amber corner dot = confirmed by the sim
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(theme.AMBER))
                    p.drawEllipse(cx + 4, cy - 9, 6, 6)
            else:
                ring = theme.RED_DIM if self.emergency else theme.TEXT_FAINT
                p.setPen(QPen(QColor(ring), 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(cx - 7, cy - 7, 14, 14)
                if self.conditions:  # sim-verifiable: inner dot, amber when live
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(theme.AMBER if self.sim_live else theme.TEXT_FAINT))
                    p.drawEllipse(cx - 2, cy - 2, 5, 5)
            x = cx + 20

        # fonts
        challenge_font = self.font()
        challenge_font.setPointSizeF(10.5)
        challenge_font.setWeight(QFont.Weight.DemiBold if self.item.memory else QFont.Weight.Normal)
        response_font = self.font()
        response_font.setPointSizeF(10.5)
        response_font.setWeight(QFont.Weight.DemiBold)

        fm_c = QFontMetrics(challenge_font)
        fm_r = QFontMetrics(response_font)

        # colors
        if self.item.checked:
            c_color, r_color = theme.TEXT_FAINT, theme.TEXT_FAINT
        else:
            c_color = theme.TEXT
            if self.reference:
                r_color = theme.AMBER
            elif self.emergency:
                r_color = "#ff8a8a"
            else:
                r_color = theme.ACCENT
            if self.item.memory and not self.item.checked:
                c_color = "#ffd9d9" if self.emergency else theme.TEXT

        right = r.right() - 14
        resp = self.item.response
        resp_w = fm_r.horizontalAdvance(resp)
        max_resp = int((right - x) * 0.62)
        if resp_w > max_resp:
            resp = fm_r.elidedText(resp, Qt.TextElideMode.ElideRight, max_resp)
            resp_w = fm_r.horizontalAdvance(resp)

        avail_c = right - x - resp_w - 16
        chall = fm_c.elidedText(self.item.challenge, Qt.TextElideMode.ElideRight, max(20, avail_c))
        chall_w = fm_c.horizontalAdvance(chall)

        p.setFont(challenge_font)
        p.setPen(QColor(c_color))
        p.drawText(x, cy + fm_c.ascent() // 2 - 1, chall)

        # memory-item marker
        if self.item.memory:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.RED))
            p.drawEllipse(x + chall_w + 6, cy - 2, 4, 4)

        p.setFont(response_font)
        p.setPen(QColor(r_color))
        p.drawText(right - resp_w, cy + fm_r.ascent() // 2 - 1, resp)

        # dotted leader
        lead_start = x + chall_w + (16 if self.item.memory else 10)
        lead_end = right - resp_w - 10
        if lead_end - lead_start > 12:
            pen = QPen(QColor(theme.TEXT_FAINT), 1, Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.drawLine(lead_start, cy + 4, lead_end, cy + 4)


class NoteRow(QLabel):
    """Informational / conditional line inside a checklist ("If engine starts:")."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setWordWrap(True)
        self.setStyleSheet(
            f"color: {theme.AMBER}; font-size: 11px; font-style: italic;"
            "padding: 6px 20px 2px 50px; background: transparent;"
        )


class MainWindow(QMainWindow):
    def __init__(self, aircraft: list[Aircraft]):
        super().__init__()
        self.aircraft_list = aircraft
        self.aircraft = aircraft[0]
        self.section: ChecklistSection | None = None
        self.rows: list[ItemRow] = []
        self.check_rows: list[ItemRow] = []
        self.cur = 0
        self._building = False

        self.setWindowTitle("Flight Checklist")
        self.resize(640, 880)
        self.setMinimumSize(460, 560)

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
        self.sidebar.setFixedWidth(212)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sidebar.setWordWrap(False)
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sidebar.currentItemChanged.connect(self._on_sidebar_change)
        body.addWidget(self.sidebar)

        body.addWidget(self._build_checklist_pane(), 1)
        outer.addLayout(body, 1)
        outer.addWidget(self._build_footer())

        self._load_aircraft(self.aircraft)
        self.pin_btn.setChecked(True)

        # flight recorder (feeds the post-flight debrief)
        from .flight_log import RECORDER_VARS, FlightRecorder

        self.recorder = FlightRecorder()
        self.recorder.set_aircraft(self.aircraft.name, self.aircraft.vspeeds)
        self._completed_sections: set[str] = set()

        # live sim verification
        self.sim_state = STATE_OFFLINE
        self.sim = SimLink(self)
        self.sim.state_changed.connect(self._on_sim_state)
        self.sim.values_read.connect(self._on_sim_values)
        self.sim.set_base_watch(set(RECORDER_VARS))
        self.sim.start()

        # make sure the shared MCP server is up (detached; survives app close)
        self.mcp_worker = McpAutostartWorker(self)
        self.mcp_worker.result.connect(self._on_mcp_autostart)
        self.mcp_worker.start()

    # ------------------------------------------------------------- header
    def _build_header(self) -> QWidget:
        header = QWidget(objectName="Header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(16, 10, 12, 10)
        lay.setSpacing(10)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(QLabel("PRE-FLIGHT", objectName="AppSubtitle"))
        titles.addWidget(QLabel("Checklist", objectName="AppTitle"))
        lay.addLayout(titles)
        lay.addStretch(1)

        self.aircraft_combo = QComboBox()
        self.aircraft_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for ac in self.aircraft_list:
            self.aircraft_combo.addItem(ac.name)
        self.aircraft_combo.currentIndexChanged.connect(self._on_aircraft_change)
        lay.addWidget(self.aircraft_combo)

        self.debrief_btn = QToolButton()
        self.debrief_btn.setText("🎓 Debrief")
        self.debrief_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.debrief_btn.setToolTip(
            "Post-flight debrief: local flight stats now, and an instructor-style\n"
            "review from Claude (needs ANTHROPIC_API_KEY)."
        )
        self.debrief_btn.clicked.connect(self._open_debrief)
        lay.addWidget(self.debrief_btn)

        self.sim_chip = QToolButton()
        self.sim_chip.setText("○ SIM")
        self.sim_chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sim_chip.setToolTip(
            "Live sim verification: items with a dot check themselves when you\n"
            "actually do them in the cockpit. Click to retry the connection."
        )
        self.sim_chip.clicked.connect(lambda: self.sim.request_reconnect())
        lay.addWidget(self.sim_chip)

        self.pin_btn = QToolButton()
        self.pin_btn.setText("⏏ On top")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pin_btn.setToolTip("Keep this window above MSFS (borderless windowed mode)")
        self.pin_btn.toggled.connect(self._on_pin_toggle)
        lay.addWidget(self.pin_btn)
        return header

    # ---------------------------------------------------------- checklist
    def _build_checklist_pane(self) -> QWidget:
        pane = QWidget(objectName="Root")
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(18, 14, 18, 8)
        lay.setSpacing(8)

        title_row = QHBoxLayout()
        self.section_title = QLabel(objectName="SectionTitle")
        title_row.addWidget(self.section_title)
        title_row.addStretch(1)
        self.complete_badge = QLabel("✓ COMPLETE", objectName="CompleteBadge")
        self.complete_badge.hide()
        title_row.addWidget(self.complete_badge)
        lay.addLayout(title_row)

        self.section_meta = QLabel(objectName="SectionMeta")
        self.section_meta.setWordWrap(True)
        lay.addWidget(self.section_meta)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        lay.addWidget(self.progress)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.canvas = QWidget(objectName="ChecklistCanvas")
        self.canvas_lay = QVBoxLayout(self.canvas)
        self.canvas_lay.setContentsMargins(0, 4, 0, 20)
        self.canvas_lay.setSpacing(0)
        self.canvas_lay.addStretch(1)
        self.scroll.setWidget(self.canvas)
        lay.addWidget(self.scroll, 1)
        return pane

    # -------------------------------------------------------------- footer
    def _build_footer(self) -> QWidget:
        footer = QWidget(objectName="Footer")
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(8)

        reset = QPushButton("Reset")
        reset.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        reset.setToolTip("Reset this checklist (R)")
        reset.clicked.connect(self.reset_section)
        lay.addWidget(reset)

        self.hint = QLabel(
            "Space check · ↑↓ move · [ ] checklist · E emergency · Ctrl+↑↓ opacity",
            objectName="Hint",
        )
        lay.addWidget(self.hint, 1)

        self.next_btn = QPushButton("Next ▸", objectName="NextButton")
        self.next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next_btn.setToolTip("Jump to the next checklist (])")
        self.next_btn.clicked.connect(lambda: self.step_section(1))
        lay.addWidget(self.next_btn)
        return footer

    # ------------------------------------------------------------ aircraft
    def _on_aircraft_change(self, idx: int) -> None:
        if 0 <= idx < len(self.aircraft_list):
            self._load_aircraft(self.aircraft_list[idx])

    def _load_aircraft(self, aircraft: Aircraft) -> None:
        self.aircraft = aircraft
        aircraft.reset()
        if hasattr(self, "recorder"):
            self.recorder.set_aircraft(aircraft.name, aircraft.vspeeds)
            self._completed_sections.clear()
        self._populate_sidebar()

    def _populate_sidebar(self) -> None:
        self._building = True
        self.sidebar.clear()
        current_group = None
        first_item = None
        for i, sec in enumerate(self.aircraft.sections):
            if sec.group != current_group:
                current_group = sec.group
                header = QListWidgetItem(GROUP_LABELS.get(sec.group, sec.group.upper()))
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self.sidebar.addItem(header)
            entry = QListWidgetItem(sec.name)
            entry.setData(Qt.ItemDataRole.UserRole, i)
            if sec.is_emergency:
                entry.setForeground(QColor("#e07070"))
            self.sidebar.addItem(entry)
            if first_item is None:
                first_item = entry
        ref_header = QListWidgetItem("REFERENCE")
        ref_header.setFlags(Qt.ItemFlag.NoItemFlags)
        self.sidebar.addItem(ref_header)
        vs = QListWidgetItem("V-Speeds")
        vs.setData(Qt.ItemDataRole.UserRole, VSPEEDS_KEY)
        vs.setForeground(QColor(theme.AMBER))
        self.sidebar.addItem(vs)
        self._building = False
        self.sidebar.setCurrentItem(first_item)

    def _refresh_sidebar_counts(self) -> None:
        for i in range(self.sidebar.count()):
            entry = self.sidebar.item(i)
            idx = entry.data(Qt.ItemDataRole.UserRole)
            if idx is None or idx == VSPEEDS_KEY:
                continue
            sec = self.aircraft.sections[idx]
            mark = "  ✓" if sec.complete else ""
            entry.setText(f"{sec.name}{mark}")

    # ------------------------------------------------------------ sections
    def _on_sidebar_change(self, current: QListWidgetItem | None, _prev=None) -> None:
        if self._building or current is None:
            return
        idx = current.data(Qt.ItemDataRole.UserRole)
        if idx == VSPEEDS_KEY:
            self._show_vspeeds()
        elif idx is not None:
            self._show_section(self.aircraft.sections[idx])

    def _clear_canvas(self) -> None:
        while self.canvas_lay.count() > 1:
            widget = self.canvas_lay.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)  # detach visually right away
                widget.deleteLater()
        self.rows = []
        self.check_rows = []

    def _show_section(self, section: ChecklistSection) -> None:
        self.section = section
        self._clear_canvas()
        self.section_title.setText(section.name)
        self.section_title.setProperty("emergency", "true" if section.is_emergency else "false")
        self.section_title.style().unpolish(self.section_title)
        self.section_title.style().polish(self.section_title)
        verifiable = sum(1 for i in section.items if i.verifiable)
        self.section_meta.setText(
            f"{self.aircraft.short_name} · {GROUP_LABELS.get(section.group, section.group)}"
            + (" · ▪ = memory item" if any(i.memory for i in section.items) else "")
            + (f" · • {verifiable} sim-verified" if verifiable else "")
        )
        self.progress.setProperty("emergency", "true" if section.is_emergency else "false")
        self.progress.style().unpolish(self.progress)
        self.progress.style().polish(self.progress)
        self.progress.show()

        insert_at = self.canvas_lay.count() - 1
        for item in section.items:
            if item.kind == "note":
                self.canvas_lay.insertWidget(insert_at, NoteRow(item.challenge))
            else:
                row = ItemRow(item, emergency=section.is_emergency)
                row.sim_live = getattr(self, "sim_state", "") == STATE_LIVE
                row.toggled.connect(self._on_row_clicked)
                self.canvas_lay.insertWidget(insert_at, row)
                self.rows.append(row)
                self.check_rows.append(row)
            insert_at = self.canvas_lay.count() - 1

        self.cur = self._first_unchecked()
        self._apply_current()
        self._refresh_progress()
        self.scroll.verticalScrollBar().setValue(0)
        self._update_sim_watch()

    def _show_vspeeds(self) -> None:
        self.section = None
        self._clear_canvas()
        self.section_title.setText("V-Speeds")
        self.section_title.setProperty("emergency", "false")
        self.section_title.style().unpolish(self.section_title)
        self.section_title.style().polish(self.section_title)
        self.section_meta.setText(f"{self.aircraft.short_name} · Reference — {self.aircraft.source}")
        self.progress.hide()
        self.complete_badge.hide()
        insert_at = self.canvas_lay.count() - 1
        for label, value in self.aircraft.vspeeds:
            row = ItemRow(ChecklistItem(challenge=label, response=value), emergency=False, reference=True)
            self.canvas_lay.insertWidget(insert_at, row)
            insert_at = self.canvas_lay.count() - 1

    # ---------------------------------------------------------- item logic
    def _first_unchecked(self) -> int:
        for i, row in enumerate(self.check_rows):
            if not row.item.checked:
                return i
        return max(0, len(self.check_rows) - 1)

    def _apply_current(self) -> None:
        for i, row in enumerate(self.check_rows):
            row.set_current(i == self.cur and not self._section_complete())
        if self.check_rows and self.cur < len(self.check_rows):
            self.scroll.ensureWidgetVisible(self.check_rows[self.cur], 0, 80)

    def _section_complete(self) -> bool:
        return self.section is not None and self.section.complete

    def _on_row_clicked(self, row: ItemRow) -> None:
        row.item.checked = not row.item.checked
        if not row.item.checked:
            row.item.sim_checked = False
        elif self.section is not None:
            self.recorder.log_item(self.section.name, row.item.challenge, row.item.response, via_sim=False)
        row.update()
        if row.item.checked:
            self.cur = self._first_unchecked()
        else:
            self.cur = self.check_rows.index(row)
        self._apply_current()
        self._refresh_progress()

    def toggle_current(self) -> None:
        if not self.check_rows:
            return
        row = self.check_rows[self.cur]
        row.item.checked = not row.item.checked
        if not row.item.checked:
            row.item.sim_checked = False
        elif self.section is not None:
            self.recorder.log_item(self.section.name, row.item.challenge, row.item.response, via_sim=False)
        row.update()
        if row.item.checked:
            nxt = self._first_unchecked()
            self.cur = nxt
        self._apply_current()
        self._refresh_progress()

    def move_current(self, delta: int) -> None:
        if not self.check_rows:
            return
        self.cur = max(0, min(len(self.check_rows) - 1, self.cur + delta))
        self._apply_current()

    def reset_section(self) -> None:
        if self.section is None:
            return
        self.section.reset()
        for row in self.check_rows:
            row.update()
        self.cur = 0
        self._apply_current()
        self._refresh_progress()

    def _refresh_progress(self) -> None:
        if self.section is None:
            return
        total = max(1, self.section.total_count)
        self.progress.setMaximum(total)
        self.progress.setValue(self.section.done_count)
        self.complete_badge.setVisible(self.section.complete)
        if self.section.complete and self.section.name not in self._completed_sections:
            self._completed_sections.add(self.section.name)
            self.recorder.log_section_complete(self.section.name)
        self._refresh_sidebar_counts()

    # ------------------------------------------------------ section nav
    def step_section(self, delta: int) -> None:
        entries = [
            i for i in range(self.sidebar.count())
            if self.sidebar.item(i).data(Qt.ItemDataRole.UserRole) is not None
        ]
        if not entries:
            return
        cur_row = self.sidebar.currentRow()
        try:
            pos = entries.index(cur_row)
        except ValueError:
            pos = 0
        pos = max(0, min(len(entries) - 1, pos + delta))
        self.sidebar.setCurrentRow(entries[pos])

    def jump_to_emergency(self) -> None:
        for i in range(self.sidebar.count()):
            idx = self.sidebar.item(i).data(Qt.ItemDataRole.UserRole)
            if idx is not None and idx != VSPEEDS_KEY and self.aircraft.sections[idx].is_emergency:
                self.sidebar.setCurrentRow(i)
                return

    # ------------------------------------------------------- sim verification
    def _update_sim_watch(self) -> None:
        """Watch every verify var in the active section."""
        watch: set[str] = set()
        for row in self.check_rows:
            watch |= vars_needed(row.conditions)
        if hasattr(self, "sim"):
            self.sim.set_watch(watch)

    def _on_sim_state(self, state: str) -> None:
        self.sim_state = state
        live = state == STATE_LIVE
        label = {STATE_LIVE: "● SIM LIVE", STATE_CONNECTING: "◌ SIM…", STATE_OFFLINE: "○ SIM"}[state]
        color = {STATE_LIVE: theme.GREEN, STATE_CONNECTING: theme.AMBER, STATE_OFFLINE: theme.TEXT_FAINT}[state]
        self.sim_chip.setText(label)
        self.sim_chip.setStyleSheet(f"QToolButton {{ color: {color}; }}")
        for row in self.check_rows:
            row.sim_live = live
            row.update()

    def _on_sim_values(self, values: dict) -> None:
        """Auto-check the CURRENT item when the sim shows it done (strict flow order).

        Cascades: if checking the current item makes the next one current and
        the same snapshot already satisfies it, it checks too.
        """
        if self.sim_state != STATE_LIVE:
            return
        self.recorder.update(values)  # feed the flight recorder / debrief
        if not self.check_rows:
            return
        advanced = False
        for _ in range(len(self.check_rows)):
            if self.cur >= len(self.check_rows):
                break
            row = self.check_rows[self.cur]
            if row.item.checked or not row.conditions or not satisfied(row.conditions, values):
                break
            row.item.checked = True
            row.item.sim_checked = True
            if self.section is not None:
                self.recorder.log_item(self.section.name, row.item.challenge, row.item.response, via_sim=True)
            row.update()
            self.cur = self._first_unchecked()
            advanced = True
        if advanced:
            self._apply_current()
            self._refresh_progress()

    def _on_mcp_autostart(self, status: str) -> None:
        base = "Space check · ↑↓ move · [ ] checklist · E emergency · Ctrl+↑↓ opacity"
        suffix = {
            "started": "MCP server started ✓",
            "already-running": "MCP server ✓",
            "failed": "MCP autostart failed (~/.msfs_companion/mcp-server.log)",
        }.get(status)
        if suffix:
            self.hint.setText(f"{base} · {suffix}")

    # ------------------------------------------------------------- window
    def _on_pin_toggle(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        if self.isVisible():
            self.show()  # re-show required after changing window flags

    def _open_debrief(self) -> None:
        from .debrief_dialog import DebriefDialog

        DebriefDialog(self, self.recorder).exec()

    def closeEvent(self, event):  # noqa: N802
        if hasattr(self, "sim"):
            self.sim.stop()
            self.sim.wait(3000)
        # Block until the autostart probe and any debrief workers return so no
        # QThread is destroyed mid-run (Qt aborts the process otherwise).
        if getattr(self, "mcp_worker", None) is not None:
            self.mcp_worker.wait(6000)
        for child in self.findChildren(QThread):
            if child.isRunning():
                child.wait(6000)
        recorder = getattr(self, "recorder", None)
        if recorder is not None and recorder.has_data and not recorder.saved:
            try:
                recorder.save()  # safety net — don't lose an unsaved flight
            except OSError:
                pass
        super().closeEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Up:
                self.setWindowOpacity(min(1.0, self.windowOpacity() + 0.1))
                return
            if key == Qt.Key.Key_Down:
                self.setWindowOpacity(max(0.4, self.windowOpacity() - 0.1))
                return
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle_current()
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_J):
            self.move_current(1)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_K):
            self.move_current(-1)
        elif key in (Qt.Key.Key_BracketRight, Qt.Key.Key_PageDown):
            self.step_section(1)
        elif key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_PageUp):
            self.step_section(-1)
        elif key == Qt.Key.Key_E:
            self.jump_to_emergency()
        elif key == Qt.Key.Key_R:
            self.reset_section()
        else:
            super().keyPressEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.QSS)
    aircraft = load_aircraft()
    if not aircraft:
        print("No aircraft data found in checklist_app/data", file=sys.stderr)
        return 1
    win = MainWindow(aircraft)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
