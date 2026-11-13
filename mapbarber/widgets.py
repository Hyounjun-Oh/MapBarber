"""Small widget helpers shared by the editors."""
import time

from .qt import QtCore, QtGui, QtWidgets

RANGE_LIMIT = 1000.0


class WheelGuard(QtCore.QObject):
    """The wheel acts on a number field, drop-down, slider or inner scrolling box only after it was clicked
    and while the pointer stays on it.

    Anywhere else the wheel scrolls the surrounding panel, so values never change by accident and a list
    in the panel never swallows the wheel while the panel is being scrolled.
    """

    GUARDED = (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox, QtWidgets.QAbstractSlider)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.armed = None

    @staticmethod
    def _outer(widget):
        """The scrolling area a widget sits in, or None."""
        area = widget.parent()
        while area is not None and not isinstance(area, QtWidgets.QAbstractScrollArea):
            area = area.parent()
        return area

    def _field(self, target):
        """What a click or wheel turn belongs to: a number field, drop-down or slider, or any scrolling box
        (list, table, text) that sits inside another scrolling panel. None for everything else."""
        widget = target
        while widget is not None:
            if isinstance(widget, QtWidgets.QScrollBar) and widget is target:
                widget = widget.parent()
                continue
            if isinstance(widget, self.GUARDED) and not isinstance(widget, QtWidgets.QScrollBar):
                return widget
            if isinstance(widget, QtWidgets.QAbstractScrollArea):
                return widget if self._outer(widget) is not None else None
            if widget.isWindow():
                return None
            widget = widget.parent()
        return None

    def eventFilter(self, target, event):
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonPress and isinstance(target, QtWidgets.QWidget):
            self.armed = self._field(target)
        elif kind == QtCore.QEvent.Leave and target is self.armed:
            self.armed = None
        elif kind == QtCore.QEvent.Wheel and isinstance(target, QtWidgets.QWidget):
            field = self._field(target)
            if field is not None and field is not self.armed:
                area = self._outer(field)
                if area is not None:
                    QtWidgets.QApplication.sendEvent(area.verticalScrollBar(), event)
                return True
            if field is not None and field is not target and not isinstance(field, QtWidgets.QAbstractScrollArea):
                QtWidgets.QApplication.sendEvent(field, event)
                return True
        return False


class UndoGuard(QtCore.QObject):
    """Sends Ctrl+Z / Ctrl+Y to the editor even while a number field has the keyboard.

    A number field would otherwise keep those keys for the text typed into it, and after clicking one the
    editor's undo would seem dead.
    """

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, target, event):
        if event.type() not in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride):
            return False
        focus = QtWidgets.QApplication.focusWidget()
        field = focus if isinstance(focus, QtWidgets.QAbstractSpinBox) else focus.parent() if focus is not None else None
        if not isinstance(field, QtWidgets.QAbstractSpinBox) or field.window() is not self.window:
            return False
        undo, redo = event.matches(QtGui.QKeySequence.Undo), event.matches(QtGui.QKeySequence.Redo)
        if not (undo or redo) or self.window.editor is None:
            return False
        if event.type() == QtCore.QEvent.KeyPress:
            (self.window.editor.undo if undo else self.window.editor.redo)()
        event.accept()
        return event.type() == QtCore.QEvent.KeyPress


def spin(low, high, value, step=0.05, slot=None, decimals=3):
    box = QtWidgets.QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    box.setKeyboardTracking(False)
    if slot:
        box.valueChanged.connect(slot)
    return box


def int_spin(low, high, value, suffix="", slot=None):
    box = QtWidgets.QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    box.setSuffix(suffix)
    if slot:
        box.valueChanged.connect(slot)
    return box


ROLE_STYLE = ("QPushButton {{ border: 1px solid {c}; border-radius: 4px; padding: 4px 8px; "
              "background-color: rgba({r}, {g}, {b}, 0.16); }} "
              "QPushButton:hover {{ background-color: rgba({r}, {g}, {b}, 0.32); }} "
              "QPushButton:pressed {{ background-color: rgba({r}, {g}, {b}, 0.5); }}")


def button(text, slot, tip=None, role=None, icon=None):
    """Push button; role 'danger', 'add' or 'select' tints it, `icon` names the drawing that shows what it does
    (one of icons._BUTTONS; without it the role's own icon is used)."""
    widget = QtWidgets.QPushButton(text)
    widget.clicked.connect(slot)
    if tip:
        widget.setToolTip(tip)
    from . import icons
    if role:
        colour = icons.accent(f"role_{role}")
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        widget.setStyleSheet(ROLE_STYLE.format(c=colour, r=r, g=g, b=b))
    if icon:
        widget.setIcon(icons.icon(f"button_{icon}", 16))
    elif role:
        widget.setIcon(icons.icon(f"role_{role}", 14))
    return widget


def tint(widget, rgb, icon_name=None):
    """Colour a push button with any colour (for example a class colour) instead of a role colour."""
    r, g, b = (int(v) for v in rgb)
    widget.setStyleSheet(ROLE_STYLE.format(c=f"rgb({r}, {g}, {b})", r=r, g=g, b=b))
    if icon_name:
        from . import icons
        widget.setIcon(icons.icon(icon_name, 14))


def danger_button(text, slot, tip=None, icon=None):
    return button(text, slot, tip, "danger", icon)


def add_button(text, slot, tip=None, icon=None):
    return button(text, slot, tip, "add", icon)


def select_button(text, slot, tip=None, icon=None):
    return button(text, slot, tip, "select", icon)


class Section(QtWidgets.QFrame):
    """Framed panel group with an icon and title above it and an accent stripe on its left edge."""

    def __init__(self, title, name):
        super().__init__()
        from . import icons
        self.setObjectName("section")
        self.setStyleSheet(f"QFrame#section {{ border: 1px solid rgba(128, 128, 128, 0.35); "
                           f"border-left: 4px solid {icons.accent(name)}; border-radius: 6px; "
                           "background-color: rgba(128, 128, 128, 0.07); }")
        self.header = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self.header)
        row.setContentsMargins(2, 10, 0, 0)
        row.setSpacing(7)
        image = icons.pixmap(name, 20)
        if image is not None:
            badge = QtWidgets.QLabel()
            badge.setPixmap(image)
            row.addWidget(badge)
        label = QtWidgets.QLabel(title)
        label.setStyleSheet("font-weight: 700;")
        row.addWidget(label)
        row.addStretch(1)

    def setToolTip(self, text):
        super().setToolTip(text)
        self.header.setToolTip(text)

    def add_to(self, layout):
        layout.addWidget(self.header)
        layout.addWidget(self)


def set_quietly(box, value):
    box.blockSignals(True)
    box.setValue(value)
    box.blockSignals(False)


class AxisRanges:
    """Three rows of (low, high) spin boxes for x, y and z."""

    def __init__(self, grid, first_row, values, step, slot):
        self.pairs = []
        for row, (axis, (low, high)) in enumerate(zip("xyz", values), start=first_row):
            grid.addWidget(QtWidgets.QLabel(f"{axis} [m]"), row, 0)
            pair = (spin(-RANGE_LIMIT, RANGE_LIMIT, low, step, slot), spin(-RANGE_LIMIT, RANGE_LIMIT, high, step, slot))
            grid.addWidget(pair[0], row, 1)
            grid.addWidget(pair[1], row, 2)
            self.pairs.append(pair)

    def values(self):
        return [(a.value(), b.value()) for a, b in self.pairs]

    def bounds(self):
        import numpy as np
        low = np.array([min(a.value(), b.value()) for a, b in self.pairs])
        high = np.array([max(a.value(), b.value()) for a, b in self.pairs])
        return low, high

    def set(self, low, high):
        for (a, b), lo, hi in zip(self.pairs, low, high):
            set_quietly(a, lo)
            set_quietly(b, hi)

    def reset(self):
        self.set([-RANGE_LIMIT] * 3, [RANGE_LIMIT] * 3)

    def set_step(self, step):
        for a, b in self.pairs:
            a.setSingleStep(step)
            b.setSingleStep(step)


def ask_numbers(parent, title, fields):
    """Modal form of fields -> list of values or None.

    A field is (label, value, low, high, decimals) for a number or (label, bool) for a tick box.
    """
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title)
    form = QtWidgets.QFormLayout(dialog)
    boxes = []
    for field in fields:
        if len(field) == 2:
            box = QtWidgets.QCheckBox(field[0])
            box.setChecked(bool(field[1]))
            box.value = box.isChecked
            form.addRow(box)
        else:
            label, value, low, high, decimals = field
            box = int_spin(int(low), int(high), int(value)) if decimals == 0 else spin(low, high, value, 10 ** -decimals,
                                                                                       None, decimals)
            form.addRow(label, box)
        boxes.append(box)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    from .qt import run
    if run(dialog) != QtWidgets.QDialog.Accepted:
        return None
    return [box.value() for box in boxes]


class Spinner(QtWidgets.QWidget):
    """A turning arc, shown while work of unknown length is running."""

    def __init__(self, size=36):
        super().__init__()
        self.setFixedSize(size, size)
        self.angle = 0
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._turn)
        self.timer.start()

    def _turn(self):
        self.angle = (self.angle + 24) % 360
        self.update()

    def paintEvent(self, _event):
        from .qt import QtGui
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        box = QtCore.QRectF(4, 4, self.width() - 8, self.height() - 8)
        painter.setPen(QtGui.QPen(QtGui.QColor(128, 128, 128, 70), 4))
        painter.drawEllipse(box)
        pen = QtGui.QPen(QtGui.QColor(79, 156, 247), 4)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(box, -self.angle * 16, 100 * 16)
        painter.end()


class BusyDialog(QtWidgets.QDialog):
    """Modal notice for running work: a spinner while the length is unknown, a bar once progress is reported.

    It appears only if the work lasts longer than a moment and never after finish() was called.
    """

    DELAY_MS = 250

    def __init__(self, parent, text):
        super().__init__(parent)
        self.setWindowTitle("MapBarber")
        self.setWindowModality(QtCore.Qt.WindowModal)
        self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)
        self.setMinimumWidth(400)
        self.finished_work = False
        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.spinner = Spinner()
        row.addWidget(self.spinner)
        self.label = QtWidgets.QLabel(text)
        self.label.setWordWrap(True)
        row.addWidget(self.label, 1)
        layout.addLayout(row)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.hide()
        layout.addWidget(self.bar)
        QtCore.QTimer.singleShot(self.DELAY_MS, self._appear)

    def _appear(self):
        if not self.finished_work:
            self.show()

    def set_progress(self, done, total, text=None):
        """Switch from the spinner to a bar showing done out of total."""
        if text:
            self.label.setText(text)
        self.spinner.hide()
        self.bar.show()
        self.bar.setRange(0, max(int(total), 1))
        self.bar.setValue(int(done))

    def finish(self):
        """Close for good; a pending delayed appearance is cancelled."""
        self.finished_work = True
        self.spinner.timer.stop()
        self.hide()
        self.deleteLater()

    def reject(self):
        """Ignore Escape: the work cannot be cancelled half-way."""


class Working:
    """Long work done step by step in the window's own thread.

    Used as `with Working(window, text) as report:`, calling report(done, total) after each step. Once the work
    has taken longer than a moment the busy dialog appears, and from then on its bar follows the reports; quick
    work shows nothing.
    """

    def __init__(self, parent, text):
        self.parent, self.text, self.dialog, self.start = parent, text, None, time.monotonic()

    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __call__(self, done=0, total=0, text=None):
        if self.dialog is None:
            if time.monotonic() - self.start < BusyDialog.DELAY_MS / 1000.0:
                return
            self.dialog = BusyDialog(self.parent, self.text)
            self.dialog.show()
        if total:
            self.dialog.set_progress(done, total, text)
        QtWidgets.QApplication.processEvents()

    def __exit__(self, *_):
        if self.dialog is not None:
            self.dialog.finish()
        return False
