"""Post-flight debrief window: local stats immediately, Claude on request."""

from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from . import theme
from .debrief import DebriefUnavailable, generate_debrief
from .flight_log import FLIGHTS_DIR, FlightRecorder


class DebriefWorker(QThread):
    finished_text = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, summary: dict):
        super().__init__()
        self.summary = summary

    def run(self):
        try:
            self.finished_text.emit(generate_debrief(self.summary))
        except DebriefUnavailable as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Debrief error: {exc}")


def _local_stats_markdown(summary: dict) -> str:
    """The offline part: raw numbers, no judgement."""
    lines = [
        f"# Flight log — {summary['aircraft'] or 'unknown aircraft'}",
        "",
        f"**Duration:** {summary['duration_min']} min &nbsp;·&nbsp; "
        f"**Takeoffs:** {len(summary['takeoffs'])} &nbsp;·&nbsp; "
        f"**Landings:** {len(summary['touchdowns'])}",
        "",
    ]
    for takeoff in summary["takeoffs"]:
        lines.append(f"- Takeoff at {takeoff['t']/60:.1f} min — rotation {takeoff.get('rotation_ias')} KIAS, "
                     f"flaps index {takeoff.get('flaps_index')}")
    for touchdown in summary["touchdowns"]:
        lines.append(f"- Touchdown at {touchdown['t']/60:.1f} min — {touchdown.get('ias')} KIAS, "
                     f"{touchdown.get('fpm')} fpm")
    if summary["max_ias"] is not None:
        lines.append(f"- Max IAS {summary['max_ias']} KIAS · max altitude {summary['max_alt']} ft")
    if summary["exceedances"]:
        for kind, data in summary["exceedances"].items():
            lines.append(f"- ⚠ **{kind}** for {data['seconds']} s (max {data['max_ias']} KIAS)")
    else:
        lines.append("- No V-speed limit exceedances recorded ✓")
    lines += [
        "",
        f"**Checklists:** {len(summary['checklist_sections_completed'])} completed — "
        + (", ".join(summary["checklist_sections_completed"]) or "none"),
        f"**Items done:** {summary['checklist_items_done']} "
        f"({summary['checklist_items_sim_verified']} verified live by the sim)",
        "",
        "---",
        "*Press “✦ Instructor debrief” for the full analysis.*",
    ]
    return "\n".join(lines)


class DebriefDialog(QDialog):
    def __init__(self, parent, recorder: FlightRecorder):
        super().__init__(parent)
        self.recorder = recorder
        self.summary = recorder.summary()
        self.worker: DebriefWorker | None = None
        self.debrief_md: str | None = None

        self.setWindowTitle("Post-flight debrief")
        self.resize(680, 720)

        lay = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setMarkdown(_local_stats_markdown(self.summary))
        lay.addWidget(self.view, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(34)
        self.status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.gen_btn = QPushButton("✦ Instructor debrief")
        self.gen_btn.setMinimumWidth(180)
        self.gen_btn.clicked.connect(self._generate)
        row.addWidget(self.gen_btn)
        save_btn = QPushButton("Save flight + debrief")
        save_btn.clicked.connect(self._save)
        row.addWidget(save_btn)
        row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)

        if not recorder.has_data:
            self.gen_btn.setEnabled(False)
            self.status.setText("No flight data yet — fly with the sim link live, then come back.")

    def _generate(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("✦ Thinking…")
        self.status.setText("Asking your instructor to review the flight…")
        self.worker = DebriefWorker(self.summary)
        self.worker.finished_text.connect(self._on_debrief)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_debrief(self, text: str) -> None:
        self.debrief_md = text
        self.view.setMarkdown(text)
        self.status.setText("Debrief ready. Save it if you want to keep it.")
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("✦ Instructor debrief")

    def _on_failed(self, message: str) -> None:
        self.status.setText(message)
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("✦ Instructor debrief")

    def _save(self) -> None:
        path = self.recorder.save()
        saved = [str(path)]
        if self.debrief_md:
            md_path = Path(str(path).replace(".json", ".md"))
            md_path.write_text(self.debrief_md, encoding="utf-8")
            saved.append(str(md_path))
        self.status.setText("Saved: " + "  ·  ".join(saved))
