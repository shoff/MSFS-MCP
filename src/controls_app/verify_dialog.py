"""Guided live verification of MSFS bindings.

Walks the pilot through each testable binding: "move the throttle now".
Watches two independent channels at once —
  hardware: the mapped physical input via InputMonitor
  sim:      the expected SimVar via SimLink (baseline -> change)
Both seen -> PASS. Hardware seen but the sim never reacts -> FAIL, which is
exactly the diagnosis of a bad MSFS binding. Sim offline -> hardware-only mode.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from PyQt6.QtGui import QColor

from companion_common import theme
from companion_common.sim_link import STATE_LIVE, STATE_OFFLINE, SimLink

from .binding_check import BindingTest, build_tests
from .devices import DEVICE_BY_ID

SIM_FAIL_TIMEOUT_MS = 6000   # hardware seen, sim silent this long -> FAIL
ADVANCE_DELAY_MS = 700

STATUS_LABELS = {
    "pending": ("…", theme.TEXT_FAINT),
    "active": ("▶ TESTING", theme.AMBER),
    "passed": ("✓ PASS", theme.GREEN),
    "hw_only": ("✓ HW (sim offline)", theme.ACCENT),
    "failed": ("✗ FAIL — fix in MSFS", theme.RED),
    "skipped": ("— skipped", theme.TEXT_FAINT),
}


class VerifyDialog(QDialog):
    def __init__(self, parent, device_id: str, plan_bindings, input_map, monitor):
        super().__init__(parent)
        self.device_id = device_id
        self.input_map = input_map
        self.monitor = monitor
        device = DEVICE_BY_ID[device_id]

        result = build_tests(plan_bindings, {c.label: c.id for c in device.inputs}, input_map)
        self.tests: list[BindingTest] = result.tests
        self.untestable = result.untestable
        self.idx = -1
        self.baseline: float | None = None
        self.sim_live = False
        self.sim_settled_offline = False  # True once a connect attempt has concluded

        self.setWindowTitle(f"Verify bindings live — {device.name}")
        self.resize(720, 600)

        lay = QVBoxLayout(self)
        self.instruction = QLabel()
        self.instruction.setWordWrap(True)
        self.instruction.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.TEXT}; padding: 6px 2px;"
        )
        lay.addWidget(self.instruction)

        self.sub = QLabel()
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        lay.addWidget(self.sub)

        # Live feedback so the screen never looks dead: sim link state + the last
        # raw input we saw from this device (proves input is arriving even if it
        # isn't the control being tested — the #1 "nothing happens" confusion).
        self.simchip = QLabel()
        self.simchip.setStyleSheet("font-size: 11px;")
        lay.addWidget(self.simchip)
        self._update_simchip()
        self.raw = QLabel("Waiting for input — move a control on this device…")
        self.raw.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11px; font-family: Consolas, monospace;"
        )
        lay.addWidget(self.raw)

        self.table = QTableWidget(len(self.tests), 4)
        self.table.setHorizontalHeaderLabels(["CONTROL", "WATCHING SIMVAR", "HW / SIM", "RESULT"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        for row, t in enumerate(self.tests):
            self.table.setItem(row, 0, QTableWidgetItem(t.control))
            self.table.setItem(row, 1, QTableWidgetItem(t.spec.var))
            self.table.setItem(row, 2, QTableWidgetItem("· / ·"))
            self.table.setItem(row, 3, QTableWidgetItem("…"))
        lay.addWidget(self.table, 1)

        if self.untestable:
            skipped = QLabel(
                "Not auto-testable: "
                + "; ".join(f"{c} ({r})" for c, r in self.untestable)
            )
            skipped.setWordWrap(True)
            skipped.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
            lay.addWidget(skipped)

        row = QHBoxLayout()
        self.skip_btn = QPushButton("Skip this control")
        self.skip_btn.clicked.connect(lambda: self._finish_current("skipped"))
        row.addWidget(self.skip_btn)
        self.restart_btn = QPushButton("Restart")
        self.restart_btn.clicked.connect(self._restart)
        row.addWidget(self.restart_btn)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

        self.fail_timer = QTimer(self)
        self.fail_timer.setSingleShot(True)
        self.fail_timer.timeout.connect(self._on_sim_timeout)
        # A single restartable timer for advancing — prevents double-Skip (or
        # Skip racing an auto-pass) from queuing two advances and wedging a test.
        self.advance_timer = QTimer(self)
        self.advance_timer.setSingleShot(True)
        self.advance_timer.timeout.connect(self._advance)

        # hardware channel (test matching + an always-on raw readout)
        self.monitor.button_changed.connect(self._on_button)
        self.monitor.axis_changed.connect(self._on_axis)
        self.monitor.button_changed.connect(self._on_raw_button)
        self.monitor.axis_changed.connect(self._on_raw_axis)

        # sim channel (own link so the watch set is ours)
        self.sim = SimLink(self)
        self.sim.state_changed.connect(self._on_sim_state)
        self.sim.values_read.connect(self._on_sim_values)
        self.sim.start()

        self._advance()

    # ---------------------------------------------------------------- flow
    def current(self) -> BindingTest | None:
        return self.tests[self.idx] if 0 <= self.idx < len(self.tests) else None

    def _advance(self) -> None:
        self.fail_timer.stop()
        self.advance_timer.stop()
        self.idx += 1
        self.baseline = None
        t = self.current()
        if t is None:
            self._show_summary()
            return
        t.status = "active"
        self.sim.set_watch({t.spec.var})
        self.instruction.setText(f"▶  Now operate: {t.control}")
        self.sub.setText(
            f"{t.assignment} — {t.spec.hint or 'move it now'}. Watching {t.spec.var}."
            + ("" if self.sim_live else "  (sim offline: hardware-only check)")
        )
        self._paint_row(self.idx)
        self.table.scrollToItem(self.table.item(self.idx, 0))

    def _finish_current(self, status: str) -> None:
        t = self.current()
        if t is None or t.status != "active":  # ignore a second finish on a done test
            return
        t.status = status
        self.fail_timer.stop()
        self._paint_row(self.idx)
        self.advance_timer.start(ADVANCE_DELAY_MS)  # restart, never stack

    def _maybe_pass(self) -> None:
        t = self.current()
        if t is None or t.status != "active":
            return
        if t.hw_seen and t.sim_seen:
            self._finish_current("passed")
        elif t.hw_seen and self.sim_settled_offline:
            # Only grade hardware-only once we KNOW the sim is unreachable — not
            # during the initial connecting window, or we'd pass an unchecked binding.
            self._finish_current("hw_only")
        elif t.hw_seen and self.baseline is not None and not self.fail_timer.isActive():
            # Only start the sim's fail clock once we have a baseline to compare
            # against — otherwise a fast operator who moves before the first
            # sample lands would be graded before the sim ever had a reference.
            self.fail_timer.start(SIM_FAIL_TIMEOUT_MS)  # sim has this long to react

    def _on_sim_timeout(self) -> None:
        t = self.current()
        if t is None or t.status != "active" or t.sim_seen:
            return
        # Hardware moved but the sim never reacted. Only call that a FAIL if the
        # sim is actually reachable; if the link dropped, grade hardware-only.
        self._finish_current("hw_only" if self.sim_settled_offline else "failed")

    def _restart(self) -> None:
        self.fail_timer.stop()
        self.advance_timer.stop()
        for t in self.tests:
            t.status, t.hw_seen, t.sim_seen = "pending", False, False
        self.idx = -1
        for row in range(len(self.tests)):
            self._paint_row(row)
        self._advance()

    def _show_summary(self) -> None:
        passed = sum(1 for t in self.tests if t.status in ("passed", "hw_only"))
        failed = [t.control for t in self.tests if t.status == "failed"]
        self.instruction.setText(f"Done — {passed}/{len(self.tests)} verified.")
        self.sub.setText(
            ("Failed (hardware works, sim did not react — rebind these in MSFS or re-run "
             f"Write to MSFS): {', '.join(failed)}" if failed else
             "Every tested control reached the sim. This profile is good to fly.")
        )
        self.sim.set_watch(set())

    # ------------------------------------------------------------- channels
    def _on_button(self, device_id: str, index: int, pressed: bool) -> None:
        t = self.current()
        if t is None or device_id != self.device_id or not pressed:
            return
        if self.input_map.control_for_button(index) == t.control_id:
            t.hw_seen = True
            self._paint_row(self.idx)
            self._maybe_pass()

    def _on_axis(self, device_id: str, index: int, value: float) -> None:
        t = self.current()
        if t is None or device_id != self.device_id:
            return
        if self.input_map.control_for_axis(index) == t.control_id:
            t.hw_seen = True
            self._paint_row(self.idx)
            self._maybe_pass()

    # -------- always-on raw readout (independent of the current test) --------
    def _on_raw_axis(self, device_id: str, index: int, value: float) -> None:
        if device_id != self.device_id:
            return
        mapped = self.input_map.control_for_axis(index)
        who = f" → {mapped}" if mapped else " (unmapped — use Learn)"
        self.raw.setText(f"input seen:  axis {index} = {value:+.2f}{who}")

    def _on_raw_button(self, device_id: str, index: int, pressed: bool) -> None:
        if device_id != self.device_id or not pressed:
            return
        mapped = self.input_map.control_for_button(index)
        who = f" → {mapped}" if mapped else " (unmapped — use Learn)"
        self.raw.setText(f"input seen:  button {index}{who}")

    def _update_simchip(self) -> None:
        if self.sim_live:
            self.simchip.setText("● Sim: LIVE — checking the binding actually reaches MSFS")
            self.simchip.setStyleSheet(f"color: {theme.GREEN}; font-size: 11px;")
        elif self.sim_settled_offline:
            self.simchip.setText("● Sim: offline — hardware-only check (start MSFS + load a flight for the full test)")
            self.simchip.setStyleSheet(f"color: {theme.AMBER}; font-size: 11px;")
        else:
            self.simchip.setText("● Sim: connecting…")
            self.simchip.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")

    def _on_sim_state(self, state: str) -> None:
        self.sim_live = state == STATE_LIVE
        if state == STATE_OFFLINE:
            self.sim_settled_offline = True   # a connect attempt has concluded
        elif state == STATE_LIVE:
            self.sim_settled_offline = False  # link recovered
        self._update_simchip()
        t = self.current()
        if t is not None:
            self.sub.setText(
                f"{t.assignment} — {t.spec.hint or 'move it now'}. Watching {t.spec.var}."
                + ("" if self.sim_live else "  (sim offline: hardware-only check)")
            )

    def _on_sim_values(self, values: dict) -> None:
        t = self.current()
        if t is None or t.status != "active":
            return
        raw = values.get(t.spec.var)
        if raw is None or isinstance(raw, dict):
            return
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return
        if self.baseline is None:
            self.baseline = v
            # Hardware may already have been operated; now that a baseline
            # exists, let _maybe_pass start the sim fail clock.
            self._maybe_pass()
            return
        if abs(v - self.baseline) >= t.spec.threshold:
            t.sim_seen = True
            self._paint_row(self.idx)
            self._maybe_pass()

    # ---------------------------------------------------------------- paint
    def _paint_row(self, row: int) -> None:
        t = self.tests[row]
        hw = "✓" if t.hw_seen else "·"
        sim = "✓" if t.sim_seen else "·"
        self.table.item(row, 2).setText(f"{hw} / {sim}")
        label, color = STATUS_LABELS[t.status]
        result = self.table.item(row, 3)
        result.setText(label)
        result.setForeground(QColor(color))

    # ------------------------------------------------------------- teardown
    def done(self, result: int) -> None:  # noqa: N802
        for sig, slot in (
            (self.monitor.button_changed, self._on_button),
            (self.monitor.axis_changed, self._on_axis),
            (self.monitor.button_changed, self._on_raw_button),
            (self.monitor.axis_changed, self._on_raw_axis),
        ):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass
        self.sim.stop()
        self.sim.wait(2000)
        super().done(result)
