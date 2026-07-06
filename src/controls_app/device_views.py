"""Custom-painted device visualizers.

Each supported device gets a stylized top-down diagram. Elements light up
live as the physical hardware is pressed/moved (driven by InputMonitor), axes
render as filled gauges, and in Learn mode clicking an element selects it so
the next physical input gets mapped to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from checklist_app import theme

VIRTUAL_W, VIRTUAL_H = 1000.0, 460.0
PULSE_MS = 280


@dataclass
class Element:
    id: str
    label: str
    kind: str                    # button | round | switch | gauge_v | gauge_h | wheel | rotary | hat | slider_h | big
    rect: tuple[float, float, float, float]
    interactive: bool = True


@dataclass
class Decor:
    rect: tuple[float, float, float, float]
    radius: float = 18.0


class DeviceView(QWidget):
    element_clicked = pyqtSignal(str)

    def __init__(self, device_id: str, elements: list[Element], decor: list[Decor] | None = None):
        super().__init__()
        self.device_id = device_id
        self.elements = elements
        self.decor = decor or []
        self.pressed: dict[str, bool] = {}
        self.values: dict[str, float] = {}       # -1..1
        self.selected: str | None = None
        self.learn_mode = False
        self._pulse_seq: dict[str, int] = {}
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ------------------------------------------------------------- state
    def set_pressed(self, control_id: str, on: bool) -> None:
        self.pressed[control_id] = on
        self.update()

    def pulse(self, control_id: str) -> None:
        """Light an element briefly (trim clicks, hat taps, key presses)."""
        self._pulse_seq[control_id] = self._pulse_seq.get(control_id, 0) + 1
        seq = self._pulse_seq[control_id]
        self.pressed[control_id] = True
        self.update()

        def clear():
            if self._pulse_seq.get(control_id) == seq:
                self.pressed[control_id] = False
                self.update()

        QTimer.singleShot(PULSE_MS, clear)

    def set_value(self, control_id: str, value: float) -> None:
        self.values[control_id] = max(-1.0, min(1.0, value))
        self.update()

    def set_selected(self, control_id: str | None) -> None:
        self.selected = control_id
        self.update()

    # ------------------------------------------------------------ events
    def _transform(self) -> tuple[float, float, float]:
        scale = min(self.width() / VIRTUAL_W, self.height() / VIRTUAL_H)
        ox = (self.width() - VIRTUAL_W * scale) / 2
        oy = (self.height() - VIRTUAL_H * scale) / 2
        return scale, ox, oy

    def mousePressEvent(self, event):  # noqa: N802
        scale, ox, oy = self._transform()
        vx = (event.position().x() - ox) / scale
        vy = (event.position().y() - oy) / scale
        for el in self.elements:
            x, y, w, h = el.rect
            if el.interactive and x - 6 <= vx <= x + w + 6 and y - 6 <= vy <= y + h + 6:
                self.element_clicked.emit(el.id)
                return
        super().mousePressEvent(event)

    # ---------------------------------------------------------- painting
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, ox, oy = self._transform()

        def R(rect: tuple[float, float, float, float]) -> QRectF:
            x, y, w, h = rect
            return QRectF(ox + x * scale, oy + y * scale, w * scale, h * scale)

        # device silhouette
        for d in self.decor:
            p.setPen(QPen(QColor(theme.BORDER), 1))
            p.setBrush(QColor(theme.PANEL))
            p.drawRoundedRect(R(d.rect), d.radius * scale, d.radius * scale)

        label_font = QFont(self.font())
        label_font.setPointSizeF(max(6.0, 7.5 * scale * 2.2))

        for el in self.elements:
            rect = R(el.rect)
            on = self.pressed.get(el.id, False)
            value = self.values.get(el.id)
            accent = QColor(theme.ACCENT)
            base = QColor(theme.PANEL_ALT)
            border = QColor(theme.BORDER)

            if on:
                glow = QColor(theme.ACCENT)
                glow.setAlpha(60)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(glow)
                p.drawRoundedRect(rect.adjusted(-5, -5, 5, 5), 8, 8)

            pen = QPen(accent if on else border, 2 if on else 1.2)
            if self.learn_mode and self.selected == el.id:
                pen = QPen(QColor(theme.AMBER), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)

            if el.kind in ("gauge_v", "wheel"):
                p.setBrush(base)
                p.drawRoundedRect(rect, 6, 6)
                if value is not None and el.kind == "gauge_v":
                    frac = (value + 1) / 2
                    fill_h = rect.height() * frac
                    fill = QRectF(rect.x() + 2, rect.bottom() - fill_h, rect.width() - 4, fill_h)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(accent if not on else QColor(theme.GREEN))
                    p.drawRoundedRect(fill, 4, 4)
                if el.kind == "wheel":
                    p.setPen(QPen(border, 1))
                    step = rect.height() / 7
                    for i in range(1, 7):
                        y = rect.y() + i * step
                        p.drawLine(int(rect.x() + 3), int(y), int(rect.right() - 3), int(y))
            elif el.kind in ("gauge_h", "slider_h"):
                p.setBrush(base)
                p.drawRoundedRect(rect, 6, 6)
                if value is not None:
                    frac = (value + 1) / 2
                    if el.kind == "slider_h":
                        # centered marker (rudder)
                        mx = rect.x() + frac * rect.width()
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(accent)
                        p.drawRoundedRect(QRectF(mx - 5, rect.y() + 2, 10, rect.height() - 4), 3, 3)
                    else:
                        fill = QRectF(rect.x() + 2, rect.y() + 2, (rect.width() - 4) * frac, rect.height() - 4)
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(accent)
                        p.drawRoundedRect(fill, 3, 3)
            elif el.kind in ("round", "rotary", "hat"):
                p.setBrush(QColor(theme.ROW_HOVER) if on else base)
                p.drawEllipse(rect)
                if el.kind == "rotary":
                    center = rect.center()
                    p.drawLine(center.toPoint(), QRectF(rect.x(), rect.y(), rect.width(), rect.height() * 0.25).center().toPoint())
                if el.kind == "hat":
                    p.setBrush(border)
                    p.setPen(Qt.PenStyle.NoPen)
                    c = rect.center()
                    r = rect.width() * 0.32
                    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                        p.drawEllipse(QRectF(c.x() + dx * r - 2, c.y() + dy * r - 2, 4, 4))
            elif el.kind == "switch":
                p.setBrush(QColor(theme.ROW_HOVER) if on else base)
                p.drawRoundedRect(rect, 4, 4)
                nub_h = rect.height() * 0.42
                nub = QRectF(rect.x() + 2, rect.y() + 2 if on else rect.bottom() - nub_h - 2,
                             rect.width() - 4, nub_h)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(accent if on else QColor(theme.TEXT_FAINT))
                p.drawRoundedRect(nub, 3, 3)
            else:  # button / big
                p.setBrush(QColor(theme.ROW_HOVER) if on else base)
                p.drawRoundedRect(rect, 7, 7)

            # label
            p.setFont(label_font)
            p.setPen(QColor(theme.ACCENT if on else theme.TEXT_DIM))
            label_rect = QRectF(rect.x() - 30 * scale, rect.bottom() + 3, rect.width() + 60 * scale, 15 * scale * 2.2)
            p.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, el.label)


# --------------------------------------------------------------------------
# Layouts (virtual 1000 x 460 canvas)
# --------------------------------------------------------------------------

def _bravo() -> tuple[list[Element], list[Decor]]:
    elements = [
        Element("ap_hdg", "HDG", "button", (250, 34, 58, 42)),
        Element("ap_nav", "NAV", "button", (318, 34, 58, 42)),
        Element("ap_apr", "APR", "button", (386, 34, 58, 42)),
        Element("ap_rev", "REV", "button", (454, 34, 58, 42)),
        Element("ap_alt", "ALT", "button", (522, 34, 58, 42)),
        Element("ap_vs", "VS", "button", (590, 34, 58, 42)),
        Element("ap_ias", "IAS", "button", (658, 34, 58, 42)),
        Element("ap_master", "AP", "button", (726, 34, 66, 42)),
        Element("ap_selector", "SELECT", "rotary", (40, 130, 84, 84)),
        Element("ap_knob", "INC/DEC", "rotary", (52, 268, 62, 62)),
        Element("trim_wheel", "TRIM", "wheel", (156, 120, 40, 220)),
        Element("go_around", "GA", "round", (204, 62, 30, 30)),
        Element("lever1", "1 THR", "gauge_v", (250, 160, 56, 200)),
        Element("lever2", "2 PROP", "gauge_v", (330, 160, 56, 200)),
        Element("lever3", "3 MIX", "gauge_v", (410, 160, 56, 200)),
        Element("lever4", "4", "gauge_v", (490, 160, 56, 200)),
        Element("flaps", "FLAPS", "gauge_v", (612, 150, 42, 170)),
        Element("gear", "GEAR", "gauge_v", (890, 130, 42, 130)),
        Element("sw1", "SW1", "switch", (250, 396, 36, 40)),
        Element("sw2", "SW2", "switch", (306, 396, 36, 40)),
        Element("sw3", "SW3", "switch", (362, 396, 36, 40)),
        Element("sw4", "SW4", "switch", (418, 396, 36, 40)),
        Element("sw5", "SW5", "switch", (474, 396, 36, 40)),
        Element("sw6", "SW6", "switch", (530, 396, 36, 40)),
        Element("sw7", "SW7", "switch", (586, 396, 36, 40)),
    ]
    decor = [Decor((16, 12, 968, 436), 22)]
    return elements, decor


def _alpha() -> tuple[list[Element], list[Decor]]:
    elements = [
        Element("elevator", "PITCH", "gauge_v", (46, 90, 22, 180)),
        Element("aileron", "ROLL", "gauge_h", (392, 34, 216, 20)),
        Element("hat", "HAT", "hat", (196, 112, 52, 52)),
        Element("ap_disc", "AP DISC", "round", (140, 158, 34, 34)),
        Element("wheel_l", "BTNS L", "button", (268, 156, 40, 30)),
        Element("rocker_r", "TRIM", "switch", (812, 112, 28, 52)),
        Element("wheel_r", "BTNS R", "button", (700, 156, 40, 30)),
        Element("sw_bat", "BAT", "switch", (172, 322, 34, 52)),
        Element("sw_alt", "ALT", "switch", (238, 322, 34, 52)),
        Element("sw_avionics1", "AVI 1", "switch", (304, 322, 34, 52)),
        Element("sw_avionics2", "AVI 2", "switch", (370, 322, 34, 52)),
        Element("sw_light_bcn", "BCN", "switch", (462, 322, 34, 52)),
        Element("sw_light_land", "LAND", "switch", (528, 322, 34, 52)),
        Element("sw_light_taxi", "TAXI", "switch", (594, 322, 34, 52)),
        Element("sw_light_nav", "NAV", "switch", (660, 322, 34, 52)),
        Element("sw_light_strobe", "STRB", "switch", (726, 322, 34, 52)),
        Element("magneto", "MAGS", "rotary", (806, 314, 78, 78)),
    ]
    decor = [
        Decor((120, 92, 210, 118), 40),   # left horn
        Decor((672, 92, 210, 118), 40),   # right horn
        Decor((330, 120, 342, 66), 14),   # crossbar
        Decor((140, 296, 760, 128), 16),  # switch base
    ]
    return elements, decor


def _rudder() -> tuple[list[Element], list[Decor]]:
    elements = [
        Element("brake_left", "LEFT TOE BRAKE", "gauge_v", (300, 60, 120, 240)),
        Element("brake_right", "RIGHT TOE BRAKE", "gauge_v", (580, 60, 120, 240)),
        Element("rudder", "RUDDER", "slider_h", (250, 372, 500, 30)),
    ]
    decor = [Decor((272, 40, 176, 290), 24), Decor((552, 40, 176, 290), 24)]
    return elements, decor


def _keyboard_mouse() -> tuple[list[Element], list[Decor]]:
    elements = [
        Element("keys", "KEYBOARD — press any key while this window is focused", "big", (150, 110, 500, 220)),
        Element("mouse", "MOUSE", "big", (760, 130, 100, 170)),
    ]
    return elements, []


def build_views() -> dict[str, DeviceView]:
    return {
        "honeycomb_bravo": DeviceView("honeycomb_bravo", *_bravo()),
        "honeycomb_alpha": DeviceView("honeycomb_alpha", *_alpha()),
        "velocityone_rudder": DeviceView("velocityone_rudder", *_rudder()),
        "keyboard_mouse": DeviceView("keyboard_mouse", *_keyboard_mouse()),
    }
