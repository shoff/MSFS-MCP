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

from companion_common import theme

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
        self.switch_dir: dict[str, int] = {}     # control_id -> -1 down / 0 neutral / +1 up
        self.calibrated: set[str] = set()        # controls confirmed calibrated (green border)
        self.selected: str | None = None
        self.learn_mode = False
        self._pulse_seq: dict[str, int] = {}
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ------------------------------------------------------------- state
    def set_pressed(self, control_id: str, on: bool) -> None:
        self.pressed[control_id] = on
        self.update()

    def set_switch(self, control_id: str, direction: int) -> None:
        """Show a two-position switch/rocker's actual position: +1 up, -1 down,
        0 neutral. Distinct from set_pressed so up and down render differently."""
        self.switch_dir[control_id] = direction
        self.pressed[control_id] = direction != 0
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

    def set_calibrated(self, control_id: str, done: bool = True) -> None:
        """Mark a control as successfully calibrated — it gets a green border that
        stays, so you can see your progress across a calibration run."""
        if done:
            self.calibrated.add(control_id)
        else:
            self.calibrated.discard(control_id)
        self.update()

    def clear_calibrated(self) -> None:
        self.calibrated.clear()
        self.update()

    def toggle_switch(self, control_id: str) -> int:
        """Cycle a switch's shown position up -> down -> up (click to sync the
        picture with a maintained physical switch). Returns the new direction."""
        cur = self.switch_dir.get(control_id, 0)
        new = -1 if cur > 0 else 1      # up -> down; neutral/down -> up
        self.set_switch(control_id, new)
        return new

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
            if el.id in self.calibrated:                 # calibrated -> solid green, stays
                pen = QPen(QColor(theme.GREEN), 2)
            if self.learn_mode and self.selected == el.id:   # being calibrated NOW -> amber
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
                direction = self.switch_dir.get(el.id)
                if direction is None:               # legacy on/off: on -> up nub
                    nub_y = rect.y() + 2 if on else rect.bottom() - nub_h - 2
                    lit = on
                elif direction > 0:                 # flipped up
                    nub_y, lit = rect.y() + 2, True
                elif direction < 0:                 # flipped down
                    nub_y, lit = rect.bottom() - nub_h - 2, True
                else:                               # centered / released
                    nub_y, lit = rect.y() + (rect.height() - nub_h) / 2, False
                nub = QRectF(rect.x() + 2, nub_y, rect.width() - 4, nub_h)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(accent if lit else QColor(theme.TEXT_FAINT))
                p.drawRoundedRect(nub, 3, 3)
            elif el.kind == "switch3":
                # 3-position spring-return momentary: rests CENTER, flicks fwd/back.
                p.setBrush(base)
                p.drawRoundedRect(rect, 4, 4)
                mid_y = rect.y() + rect.height() / 2
                # detent marks (top / center / bottom) so all three positions read
                p.setPen(QPen(border, 1))
                for fy in (0.16, 0.5, 0.84):
                    y = rect.y() + rect.height() * fy
                    p.drawLine(int(rect.x() + 4), int(y), int(rect.right() - 4), int(y))
                nub_h = rect.height() * 0.28
                direction = self.switch_dir.get(el.id, 0)   # default NEUTRAL (center)
                if direction > 0:                            # pushed forward (away)
                    nub_y = rect.y() + 2
                elif direction < 0:                          # pulled back (toward you)
                    nub_y = rect.bottom() - nub_h - 2
                else:                                        # spring-centered rest
                    nub_y = mid_y - nub_h / 2
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(accent if direction != 0 else QColor(theme.TEXT_DIM))
                p.drawRoundedRect(QRectF(rect.x() + 2, nub_y, rect.width() - 4, nub_h), 3, 3)
            elif el.kind == "switch3h":
                # 3-position spring-return momentary, HORIZONTAL: rests CENTER,
                # flicks LEFT / RIGHT (Alpha right-grip switches).
                p.setBrush(base)
                p.drawRoundedRect(rect, 4, 4)
                mid_x = rect.x() + rect.width() / 2
                p.setPen(QPen(border, 1))
                for fx in (0.16, 0.5, 0.84):
                    x = rect.x() + rect.width() * fx
                    p.drawLine(int(x), int(rect.y() + 4), int(x), int(rect.bottom() - 4))
                nub_w = rect.width() * 0.28
                direction = self.switch_dir.get(el.id, 0)   # default NEUTRAL (center)
                if direction > 0:                            # flicked right
                    nub_x = rect.right() - nub_w - 2
                elif direction < 0:                          # flicked left
                    nub_x = rect.x() + 2
                else:                                        # spring-centered rest
                    nub_x = mid_x - nub_w / 2
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(accent if direction != 0 else QColor(theme.TEXT_DIM))
                p.drawRoundedRect(QRectF(nub_x, rect.y() + 2, nub_w, rect.height() - 4), 3, 3)
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
        # LEFT grip: hat + white + TWO side-by-side 3-position spring switches + trigger
        Element("hat", "HAT", "hat", (140, 100, 48, 48)),
        Element("left_white", "WHT", "round", (256, 104, 28, 28)),
        Element("left_rocker_l", "RK1", "switch3", (144, 150, 26, 58)),
        Element("left_rocker_r", "RK2", "switch3", (178, 150, 26, 58)),
        Element("left_trigger", "TRIG", "round", (256, 162, 28, 28)),
        # RIGHT grip: TWO stacked 3-position spring switches (push LEFT/RIGHT) + white + red
        Element("right_rocker_top", "RK1", "switch3h", (676, 104, 60, 26)),
        Element("right_rocker_bot", "RK2", "switch3h", (676, 160, 60, 26)),
        Element("right_white", "WHT", "round", (766, 104, 28, 28)),
        Element("right_red", "RED", "round", (766, 160, 28, 28)),
        # Panel order matches the real Alpha: MASTER ALT, MASTER BAT, AVI 1, AVI 2
        Element("sw_alt", "ALT", "switch", (172, 322, 34, 52)),
        Element("sw_bat", "BAT", "switch", (238, 322, 34, 52)),
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


class RawDeviceView(QWidget):
    """Accurate device panel read straight from SDL: one bar per real axis and
    one light per real button, so the count ALWAYS matches the hardware (no
    hardcoded guess). Live-updates as you operate controls; click a button/axis
    to assign it a function. Mapped inputs get a green outline.
    """

    element_clicked = pyqtSignal(str)  # "btn:N" or "axis:N"

    def __init__(self, device_id: str, monitor, label_fn):
        super().__init__()
        self.device_id = device_id
        self.monitor = monitor
        self.label_fn = label_fn          # (kind: str, index: int) -> str | None
        self.axes: dict[int, float] = {}
        self.pressed: set[int] = set()
        self.learn_mode = False           # interface parity with DeviceView
        self._hit: list[tuple[QRectF, str]] = []
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # driven by the monitor with RAW indices
    def set_button(self, index: int, on: bool) -> None:
        (self.pressed.add if on else self.pressed.discard)(index)
        self.update()

    def set_axis(self, index: int, value: float) -> None:
        self.axes[index] = max(-1.0, min(1.0, value))
        self.update()

    def set_selected(self, _control_id) -> None:  # parity no-op
        pass

    def mousePressEvent(self, event):  # noqa: N802
        pos = event.position()
        for rect, key in self._hit:
            if rect.contains(pos):
                self.element_clicked.emit(key)
                return
        super().mousePressEvent(event)

    def paintEvent(self, _event):  # noqa: N802
        naxes, nbuttons, _nhats = self.monitor.caps(self.device_id)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.PANEL_ALT))
        self._hit = []

        if naxes == 0 and nbuttons == 0:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "This device isn’t connected to the app.\n"
                       "Open 🔎 Hardware to detect or assign it, then it appears here.")
            return

        m, W = 16.0, float(self.width())
        y = m
        p.setFont(QFont(self.font().family(), 9))
        bar_h = 22.0
        for i in range(naxes):
            v = self.axes.get(i, 0.0)
            rect = QRectF(m, y, W - 2 * m, bar_h)
            mapped = self.label_fn("axis", i)
            p.setPen(QPen(QColor(theme.GREEN if mapped else theme.BORDER), 1.5))
            p.setBrush(QColor(theme.BG))
            p.drawRoundedRect(rect, 4, 4)
            cx = rect.center().x()
            fill = v * (rect.width() / 2 - 3)
            fr = (QRectF(cx, rect.top() + 3, fill, bar_h - 6) if fill >= 0
                  else QRectF(cx + fill, rect.top() + 3, -fill, bar_h - 6))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(fr, 3, 3)
            p.setPen(QColor(theme.TEXT))
            text = f"Axis {i}" + (f"  →  {mapped}" if mapped else "  (unassigned)") + f"     {v:+.2f}"
            p.drawText(rect.adjusted(8, 0, -8, 0),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
            self._hit.append((rect, f"axis:{i}"))
            y += bar_h + 8

        y += 8
        if nbuttons:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(QRectF(m, y, W - 2 * m, 16), int(Qt.AlignmentFlag.AlignLeft),
                       f"{nbuttons} buttons — press one to light it; click a square to assign it")
            y += 22
        cols = max(8, min(16, int((W - 2 * m) // 46)))
        cell = max(26.0, ((W - 2 * m) - (cols - 1) * 6) / cols)
        for i in range(nbuttons):
            r, c = divmod(i, cols)
            rect = QRectF(m + c * (cell + 6), y + r * (cell + 6), cell, cell)
            lit = i in self.pressed
            mapped = self.label_fn("button", i)
            edge = theme.ACCENT if lit else (theme.GREEN if mapped else theme.BORDER)
            p.setPen(QPen(QColor(edge), 1.5))
            p.setBrush(QColor(theme.ACCENT if lit else theme.PANEL))
            p.drawRoundedRect(rect, 5, 5)
            p.setPen(QColor(theme.INK_ON_BRIGHT if lit else (theme.TEXT if mapped else theme.TEXT_FAINT)))
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), str(i))
            if mapped:
                self.setToolTip("")  # per-cell tooltips are impractical; label via assign menu
            self._hit.append((rect, f"btn:{i}"))
        p.end()
