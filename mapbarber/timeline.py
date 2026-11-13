"""Widgets that sit on the 3D view: the frame range slider for sequences and the labeling status bar."""
from .qt import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
HANDLE = 9
TRACK_MARGIN = 16
ACCENT = QtGui.QColor(79, 156, 247)
LABELED = QtGui.QColor(76, 194, 106)
CHANGED = QtGui.QColor(242, 182, 50)


class FrameRange(QtWidgets.QWidget):
    """A track with one tick per frame and two handles for the first and last frame shown.

    Drag a handle to move one end, or drag the band between them to slide the whole range; `on_range(first,
    last)` is called when the mouse is released. Where the two handles lie on top of each other, the direction
    of the drag picks one: to the right the last frame moves, to the left the first. A click anywhere else on it changes nothing and only gives
    it the keyboard: the left and right arrow keys then slide the range by its own width (with Shift by a
    single frame) through `on_keys(direction, whole)`.
    """

    def __init__(self, on_range, on_keys=None):
        super().__init__()
        self.on_range, self.on_keys, self.on_focus = on_range, on_keys, None
        self.setFocusPolicy(Qt.ClickFocus)
        self.count, self.first, self.last = 1, 0, 0
        self.labeled, self.changed = set(), set()
        self._drag, self._grip, self._pressed = None, 0, 0.0
        self.setMinimumHeight(34)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_count(self, count):
        self.count = max(int(count), 1)
        self.update()

    def set_range(self, first, last):
        self.first, self.last = sorted((int(first), int(last)))
        self.update()

    def set_marks(self, labeled, changed):
        self.labeled, self.changed = set(labeled), set(changed)
        self.update()

    def _x(self, frame):
        span = max(self.width() - 2 * TRACK_MARGIN, 1)
        return TRACK_MARGIN + span * (frame / max(self.count - 1, 1))

    def _frame(self, x):
        span = max(self.width() - 2 * TRACK_MARGIN, 1)
        return int(round(min(max((x - TRACK_MARGIN) / span, 0.0), 1.0) * (self.count - 1)))

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        middle = self.height() / 2
        text = self.palette().color(QtGui.QPalette.WindowText)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor(128, 128, 128, 70))
        painter.drawRoundedRect(QtCore.QRectF(TRACK_MARGIN, middle - 3, self.width() - 2 * TRACK_MARGIN, 6), 3, 3)
        step = max(1, int(self.count / max((self.width() - 2 * TRACK_MARGIN) / 6, 1)))
        for frame in range(0, self.count, step):
            x = self._x(frame)
            colour = CHANGED if frame in self.changed else LABELED if frame in self.labeled else None
            painter.setPen(QtGui.QPen(colour or QtGui.QColor(150, 150, 150, 120), 2 if colour else 1))
            painter.drawLine(QtCore.QPointF(x, middle + 6), QtCore.QPointF(x, middle + (11 if colour else 8)))
        left, right = self._x(self.first), self._x(self.last)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 150))
        painter.drawRoundedRect(QtCore.QRectF(left, middle - 4, max(right - left, 2), 8), 4, 4)
        for x in (left, right):
            painter.setPen(QtGui.QPen(text, 1.5))
            painter.setBrush(ACCENT)
            painter.drawRoundedRect(QtCore.QRectF(x - HANDLE / 2, middle - 10, HANDLE, 20), 3, 3)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()
        if self.on_focus:
            self.on_focus(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()
        if self.on_focus:
            self.on_focus(False)

    def keyPressEvent(self, event):
        direction = {Qt.Key_Left: -1, Qt.Key_Right: 1}.get(event.key())
        if direction is None or self.on_keys is None:
            return super().keyPressEvent(event)
        self.on_keys(direction, not (event.modifiers() & Qt.ShiftModifier))
        event.accept()

    def mousePressEvent(self, event):
        x = event.position().x() if hasattr(event, "position") else event.x()
        left, right = self._x(self.first), self._x(self.last)
        frame = self._frame(x)
        on_left, on_right = abs(x - left) <= HANDLE, abs(x - right) <= HANDLE
        if on_left and on_right:
            self._drag, self._pressed = "either", x
        elif on_left:
            self._drag = "first"
        elif on_right:
            self._drag = "last"
        elif left < x < right:
            self._drag, self._grip = "band", frame - self.first
        else:
            self._drag = None

    def _move(self, frame):
        if self._drag == "first":
            self.first = min(frame, self.last)
        elif self._drag == "last":
            self.last = max(frame, self.first)
        elif self._drag == "band":
            width = self.last - self.first
            self.first = min(max(frame - self._grip, 0), self.count - 1 - width)
            self.last = self.first + width
        self.update()
        self.setToolTip(f"{self.first} – {self.last}")

    def mouseMoveEvent(self, event):
        x = event.position().x() if hasattr(event, "position") else event.x()
        if self._drag == "either":
            if abs(x - self._pressed) < 2:
                return
            self._drag = "last" if x > self._pressed else "first"
        if self._drag:
            self._move(self._frame(x))

    def mouseReleaseEvent(self, _event):
        dragged, self._drag = self._drag, None
        if dragged and dragged != "either":
            self.on_range(self.first, self.last)


class TimelineBar(QtWidgets.QFrame):
    """Bottom strip of a sequence: previous / next, the range slider and what it currently shows.

    A click anywhere on the strip, on the frame numbers as well, gives the slider the keyboard without
    touching the range, so the arrow keys can be used without risking a slip on the slider itself.
    """

    IDLE = "QFrame#timeline { border-top: 1px solid rgba(128, 128, 128, 0.35); }"
    ACTIVE = "QFrame#timeline { border: 1px solid #4f9cf7; background-color: rgba(79, 156, 247, 0.10); }"

    ANCHORS = ("world", "lidar", "object")

    def __init__(self, on_range, on_step, translate, on_keys=None, on_anchor=None):
        super().__init__()
        self.translate = translate
        self.setObjectName("timeline")
        self.setStyleSheet(self.IDLE)
        self.setCursor(Qt.PointingHandCursor)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        self.back = QtWidgets.QToolButton()
        self.back.setText("◀")
        self.back.clicked.connect(lambda: on_step(-1))
        self.forward = QtWidgets.QToolButton()
        self.forward.setText("▶")
        self.forward.clicked.connect(lambda: on_step(1))
        self.slider = FrameRange(on_range, on_keys)
        self.slider.on_focus = lambda on: self.setStyleSheet(self.ACTIVE if on else self.IDLE)
        self.caption = QtWidgets.QLabel()
        self.caption.setMinimumWidth(260)
        self.anchor_label = QtWidgets.QLabel()
        self.anchor = QtWidgets.QComboBox()
        self.anchor.setFocusPolicy(Qt.NoFocus)
        for name in self.ANCHORS:
            self.anchor.addItem(name, name)
        if on_anchor:
            self.anchor.currentIndexChanged.connect(lambda *_: on_anchor(self.anchor.currentData()))
        row.addWidget(self.back)
        row.addWidget(self.slider, 1)
        row.addWidget(self.forward)
        row.addWidget(self.caption)
        row.addWidget(self.anchor_label)
        row.addWidget(self.anchor)

    def mousePressEvent(self, event):
        self.slider.setFocus(Qt.MouseFocusReason)
        event.accept()

    def show_range(self, names, first, last):
        t = self.translate()
        self.slider.set_count(len(names))
        self.slider.set_range(first, last)
        self.back.setToolTip(t("frames_previous") + "  ( , )")
        self.forward.setToolTip(t("frames_next") + "  ( . )")
        self.slider.setToolTip(t("timeline_tip"))
        self.caption.setText(t("timeline_caption", first=names[first], last=names[last], n=last - first + 1,
                               total=len(names)))
        self.anchor_label.setText(t("anchor"))
        self.anchor.setToolTip(t("anchor_tip"))
        for index, name in enumerate(self.ANCHORS):
            self.anchor.setItemText(index, t(f"anchor_{name}"))


class LabelBar(QtWidgets.QFrame):
    """Always-visible strip in the top right corner while labeling: the active class and the protection switch."""

    def __init__(self, host, translate, on_protect):
        super().__init__(host)
        self.host, self.translate = host, translate
        self.below = None
        self.setObjectName("labelbar")
        self.setStyleSheet("QFrame#labelbar { background-color: rgba(21, 23, 30, 225); border: 1px solid #4cc26a; "
                           "border-radius: 8px; } QLabel { color: #f2f4f8; }")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(8, 5, 6, 5)
        row.setSpacing(8)
        self.active = QtWidgets.QLabel()
        row.addWidget(self.active)
        self.protect = QtWidgets.QPushButton()
        self.protect.setCheckable(True)
        self.protect.setCursor(Qt.PointingHandCursor)
        self.protect.toggled.connect(lambda on: on_protect(on))
        row.addWidget(self.protect)
        self.hide()
        host.installEventFilter(self)

    def eventFilter(self, target, event):
        if target is self.host and event.type() == QtCore.QEvent.Resize:
            self.place()
        return False

    def place(self):
        self.adjustSize()
        self.move(self.host.width() - self.width() - 12, 12)
        self.raise_()

    def update_state(self, name, rgb, protected):
        t = self.translate()
        r, g, b = rgb
        self.active.setText(f"<span style='color: rgb({r},{g},{b}); font-size: 15px;'>■</span>  "
                            f"<b>{t('class_active', name=name)}</b>")
        self.protect.blockSignals(True)
        self.protect.setChecked(protected)
        self.protect.blockSignals(False)
        self.protect.setText(("🛡  " if protected else "○  ") + t("label_protect") + ("  ON" if protected else "  OFF"))
        self.protect.setToolTip(t("label_protect_tip"))
        colour = "#4cc26a" if protected else "#8a8f99"
        self.protect.setStyleSheet(
            f"QPushButton {{ color: #f2f4f8; font-weight: 700; padding: 4px 10px; border-radius: 5px; "
            f"border: 1px solid {colour}; background-color: {'rgba(76, 194, 106, 0.30)' if protected else 'transparent'}; }}")
        self.place()
