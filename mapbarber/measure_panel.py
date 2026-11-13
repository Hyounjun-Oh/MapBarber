"""Floating read-out for ruler measurements: a schematic with per-axis offsets, one tab per measurement."""
import math

from .qt import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
GOLD = QtGui.QColor(255, 209, 38)
AXIS_COLOURS = (QtGui.QColor(242, 82, 64), QtGui.QColor(89, 217, 89), QtGui.QColor(82, 143, 255))
AXIS_LABELS = ("Δx", "Δy", "Δz")
MARGIN = 12


class Schematic(QtWidgets.QWidget):
    """Draws one measurement as its x, y (and z) legs plus the direct line, always fully visible."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(280, 180)
        self.delta = None

    def show_delta(self, delta):
        self.delta = delta
        self.update()

    def _project(self, point):
        x, y, z = point
        if len(self.delta) == 2:
            return x, -y
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        return (x - y) * c, (x + y) * s * 0.6 - z

    def paintEvent(self, _event):
        if self.delta is None:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        delta = list(self.delta) + [0.0] * (3 - len(self.delta))
        corners = [(0.0, 0.0, 0.0)]
        for axis in range(3):
            step = list(corners[-1])
            step[axis] += delta[axis]
            corners.append(tuple(step))
        box = [(delta[0] * i, delta[1] * j, delta[2] * k) for i in (0, 1) for j in (0, 1) for k in (0, 1)]
        flat = [self._project(p) for p in box]
        low_x, high_x = min(p[0] for p in flat), max(p[0] for p in flat)
        low_y, high_y = min(p[1] for p in flat), max(p[1] for p in flat)
        pad_x, pad_y = 34, 24
        scale = min((self.width() - 2 * pad_x) / max(high_x - low_x, 1e-9), (self.height() - 2 * pad_y) / max(high_y - low_y, 1e-9))
        offset_x = (self.width() - (high_x - low_x) * scale) / 2 - low_x * scale
        offset_y = (self.height() - (high_y - low_y) * scale) / 2 - low_y * scale

        def at(point):
            x, y = self._project(point)
            return QtCore.QPointF(x * scale + offset_x, y * scale + offset_y)

        painter.setPen(QtGui.QPen(QtGui.QColor(150, 155, 165, 90), 1, Qt.DotLine))
        for i, a in enumerate(box):
            for b in box[i + 1:]:
                if sum(abs(u - v) > 1e-12 for u, v in zip(a, b)) == 1:
                    painter.drawLine(at(a), at(b))
        font = painter.font()
        font.setPointSizeF(9)
        font.setBold(True)
        painter.setFont(font)
        for axis in range(len(self.delta)):
            if abs(delta[axis]) < 1e-9:
                continue
            start, end = at(corners[axis]), at(corners[axis + 1])
            painter.setPen(QtGui.QPen(AXIS_COLOURS[axis], 3, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(start, end)
            middle = (start + end) / 2
            text = f"{AXIS_LABELS[axis]} {delta[axis]:+.3f}"
            width = painter.fontMetrics().horizontalAdvance(text)
            painter.drawText(QtCore.QPointF(min(max(middle.x() - width / 2, 2), self.width() - width - 2), middle.y() + 14), text)
        painter.setPen(QtGui.QPen(GOLD, 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(at(corners[0]), at(corners[-1]))
        painter.setBrush(GOLD)
        for point in (corners[0], corners[-1]):
            painter.drawEllipse(at(point), 4, 4)
        painter.end()


class MeasureOverlay(QtWidgets.QFrame):
    """Sits in the top-right corner of a view and keeps every measurement until it is closed."""

    def __init__(self, host, describe, on_show, translate):
        super().__init__(host)
        self.host, self.describe, self.on_show, self.translate = host, describe, on_show, translate
        self.entries = []
        self.below = None
        self.setObjectName("measure")
        self.setStyleSheet("QFrame#measure { background-color: rgba(21, 23, 30, 235); border: 1px solid #ffd126; "
                           "border-radius: 8px; } QLabel { color: #f2f4f8; }")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)
        self.tabs = QtWidgets.QTabBar()
        self.tabs.setTabsClosable(True)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setDrawBase(False)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        layout.addWidget(self.tabs)
        self.schematic = Schematic()
        layout.addWidget(self.schematic, 0, Qt.AlignHCenter)
        self.text = QtWidgets.QLabel()
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text.setMinimumWidth(280)
        layout.addWidget(self.text)
        self.hide()
        host.installEventFilter(self)

    def eventFilter(self, target, event):
        if target is self.host and event.type() == QtCore.QEvent.Resize:
            self.place()
        return False

    def place(self):
        self.adjustSize()
        top = MARGIN
        if self.below is not None and self.below.isVisible():
            top = self.below.geometry().bottom() + MARGIN
        self.move(self.host.width() - self.width() - MARGIN, top)
        self.raise_()

    def total(self):
        return sum(entry["d"] for entry in self.entries)

    def add(self, entry):
        """Keep a finished measurement (a dict from ruler.measure plus anything the editor needs to redraw it)."""
        self.entries.append(entry)
        self._rebuild(len(self.entries))

    def clear(self):
        self.entries = []
        self._rebuild(0)

    def refresh(self):
        self._rebuild(self.tabs.currentIndex())

    def _rebuild(self, current):
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        if self.entries:
            self.tabs.addTab("Σ")
            self.tabs.setTabButton(0, QtWidgets.QTabBar.RightSide, None)
            self.tabs.setTabButton(0, QtWidgets.QTabBar.LeftSide, None)
            for number in range(1, len(self.entries) + 1):
                self.tabs.addTab(str(number))
            self.tabs.setCurrentIndex(max(0, min(current, len(self.entries))))
        self.tabs.blockSignals(False)
        self.setVisible(bool(self.entries))
        self._show(self.tabs.currentIndex())

    def _close_tab(self, index):
        if index >= 1:
            del self.entries[index - 1]
            self._rebuild(min(index, len(self.entries)))
            self.on_show(self.current())

    def _tab_changed(self, index):
        self._show(index)
        self.on_show(self.current())

    def current(self):
        index = self.tabs.currentIndex()
        return self.entries[index - 1] if 1 <= index <= len(self.entries) else None

    def _show(self, index):
        if not self.entries:
            return
        entry = self.current()
        self.schematic.setVisible(entry is not None)
        if entry is not None:
            self.schematic.show_delta([entry[key] for key in ("dx", "dy", "dz") if key in entry])
            self.text.setText(self.describe(entry))
        else:
            lines = [f"#{number}   {item['d']:.3f} m" for number, item in enumerate(self.entries, start=1)]
            lines.append(self.translate()("ruler_total", d=self.total(), n=len(self.entries)))
            self.text.setText("\n".join(lines))
        self.place()
