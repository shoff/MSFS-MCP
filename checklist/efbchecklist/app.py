"""EFB-style electronic checklist for MSFS 2024.

Keyboard-first design so the app can be driven with one hand while flying:

    Space / Enter   check current item and advance
    Backspace       uncheck current item and step back
    Up / Down       move between items
    Left / Right    previous / next checklist
    Ctrl+E          jump to first emergency checklist
    Ctrl+R          reset current checklist
    Ctrl+T          toggle always-on-top
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .models import Aircraft, Checklist, ChecklistItem, loadAllAircraft

SIDEBAR_ROLE_CHECKLIST = Qt.ItemDataRole.UserRole
SIDEBAR_ROLE_VSPEEDS = Qt.ItemDataRole.UserRole + 1


class ItemRow(QWidget):
    """One challenge ... RESPONSE row with a dot leader, like a printed POH card."""

    clicked = pyqtSignal()

    def __init__(self, item: ChecklistItem, emergency: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.item = item
        self.emergency = emergency
        self.current = False
        self.setMinimumHeight(40 if item.note is None else 56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.challengeFont = QFont(self.font())
        self.challengeFont.setPointSize(11)
        self.responseFont = QFont(self.font())
        self.responseFont.setPointSize(11)
        self.responseFont.setBold(True)
        self.noteFont = QFont(self.font())
        self.noteFont.setPointSize(9)
        self.noteFont.setItalic(True)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def setCurrent(self, current: bool) -> None:
        if self.current != current:
            self.current = current
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        if self.current:
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.fillRect(rect, self.palette().base())
            painter.fillRect(rect, self.currentBackground())
            painter.setPen(QPen(self.accentColor(), 3))
            painter.drawLine(rect.left() + 1, rect.top() + 4, rect.left() + 1, rect.bottom() - 4)

        leftPad = 16
        rightPad = 16
        boxSize = 15
        boxY = rect.top() + 12

        # checkbox
        from PyQt6.QtGui import QColor
        boxColor = QColor(theme.GREEN) if self.item.checked else QColor(theme.TEXT_DIM)
        painter.setPen(QPen(boxColor, 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(leftPad, boxY, boxSize, boxSize, 3, 3)
        if self.item.checked:
            painter.setPen(QPen(QColor(theme.GREEN), 2.2))
            painter.drawLine(leftPad + 3, boxY + 8, leftPad + 6, boxY + 11)
            painter.drawLine(leftPad + 6, boxY + 11, leftPad + 12, boxY + 4)

        textLeft = leftPad + boxSize + 12
        baselineY = boxY + boxSize - 3

        checked = self.item.checked
        challengeColor = QColor(theme.TEXT_DIM) if checked else QColor(theme.TEXT)
        responseColor = (
            QColor(theme.GREEN)
            if checked
            else QColor(theme.RED) if self.emergency else QColor(theme.CYAN)
        )

        challengeMetrics = QFontMetrics(self.challengeFont)
        responseMetrics = QFontMetrics(self.responseFont)
        responseWidth = responseMetrics.horizontalAdvance(self.item.response)

        responseX = rect.right() - rightPad - responseWidth
        maxChallengeWidth = responseX - textLeft - 24
        challengeText = challengeMetrics.elidedText(
            self.item.challenge, Qt.TextElideMode.ElideRight, max(40, maxChallengeWidth)
        )
        challengeWidth = challengeMetrics.horizontalAdvance(challengeText)

        painter.setFont(self.challengeFont)
        painter.setPen(challengeColor)
        painter.drawText(textLeft, baselineY, challengeText)

        # dot leader
        leaderStart = textLeft + challengeWidth + 8
        leaderEnd = responseX - 8
        if leaderEnd > leaderStart:
            painter.setPen(QPen(QColor(theme.BORDER), 1, Qt.PenStyle.DotLine))
            painter.drawLine(leaderStart, baselineY - 3, leaderEnd, baselineY - 3)

        painter.setFont(self.responseFont)
        painter.setPen(responseColor)
        painter.drawText(responseX, baselineY, self.item.response)

        if self.item.note:
            painter.setFont(self.noteFont)
            painter.setPen(QColor(theme.AMBER))
            noteMetrics = QFontMetrics(self.noteFont)
            noteText = noteMetrics.elidedText(
                "\u26a0 " + self.item.note, Qt.TextElideMode.ElideRight, rect.width() - textLeft - rightPad
            )
            painter.drawText(textLeft, baselineY + 16, noteText)

    def currentBackground(self):
        from PyQt6.QtGui import QColor
        color = QColor(theme.RED if self.emergency else theme.CYAN)
        color.setAlpha(22)
        return color

    def accentColor(self):
        from PyQt6.QtGui import QColor
        return QColor(theme.RED if self.emergency else theme.CYAN)


class ChecklistView(QWidget):
    """Scrollable list of ItemRows for one checklist, with progress header."""

    progressChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.checklist: Checklist | None = None
        self.rows: list[ItemRow] = []
        self.currentIndex = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 8)
        layout.setSpacing(10)

        headerRow = QHBoxLayout()
        self.titleLabel = QLabel("")
        self.titleLabel.setObjectName("checklistTitle")
        headerRow.addWidget(self.titleLabel)
        headerRow.addStretch()
        self.progressLabel = QLabel("")
        self.progressLabel.setObjectName("progressLabel")
        headerRow.addWidget(self.progressLabel)
        self.resetButton = QPushButton("Reset")
        self.resetButton.setObjectName("resetButton")
        self.resetButton.clicked.connect(self.resetChecklist)
        headerRow.addWidget(self.resetButton)
        layout.addLayout(headerRow)

        self.progressBar = QProgressBar()
        self.progressBar.setTextVisible(False)
        self.progressBar.setFixedHeight(6)
        layout.addWidget(self.progressBar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.itemsHost = QWidget()
        self.itemsLayout = QVBoxLayout(self.itemsHost)
        self.itemsLayout.setContentsMargins(0, 4, 0, 20)
        self.itemsLayout.setSpacing(2)
        self.itemsLayout.addStretch()
        self.scroll.setWidget(self.itemsHost)
        layout.addWidget(self.scroll, 1)

    def setChecklist(self, checklist: Checklist) -> None:
        self.checklist = checklist
        for row in self.rows:
            row.deleteLater()
        self.rows.clear()

        emergency = checklist.kind == "emergency"
        self.titleLabel.setObjectName("checklistTitleEmergency" if emergency else "checklistTitle")
        self.titleLabel.setStyleSheet("")  # force restyle after objectName change
        self.titleLabel.setText(checklist.name.upper())
        self.progressBar.setObjectName("emergencyProgress" if emergency else "")
        self.progressBar.setStyleSheet("")

        for index, item in enumerate(checklist.items):
            row = ItemRow(item, emergency)
            row.clicked.connect(lambda i=index: self.toggleItem(i))
            self.itemsLayout.insertWidget(index, row)
            self.rows.append(row)

        self.currentIndex = checklist.firstUnchecked()
        self.refresh()

    def refresh(self) -> None:
        if self.checklist is None:
            return
        for index, row in enumerate(self.rows):
            row.setCurrent(index == self.currentIndex)
            row.update()
        done, total = self.checklist.done, self.checklist.total
        self.progressBar.setMaximum(max(1, total))
        self.progressBar.setValue(done)
        suffix = "  \u2713 COMPLETE" if self.checklist.complete else ""
        self.progressLabel.setText(f"{done} / {total}{suffix}")
        if 0 <= self.currentIndex < len(self.rows):
            self.scroll.ensureWidgetVisible(self.rows[self.currentIndex], 0, 60)
        self.progressChanged.emit()

    def toggleItem(self, index: int) -> None:
        if self.checklist is None or not (0 <= index < len(self.checklist.items)):
            return
        item = self.checklist.items[index]
        item.checked = not item.checked
        self.currentIndex = index
        if item.checked:
            self.advance()
        self.refresh()

    def checkCurrentAndAdvance(self) -> None:
        if self.checklist is None or not self.checklist.items:
            return
        self.checklist.items[self.currentIndex].checked = True
        self.advance()
        self.refresh()

    def uncheckCurrentAndStepBack(self) -> None:
        if self.checklist is None or not self.checklist.items:
            return
        item = self.checklist.items[self.currentIndex]
        if item.checked:
            item.checked = False
        elif self.currentIndex > 0:
            self.currentIndex -= 1
            self.checklist.items[self.currentIndex].checked = False
        self.refresh()

    def advance(self) -> None:
        if self.checklist is None:
            return
        for index in range(self.currentIndex + 1, self.checklist.total):
            if not self.checklist.items[index].checked:
                self.currentIndex = index
                return
        for index in range(self.checklist.total):
            if not self.checklist.items[index].checked:
                self.currentIndex = index
                return
        self.currentIndex = self.checklist.total - 1

    def moveCurrent(self, delta: int) -> None:
        if self.checklist is None or not self.checklist.items:
            return
        self.currentIndex = max(0, min(self.checklist.total - 1, self.currentIndex + delta))
        self.refresh()

    def resetChecklist(self) -> None:
        if self.checklist is None:
            return
        self.checklist.reset()
        self.currentIndex = 0
        self.refresh()


class VSpeedView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 8)
        layout.setSpacing(10)
        self.titleLabel = QLabel("V-SPEEDS")
        self.titleLabel.setObjectName("checklistTitle")
        layout.addWidget(self.titleLabel)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.host = QWidget()
        self.hostLayout = QVBoxLayout(self.host)
        self.hostLayout.setContentsMargins(0, 4, 0, 20)
        self.hostLayout.setSpacing(0)
        self.scroll.setWidget(self.host)
        layout.addWidget(self.scroll, 1)

    def setAircraft(self, aircraft: Aircraft) -> None:
        while self.hostLayout.count():
            child = self.hostLayout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for vspeed in aircraft.vspeeds:
            row = QLabel(
                f'<table width="100%"><tr>'
                f'<td style="color:{theme.TEXT}; font-size:12px;">{vspeed.label}</td>'
                f'<td align="right" style="color:{theme.CYAN}; font-size:12px; font-weight:700;">{vspeed.value}</td>'
                f"</tr></table>"
            )
            row.setContentsMargins(16, 8, 16, 8)
            self.hostLayout.addWidget(row)
        self.hostLayout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self, fleet: list[Aircraft]):
        super().__init__()
        self.fleet = fleet
        self.aircraft = fleet[0]

        self.setWindowTitle("EFB Checklist \u2014 MSFS 2024")
        self.resize(560, 720)
        self.setMinimumWidth(420)

        root = QWidget()
        root.setObjectName("root")
        rootLayout = QVBoxLayout(root)
        rootLayout.setContentsMargins(0, 0, 0, 0)
        rootLayout.setSpacing(0)
        self.setCentralWidget(root)

        rootLayout.addWidget(self.buildHeader())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(200)
        self.sidebar.currentItemChanged.connect(self.onSidebarChanged)
        body.addWidget(self.sidebar)

        self.checklistView = ChecklistView()
        self.checklistView.progressChanged.connect(self.refreshSidebarLabels)
        self.vspeedView = VSpeedView()
        self.vspeedView.hide()

        contentHost = QVBoxLayout()
        contentHost.setContentsMargins(0, 0, 0, 0)
        contentHost.addWidget(self.checklistView, 1)
        contentHost.addWidget(self.vspeedView, 1)
        body.addLayout(contentHost, 1)

        rootLayout.addLayout(body, 1)
        rootLayout.addWidget(self.buildFooter())

        self.bindShortcuts()
        self.populateAircraftCombo()
        self.loadAircraftIntoUi()
        self.setAlwaysOnTop(True)

    # ---------- construction ----------

    def buildHeader(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        titleBox = QVBoxLayout()
        titleBox.setSpacing(1)
        self.aircraftCombo = QComboBox()
        self.aircraftCombo.currentIndexChanged.connect(self.onAircraftChanged)
        titleBox.addWidget(self.aircraftCombo)
        self.subtitleLabel = QLabel("")
        self.subtitleLabel.setObjectName("subtitle")
        titleBox.addWidget(self.subtitleLabel)
        layout.addLayout(titleBox)
        layout.addStretch()

        self.emergencyButton = QToolButton()
        self.emergencyButton.setObjectName("emergencyButton")
        self.emergencyButton.setText("EMERG")
        self.emergencyButton.setToolTip("Jump to emergency procedures (Ctrl+E)")
        self.emergencyButton.clicked.connect(self.jumpToEmergency)
        layout.addWidget(self.emergencyButton)

        self.pinButton = QToolButton()
        self.pinButton.setText("\U0001f4cc PIN")
        self.pinButton.setCheckable(True)
        self.pinButton.setChecked(True)
        self.pinButton.setToolTip("Always on top (Ctrl+T)")
        self.pinButton.toggled.connect(self.setAlwaysOnTop)
        layout.addWidget(self.pinButton)

        return header

    def buildFooter(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("header")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(14, 6, 14, 6)

        hint = QLabel("Space check \u00b7 Bksp undo \u00b7 \u2190\u2192 lists \u00b7 Ctrl+E emergency \u00b7 Ctrl+R reset")
        hint.setObjectName("footerHint")
        layout.addWidget(hint)
        layout.addStretch()

        opacityLabel = QLabel("Opacity")
        opacityLabel.setObjectName("footerHint")
        layout.addWidget(opacityLabel)
        self.opacitySlider = QSlider(Qt.Orientation.Horizontal)
        self.opacitySlider.setRange(35, 100)
        self.opacitySlider.setValue(100)
        self.opacitySlider.setFixedWidth(90)
        self.opacitySlider.valueChanged.connect(lambda v: self.setWindowOpacity(v / 100))
        layout.addWidget(self.opacitySlider)
        return footer

    def bindShortcuts(self) -> None:
        def bind(sequence: str, handler) -> None:
            QShortcut(QKeySequence(sequence), self, activated=handler)

        bind("Space", self.checklistView.checkCurrentAndAdvance)
        bind("Return", self.checklistView.checkCurrentAndAdvance)
        bind("Backspace", self.checklistView.uncheckCurrentAndStepBack)
        bind("Up", lambda: self.checklistView.moveCurrent(-1))
        bind("Down", lambda: self.checklistView.moveCurrent(1))
        bind("Left", lambda: self.stepChecklist(-1))
        bind("Right", lambda: self.stepChecklist(1))
        bind("Ctrl+E", self.jumpToEmergency)
        bind("Ctrl+R", self.checklistView.resetChecklist)
        bind("Ctrl+T", lambda: self.pinButton.toggle())

    # ---------- population ----------

    def populateAircraftCombo(self) -> None:
        self.aircraftCombo.blockSignals(True)
        self.aircraftCombo.clear()
        for aircraft in self.fleet:
            self.aircraftCombo.addItem(aircraft.name)
        self.aircraftCombo.blockSignals(False)

    def loadAircraftIntoUi(self) -> None:
        self.subtitleLabel.setText(self.aircraft.subtitle)
        self.sidebar.blockSignals(True)
        self.sidebar.clear()

        for group in self.aircraft.groups:
            headerItem = QListWidgetItem(group.name.upper())
            headerItem.setFlags(Qt.ItemFlag.NoItemFlags)
            from PyQt6.QtGui import QColor
            headerItem.setForeground(QColor(theme.RED if group.kind == "emergency" else theme.TEXT_DIM))
            font = headerItem.font()
            font.setPointSize(8)
            font.setBold(True)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
            headerItem.setFont(font)
            self.sidebar.addItem(headerItem)
            for checklist in group.checklists:
                listItem = QListWidgetItem(self.sidebarLabel(checklist))
                listItem.setData(SIDEBAR_ROLE_CHECKLIST, checklist.id)
                if group.kind == "emergency":
                    listItem.setForeground(QColor(theme.RED))
                self.sidebar.addItem(listItem)

        vspeedItem = QListWidgetItem("V-SPEEDS")
        vspeedItem.setData(SIDEBAR_ROLE_VSPEEDS, True)
        from PyQt6.QtGui import QColor
        vspeedItem.setForeground(QColor(theme.CYAN))
        self.sidebar.addItem(vspeedItem)

        self.sidebar.blockSignals(False)
        self.vspeedView.setAircraft(self.aircraft)
        self.selectFirstChecklist()

    def sidebarLabel(self, checklist: Checklist) -> str:
        marker = "\u2713 " if checklist.complete else ""
        return f"{marker}{checklist.name}   ({checklist.done}/{checklist.total})"

    def refreshSidebarLabels(self) -> None:
        for row in range(self.sidebar.count()):
            listItem = self.sidebar.item(row)
            checklistId = listItem.data(SIDEBAR_ROLE_CHECKLIST)
            if checklistId:
                checklist = self.findChecklist(checklistId)
                if checklist:
                    listItem.setText(self.sidebarLabel(checklist))

    def findChecklist(self, checklistId: str) -> Checklist | None:
        for checklist in self.aircraft.allChecklists():
            if checklist.id == checklistId:
                return checklist
        return None

    # ---------- navigation ----------

    def selectFirstChecklist(self) -> None:
        for row in range(self.sidebar.count()):
            if self.sidebar.item(row).data(SIDEBAR_ROLE_CHECKLIST):
                self.sidebar.setCurrentRow(row)
                return

    def onSidebarChanged(self, currentItem: QListWidgetItem | None, previousItem) -> None:
        if currentItem is None:
            return
        if currentItem.data(SIDEBAR_ROLE_VSPEEDS):
            self.checklistView.hide()
            self.vspeedView.show()
            return
        checklistId = currentItem.data(SIDEBAR_ROLE_CHECKLIST)
        checklist = self.findChecklist(checklistId) if checklistId else None
        if checklist:
            self.vspeedView.hide()
            self.checklistView.show()
            self.checklistView.setChecklist(checklist)

    def stepChecklist(self, delta: int) -> None:
        rows = [
            row
            for row in range(self.sidebar.count())
            if self.sidebar.item(row).data(SIDEBAR_ROLE_CHECKLIST)
            or self.sidebar.item(row).data(SIDEBAR_ROLE_VSPEEDS)
        ]
        if not rows:
            return
        currentRow = self.sidebar.currentRow()
        try:
            position = rows.index(currentRow)
        except ValueError:
            position = 0
        newPosition = max(0, min(len(rows) - 1, position + delta))
        self.sidebar.setCurrentRow(rows[newPosition])

    def jumpToEmergency(self) -> None:
        for row in range(self.sidebar.count()):
            checklistId = self.sidebar.item(row).data(SIDEBAR_ROLE_CHECKLIST)
            if checklistId:
                checklist = self.findChecklist(checklistId)
                if checklist and checklist.kind == "emergency":
                    self.sidebar.setCurrentRow(row)
                    return

    def onAircraftChanged(self, index: int) -> None:
        if 0 <= index < len(self.fleet):
            self.aircraft = self.fleet[index]
            self.loadAircraftIntoUi()

    def setAlwaysOnTop(self, onTop: bool) -> None:
        flags = self.windowFlags()
        if onTop:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)
    fleet = loadAllAircraft()
    window = MainWindow(fleet)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
