"""Small widget helpers shared by the editors."""
from .qt import QtWidgets

RANGE_LIMIT = 1000.0


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


def button(text, slot, tip=None):
    widget = QtWidgets.QPushButton(text)
    widget.clicked.connect(slot)
    if tip:
        widget.setToolTip(tip)
    return widget


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
