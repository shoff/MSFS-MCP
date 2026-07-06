"""Post-flight debrief window: stat tiles + flight profile chart + report card.

Local visuals render instantly and offline; Claude fills in the graded report
card and coaching. Chart follows the house dataviz rules: no dual axes (two
stacked panels share the time axis), thin marks, recessive grid, status color
never used alone (always paired with text).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .debrief import DebriefUnavailable, debrief_to_markdown, generate_debrief
from .flight_log import FlightRecorder


class DebriefWorker(QThread):
    finished_data = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, summary: dict):
        super().__init__()
        self.summary = summary

    def run(self):
        try:
            self.finished_data.emit(generate_debrief(self.summary))
        except DebriefUnavailable as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Debrief error: {exc}")


# --------------------------------------------------------------------------
# Stat tiles (hero numbers with status color + explanatory caption)
# --------------------------------------------------------------------------

def _rate_touchdown(fpm) -> tuple[str, str]:
    rate = abs(fpm)
    if rate < 200:
        return theme.GREEN, "smooth"
    if rate <= 400:
        return theme.AMBER, "firm"
    return theme.RED, "hard"


def build_tiles(summary: dict) -> list[tuple[str, str, str, str]]:
    """(label, value, caption, value_color) — caption always names the judgement."""
    limits = summary.get("limits", {})
    tiles = [("FLIGHT TIME", f"{summary['duration_min']:g} min",
              f"{len(summary['takeoffs'])} takeoff · {len(summary['touchdowns'])} landing", theme.TEXT)]

    if summary["takeoffs"]:
        rotation = summary["takeoffs"][0].get("rotation_ias")
        vr = limits.get("vr")
        if rotation is not None:
            color, note = theme.TEXT, ""
            if vr:
                delta = rotation - vr
                color = theme.GREEN if abs(delta) <= 5 else theme.AMBER if abs(delta) <= 12 else theme.RED
                note = f"target Vr {vr:g} ({delta:+g})"
            tiles.append(("ROTATION", f"{rotation:g} kt", note or "rotation speed", color))

    if summary["touchdowns"]:
        fpm = summary["touchdowns"][0].get("fpm")
        if fpm is not None:
            color, word = _rate_touchdown(fpm)
            tiles.append(("TOUCHDOWN", f"{fpm:+g} fpm", word, color))

    if summary["max_ias"] is not None:
        vno = limits.get("vno")
        color = theme.TEXT
        note = "max speed"
        if vno:
            color = theme.GREEN if summary["max_ias"] <= vno else theme.RED
            note = f"Vno {vno:g}" + ("" if summary["max_ias"] <= vno else " exceeded")
        tiles.append(("MAX IAS", f"{summary['max_ias']:g} kt", note, color))

    n_exceed = sum(e["seconds"] for e in summary["exceedances"].values())
    tiles.append(("LIMITS", "clean ✓" if not n_exceed else f"{n_exceed}s over",
                  "no exceedances" if not n_exceed else " · ".join(summary["exceedances"]),
                  theme.GREEN if not n_exceed else theme.RED))

    done = summary["checklist_items_done"]
    sim = summary["checklist_items_sim_verified"]
    pct = round(100 * sim / done) if done else 0
    tiles.append(("CHECKLISTS", str(len(summary["checklist_sections_completed"])),
                  f"{done} items · {pct}% sim-verified", theme.ACCENT))
    return tiles[:6]


def _tiles_widget(tiles) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for label, value, caption, color in tiles:
        tile = QFrame(objectName="Tile")
        tile.setStyleSheet(
            f"QFrame#Tile {{ background: {theme.PANEL_ALT}; border: 1px solid {theme.BORDER};"
            "border-radius: 8px; }"
        )
        tl = QVBoxLayout(tile)
        tl.setContentsMargins(10, 8, 10, 8)
        tl.setSpacing(1)
        head = QLabel(label)
        head.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 9px; letter-spacing: 1px; border: none;")
        val = QLabel(value)
        val.setStyleSheet(f"color: {color}; font-size: 17px; font-weight: 700; border: none;")
        cap = QLabel(caption)
        cap.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 9px; border: none;")
        for w in (head, val, cap):
            tl.addWidget(w)
        lay.addWidget(tile, 1)
    return row


# --------------------------------------------------------------------------
# Flight profile chart — two stacked panels, shared time axis
# --------------------------------------------------------------------------

class FlightProfileChart(QWidget):
    def __init__(self, samples: list[dict], limits: dict, events: list[dict]):
        super().__init__()
        self.samples = [s for s in samples if s.get("alt") is not None and s.get("t") is not None]
        self.limits = limits
        self.events = events
        self.setMinimumHeight(300)

    def _exceeds(self, s: dict) -> bool:
        ias, flaps = s.get("ias"), s.get("flaps") or 0
        if ias is None:
            return False
        if "vne" in self.limits and ias > self.limits["vne"]:
            return True
        if "vno" in self.limits and ias > self.limits["vno"]:
            return True
        return "vfe" in self.limits and flaps > 0.5 and ias > self.limits["vfe"]

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = QFont(self.font()); small.setPointSizeF(7.5)
        title_font = QFont(self.font()); title_font.setPointSizeF(8.0); title_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, 1.2)

        if len(self.samples) < 2:
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No telemetry recorded — fly with the sim link live.")
            return

        ml, mr, mt, mb, gap = 58, 14, 20, 20, 34
        w = self.width() - ml - mr
        panel_h = (self.height() - mt - mb - gap) / 2
        tmax = max(s["t"] for s in self.samples) or 1.0

        def x_at(t): return ml + (t / tmax) * w

        def draw_panel(top: float, title: str, ymax: float, ylabel_fmt):
            p.setFont(title_font)
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(int(ml), int(top - 6), title)
            for frac in (0.0, 0.5, 1.0):  # recessive grid
                y = top + panel_h - frac * panel_h
                p.setPen(QPen(QColor(theme.BORDER), 1))
                p.drawLine(int(ml), int(y), int(ml + w), int(y))
                p.setFont(small)
                p.setPen(QColor(theme.TEXT_FAINT))
                p.drawText(0, int(y - 8), ml - 8, 16,
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           ylabel_fmt(frac * ymax))
            return lambda v: top + panel_h - (max(0.0, min(v, ymax)) / ymax) * panel_h

        # -- Panel A: altitude
        alts = [s["alt"] for s in self.samples]
        amax = max(alts) * 1.06 or 1
        y_alt = draw_panel(mt, "ALTITUDE (FT)", amax, lambda v: f"{v:,.0f}")
        pts = [QPointF(x_at(s["t"]), y_alt(s["alt"])) for s in self.samples]
        area = QPolygonF([QPointF(pts[0].x(), mt + panel_h)] + pts + [QPointF(pts[-1].x(), mt + panel_h)])
        fill = QColor(theme.ACCENT); fill.setAlpha(36)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(fill); p.drawPolygon(area)
        p.setPen(QPen(QColor(theme.ACCENT), 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF(pts))

        # event markers on the altitude panel
        p.setFont(small)
        for e in self.events:
            if e["event"] == "takeoff":
                x = x_at(e["t"])
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(theme.GREEN))
                p.drawPolygon(QPolygonF([QPointF(x, mt + panel_h - 8), QPointF(x - 5, mt + panel_h), QPointF(x + 5, mt + panel_h)]))
                p.setPen(QColor(theme.TEXT_DIM))
                rot = e.get("rotation_ias")
                p.drawText(int(x + 6), int(mt + panel_h - 4), f"TO {rot:g} kt" if rot else "TO")
            elif e["event"] == "touchdown":
                x = x_at(e["t"])
                fpm = e.get("fpm")
                color = _rate_touchdown(fpm)[0] if fpm is not None else theme.TEXT_DIM
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(color))
                p.drawPolygon(QPolygonF([QPointF(x, mt + panel_h), QPointF(x - 5, mt + panel_h - 8), QPointF(x + 5, mt + panel_h - 8)]))
                p.setPen(QColor(theme.TEXT_DIM))
                label = f"TD {fpm:+g} fpm" if fpm is not None else "TD"
                p.drawText(int(x - 70), int(mt + panel_h - 12), label)

        # -- Panel B: airspeed
        top_b = mt + panel_h + gap
        ias_vals = [s["ias"] for s in self.samples if s.get("ias") is not None]
        smax = max(ias_vals + [self.limits.get("vfe", 0) + 10]) * 1.12 or 1
        y_ias = draw_panel(top_b, "AIRSPEED (KIAS)", smax, lambda v: f"{v:,.0f}")

        # limit reference lines with direct labels
        for key, label in (("vfe", "Vfe"), ("vno", "Vno"), ("vne", "Vne")):
            if key in self.limits and self.limits[key] < smax:
                y = y_ias(self.limits[key])
                pen = QPen(QColor(theme.TEXT_FAINT), 1, Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.drawLine(int(ml), int(y), int(ml + w), int(y))
                p.setPen(QColor(theme.TEXT_FAINT))
                p.drawText(int(ml + w - 52), int(y - 3), f"{label} {self.limits[key]:g}")

        # IAS line, red where over a limit (plus text caption so red is not alone)
        any_exceed = False
        for a, b in zip(self.samples, self.samples[1:]):
            if a.get("ias") is None or b.get("ias") is None:
                continue
            over = self._exceeds(a) or self._exceeds(b)
            any_exceed = any_exceed or over
            p.setPen(QPen(QColor(theme.RED if over else theme.ACCENT), 2))
            p.drawLine(QPointF(x_at(a["t"]), y_ias(a["ias"])), QPointF(x_at(b["t"]), y_ias(b["ias"])))
        if any_exceed:
            p.setFont(small)
            p.setPen(QColor(theme.RED))
            p.drawText(int(ml + w - 208), int(top_b + 12), "⚠ red segments: above a V-speed limit")

        # shared x axis (minutes)
        p.setFont(small)
        p.setPen(QColor(theme.TEXT_FAINT))
        for frac in (0, 0.25, 0.5, 0.75, 1.0):
            t = frac * tmax
            p.drawText(int(x_at(t) - 14), int(self.height() - 4), f"{t/60:.0f}m")


# --------------------------------------------------------------------------
# Report card HTML
# --------------------------------------------------------------------------

def _score_color(score: int) -> str:
    return theme.GREEN if score >= 4 else theme.AMBER if score == 3 else theme.RED


def debrief_html(data: dict) -> str:
    rows = []
    for grade in data["grades"]:
        color = _score_color(grade["score"])
        filled = grade["score"] * 40
        rows.append(
            f"<tr><td style='color:{theme.TEXT}' width='190'>{grade['area']}</td>"
            f"<td width='210'><table cellspacing='0' cellpadding='0'><tr>"
            f"<td bgcolor='{color}' width='{filled}' height='9'></td>"
            f"<td bgcolor='{theme.BORDER}' width='{200 - filled}' height='9'></td>"
            f"</tr></table></td>"
            f"<td style='color:{color}; font-weight:bold'>{grade['score']}/5</td></tr>"
            f"<tr><td colspan='3' style='color:{theme.TEXT_DIM}; font-size:11px'>{grade['comment']}</td></tr>"
            f"<tr><td colspan='3' height='6'></td></tr>"
        )
    grade_table = f"<table cellspacing='0' cellpadding='2'>{''.join(rows)}</table>"

    went_well = "".join(f"<li style='color:{theme.TEXT}'>{w}</li>" for w in data["went_well"])

    work = []
    for i, item in enumerate(data["work_on"], 1):
        work.append(
            f"<table width='100%' cellpadding='8' cellspacing='0' bgcolor='{theme.PANEL}'>"
            f"<tr><td><b style='color:{theme.AMBER}'>{i}. {item['title']}</b><br>"
            f"<span style='color:{theme.TEXT_DIM}'>Evidence:</span> <span style='color:{theme.TEXT}'>{item['evidence']}</span><br>"
            f"<span style='color:{theme.TEXT_DIM}'>Why it matters:</span> <span style='color:{theme.TEXT}'>{item['why']}</span><br>"
            f"<span style='color:{theme.TEXT_DIM}'>The fix:</span> <span style='color:{theme.GREEN}'>{item['fix']}</span>"
            f"</td></tr></table><br>"
        )

    return (
        f"<p style='color:{theme.TEXT}'>{data['overview']}</p>"
        f"<h3 style='color:{theme.TEXT}'>Report card</h3>{grade_table}"
        f"<h3 style='color:{theme.TEXT}'>What went well</h3><ul>{went_well}</ul>"
        f"<h3 style='color:{theme.TEXT}'>What to work on</h3>{''.join(work)}"
        f"<h3 style='color:{theme.TEXT}'>Next flight</h3>"
        f"<p style='color:{theme.ACCENT}'>{data['next_flight']}</p>"
    )


# --------------------------------------------------------------------------
# Dialog
# --------------------------------------------------------------------------

class DebriefDialog(QDialog):
    def __init__(self, parent, recorder: FlightRecorder):
        super().__init__(parent)
        self.recorder = recorder
        self.summary = recorder.summary()
        self.worker: DebriefWorker | None = None
        self.debrief_data: dict | None = None

        self.setWindowTitle(f"Post-flight debrief — {self.summary['aircraft'] or 'flight'}")
        self.resize(780, 880)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(_tiles_widget(build_tiles(self.summary)))

        self.chart = FlightProfileChart(
            recorder.samples, self.summary.get("limits", {}), self.summary.get("events", [])
        )
        lay.addWidget(self.chart)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setHtml(
            f"<p style='color:{theme.TEXT_DIM}'>Press <b style='color:{theme.TEXT}'>✦ Instructor debrief</b> "
            "for the graded report card and coaching based on this flight."
            "</p>"
        )
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
        self.worker.finished_data.connect(self._on_debrief)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_debrief(self, data: dict) -> None:
        self.debrief_data = data
        self.view.setHtml(debrief_html(data))
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
        if self.debrief_data:
            md_path = Path(str(path).replace(".json", ".md"))
            md_path.write_text(debrief_to_markdown(self.debrief_data), encoding="utf-8")
            saved.append(str(md_path))
        self.status.setText("Saved: " + "  ·  ".join(saved))
