"""Small widget helpers shared by the editors."""
from .qt import QtCore, QtWidgets

RANGE_LIMIT = 1000.0


class WheelGuard(QtCore.QObject):
    """The wheel edits a number field or list only after it was clicked and while the pointer stays on it.

    Anywhere else the wheel scrolls the surrounding panel, so values never change by accident.
    """

    GUARDED = (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox, QtWidgets.QAbstractSlider)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.armed = None

    def _field(self, target):
        if isinstance(target, QtWidgets.QScrollBar):
            return None
        if isinstance(target, self.GUARDED):
            return target
        parent = target.parent() if isinstance(target, QtWidgets.QLineEdit) else None
        return parent if isinstance(parent, self.GUARDED) else None

    def eventFilter(self, target, event):
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonPress and isinstance(target, QtWidgets.QWidget):
            self.armed = self._field(target)
        elif kind == QtCore.QEvent.Leave and target is self.armed:
            self.armed = None
        elif kind == QtCore.QEvent.Wheel and isinstance(target, QtWidgets.QWidget):
            field = self._field(target)
            if field is not None and field is not self.armed:
                area = field.parent()
                while area is not None and not isinstance(area, QtWidgets.QAbstractScrollArea):
                    area = area.parent()
                if area is not None:
                    QtWidgets.QApplication.sendEvent(area.verticalScrollBar(), event)
                return True
            if field is not None and field is not target:
                QtWidgets.QApplication.sendEvent(field, event)
                return True
        return False


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


def button(text, slot, tip=None, role=None):
    """Push button; role 'danger', 'add' or 'select' tints it and adds a matching icon."""
    widget = QtWidgets.QPushButton(text)
    widget.clicked.connect(slot)
    if tip:
        widget.setToolTip(tip)
    if role:
        from . import icons
        colour = icons.accent(f"role_{role}")
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        widget.setStyleSheet(ROLE_STYLE.format(c=colour, r=r, g=g, b=b))
        widget.setIcon(icons.icon(f"role_{role}", 14))
    return widget


def danger_button(text, slot, tip=None):
    return button(text, slot, tip, "danger")


def add_button(text, slot, tip=None):
    return button(text, slot, tip, "add")


def select_button(text, slot, tip=None):
    return button(text, slot, tip, "select")


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
    """Modal form of numeric fields [(label, value, low, high, decimals)] -> list of values or None."""
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title)
    form = QtWidgets.QFormLayout(dialog)
    boxes = []
    for label, value, low, high, decimals in fields:
        box = int_spin(int(low), int(high), int(value)) if decimals == 0 else spin(low, high, value, 10 ** -decimals, None,
                                                                                   decimals)
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
