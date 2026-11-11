"""Draggable 3D handles: a box with move arrows and resize dots, and a slicing plane."""
import numpy as np
import vtk

from .qt import QtWidgets
from .widgets import button, RANGE_LIMIT, Section, set_quietly, spin

AXIS_RGB = ((0.95, 0.32, 0.25), (0.35, 0.85, 0.35), (0.32, 0.56, 1.0))
AXIS_NAMES = "xyz"
HIT_PIXELS = 9
ORIENTATION = ((0, 0, 0), (0, 0, 90), (0, -90, 0))


def _actor(source, rgb, opacity=1.0):
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(source.GetOutputPort())
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    prop = actor.GetProperty()
    prop.SetColor(*rgb)
    prop.SetAmbient(0.55)
    prop.SetDiffuse(0.6)
    prop.SetOpacity(opacity)
    actor.PickableOff()
    actor.VisibilityOff()
    return actor


def _arrow(rgb):
    source = vtk.vtkArrowSource()
    source.SetShaftRadius(0.035)
    source.SetTipRadius(0.09)
    source.SetTipLength(0.25)
    source.SetShaftResolution(12)
    source.SetTipResolution(16)
    return _actor(source, rgb)


def _segment_distance(point, a, b):
    ab = b - a
    t = np.clip(np.dot(point - a, ab) / max(np.dot(ab, ab), 1e-9), 0.0, 1.0)
    return float(np.linalg.norm(point - (a + t * ab)))


class Gizmo:
    """Screen-space hit testing and axis-constrained dragging shared by the handles."""

    def __init__(self, viewport, snap):
        self.viewport = viewport
        self.snap = snap
        self.visible = False
        self._drag = None

    def _screen(self, world):
        return np.array(self.viewport.to_display(world))

    def _axis_shift(self, x, y):
        """Distance moved along the dragged axis since the drag started, in metres."""
        anchor, length, start = self._drag["anchor"], self._drag["length"], self._drag["mouse"]
        direction = self._drag.get("direction")
        if direction is None:
            direction = np.zeros(3)
            direction[self._drag["axis"]] = 1.0
        per_metre = (self._screen(anchor + direction * length) - self._screen(anchor)) / length
        norm = float(np.dot(per_metre, per_metre))
        if norm < 1e-6:
            return 0.0
        return float(np.dot(np.array([x, y]) - start, per_metre) / norm)


class BoxGizmo(Gizmo):
    def __init__(self, viewport, on_change, snap):
        super().__init__(viewport, snap)
        self.on_change = on_change
        self.low, self.high = np.zeros(3), np.ones(3)
        self.arrows = [_arrow(rgb) for rgb in AXIS_RGB]
        self.dots = []
        for axis in range(3):
            for _sign in (-1, 1):
                source = vtk.vtkSphereSource()
                source.SetThetaResolution(16)
                source.SetPhiResolution(12)
                self.dots.append((source, _actor(source, AXIS_RGB[axis])))
        for actor in self.arrows + [actor for _, actor in self.dots]:
            viewport.renderer.AddActor(actor)

    def length(self):
        return max(0.4 * float(np.max(self.high - self.low)), 0.1)

    def set_box(self, low, high):
        self.low, self.high = np.asarray(low, float), np.asarray(high, float)
        centre, length = (self.low + self.high) / 2, self.length()
        for axis, actor in enumerate(self.arrows):
            actor.SetPosition(*centre)
            actor.SetOrientation(*ORIENTATION[axis])
            actor.SetScale(length)
        for index, (source, _actor_) in enumerate(self.dots):
            axis, sign = divmod(index, 2)
            point = centre.copy()
            point[axis] = self.high[axis] if sign else self.low[axis]
            source.SetCenter(*point)
            source.SetRadius(length * 0.07)

    def show(self, visible):
        self.visible = visible
        for actor in self.arrows + [actor for _, actor in self.dots]:
            actor.SetVisibility(visible)

    def hit(self, x, y):
        if not self.visible:
            return None
        mouse = np.array([x, y], float)
        centre, length = (self.low + self.high) / 2, self.length()
        for index, (source, _actor_) in enumerate(self.dots):
            if np.linalg.norm(self._screen(source.GetCenter()) - mouse) <= HIT_PIXELS + 2:
                return "resize", index // 2, index % 2
        for axis in range(3):
            tip = centre.copy()
            tip[axis] += length
            if _segment_distance(mouse, self._screen(centre), self._screen(tip)) <= HIT_PIXELS:
                return "move", axis, None
        return None

    def begin(self, handle, x, y):
        kind, axis, side = handle
        anchor = (self.low + self.high) / 2
        self._drag = {"kind": kind, "axis": axis, "side": side, "mouse": np.array([x, y], float), "anchor": anchor,
                      "length": self.length(), "low": self.low.copy(), "high": self.high.copy()}

    def drag(self, x, y):
        if self._drag is None:
            return
        shift = self.snap(self._axis_shift(x, y))
        axis, low, high = self._drag["axis"], self._drag["low"].copy(), self._drag["high"].copy()
        if self._drag["kind"] == "move":
            low[axis] += shift
            high[axis] += shift
        elif self._drag["side"]:
            high[axis] = max(high[axis] + shift, low[axis] + self.snap.step)
        else:
            low[axis] = min(low[axis] + shift, high[axis] - self.snap.step)
        self.set_box(low, high)
        self.on_change(low, high)

    def end(self):
        self._drag = None


def plane_normal(axis, tilt):
    """Unit normal of a plane that starts perpendicular to `axis` and is tilted about the two other axes (degrees)."""
    u, v = [a for a in range(3) if a != axis]
    normal = np.zeros(3)
    normal[axis] = 1.0
    for about, angle in ((u, tilt[0]), (v, tilt[1])):
        c, s = np.cos(np.radians(angle)), np.sin(np.radians(angle))
        i, j = [a for a in range(3) if a != about]
        normal[i], normal[j] = c * normal[i] - s * normal[j], s * normal[i] + c * normal[j]
    return normal


class SliceGizmo(Gizmo):
    def __init__(self, viewport, on_change, snap):
        super().__init__(viewport, snap)
        self.on_change = on_change
        self.axis, self.position = 2, 0.0
        self.normal = np.array([0.0, 0.0, 1.0])
        self.pivot = np.zeros(3)
        self.extent = 1.0
        self.limits = (0.0, 1.0)
        self.plane = vtk.vtkPlaneSource()
        self.plane_actor = _actor(self.plane, AXIS_RGB[2], 0.18)
        self.plane_actor.GetProperty().LightingOff()
        self.edge_actor = _actor(self.plane, AXIS_RGB[2])
        self.edge_actor.GetProperty().SetRepresentationToWireframe()
        self.edge_actor.GetProperty().SetLineWidth(2.0)
        self.edge_actor.GetProperty().LightingOff()
        self.arrow = _arrow(AXIS_RGB[2])
        for actor in (self.plane_actor, self.edge_actor, self.arrow):
            viewport.renderer.AddActor(actor)

    def length(self):
        return max(0.12 * self.extent, 0.15)

    def centre(self):
        return self.pivot.copy()

    def update(self, axis, position, bounds, normal=None, centre=None):
        """Place the plane: it passes through the pivot (the centre, moved to `position` on the axis)."""
        low, high = np.asarray(bounds[0], float), np.asarray(bounds[1], float)
        self.axis, self.position = axis, float(position)
        self.extent = float(np.max(high - low))
        self.limits = (float(low[axis]), float(high[axis]))
        self.normal = np.zeros(3)
        self.normal[axis] = 1.0
        if normal is not None:
            self.normal = np.asarray(normal, float)
        self.pivot = np.array((low + high) / 2 if centre is None else centre, float)
        self.pivot[axis] = self.position
        helper = np.zeros(3)
        helper[int(np.argmin(np.abs(self.normal)))] = 1.0
        first = np.cross(self.normal, helper)
        first /= np.linalg.norm(first)
        second = np.cross(self.normal, first)
        reach = 0.6 * float(np.linalg.norm(high - low)) + 0.05
        corner = self.pivot - first * reach - second * reach
        self.plane.SetOrigin(*corner)
        self.plane.SetPoint1(*(corner + 2 * reach * first))
        self.plane.SetPoint2(*(corner + 2 * reach * second))
        rgb = AXIS_RGB[axis]
        for actor in (self.plane_actor, self.edge_actor, self.arrow):
            actor.GetProperty().SetColor(*rgb)
        matrix = vtk.vtkMatrix4x4()
        length = self.length()
        for row in range(3):
            matrix.SetElement(row, 0, self.normal[row] * length)
            matrix.SetElement(row, 1, first[row] * length)
            matrix.SetElement(row, 2, second[row] * length)
            matrix.SetElement(row, 3, self.pivot[row])
        self.arrow.SetUserMatrix(matrix)

    def show(self, visible):
        self.visible = visible
        for actor in (self.plane_actor, self.edge_actor, self.arrow):
            actor.SetVisibility(visible)

    def hit(self, x, y):
        if not self.visible:
            return None
        tip = self.pivot + self.normal * self.length()
        mouse = np.array([x, y], float)
        if _segment_distance(mouse, self._screen(self.pivot), self._screen(tip)) <= HIT_PIXELS:
            return "slice", self.axis, None
        return None

    def begin(self, handle, x, y):
        self._drag = {"axis": self.axis, "direction": self.normal.copy(), "mouse": np.array([x, y], float),
                      "anchor": self.pivot.copy(), "length": self.length(), "position": self.position}

    def drag(self, x, y):
        if self._drag is None:
            return
        along_axis = self._axis_shift(x, y) / self.normal[self.axis]
        self.position = float(np.clip(self._drag["position"] + self.snap(along_axis), *self.limits))
        self.on_change(self.position)

    def end(self):
        self._drag = None


class Snap:
    """Rounds a distance to a grid step (step 0 leaves it unchanged)."""

    def __init__(self, step=0.0):
        self.step = step if step > 0 else 0.01
        self.grid = step > 0

    def __call__(self, value):
        return round(value / self.step) * self.step if self.grid else value


class SliceControls:
    """Panel section that cuts the view with a plane: an axis, a position along it and two tilt angles."""

    def __init__(self, tr, values, step, on_change, on_restore):
        W = QtWidgets
        self.group = Section(tr("slice"), "slice")
        self.group.setToolTip(tr("slice_tip"))
        form = W.QFormLayout(self.group)
        self.enabled = W.QCheckBox(tr("slice_enable"))
        self.enabled.setChecked(values["on"])
        form.addRow(self.enabled)
        row = W.QHBoxLayout()
        self.axes = W.QButtonGroup(self.group)
        for axis, name in enumerate(AXIS_NAMES):
            radio = W.QRadioButton(name.upper())
            radio.setChecked(axis == values["axis"])
            self.axes.addButton(radio, axis)
            row.addWidget(radio)
        form.addRow(tr("slice_axis"), row)
        self.position = spin(-RANGE_LIMIT, RANGE_LIMIT, values["position"], step)
        form.addRow(tr("slice_position"), self.position)
        self.tr = tr
        self.centre = np.array(values["centre"], float)
        self.tilts, self.tilt_labels = [], []
        for angle in values["tilt"]:
            box = spin(-80.0, 80.0, angle, 5.0, decimals=1)
            label = W.QLabel()
            form.addRow(label, box)
            self.tilts.append(box)
            self.tilt_labels.append(label)
            box.valueChanged.connect(lambda *_: on_change())
        self._name_tilts()
        self.keep = W.QComboBox()
        self.keep.addItem(tr("slice_below"), "below")
        self.keep.addItem(tr("slice_above"), "above")
        self.keep.setCurrentIndex(max(self.keep.findData(values["keep"]), 0))
        form.addRow(tr("slice_keep"), self.keep)
        row = W.QHBoxLayout()
        row.addWidget(button(tr("slice_flip"), self.flip))
        row.addWidget(button(tr("slice_restore"), on_restore))
        form.addRow(row)
        self.enabled.toggled.connect(lambda *_: on_change())
        self.axes.buttonClicked.connect(lambda *_: (self._name_tilts(), on_change()))
        self.position.valueChanged.connect(lambda *_: on_change())
        self.keep.currentIndexChanged.connect(lambda *_: on_change())

    def flip(self):
        self.keep.setCurrentIndex(1 - self.keep.currentIndex())

    def _name_tilts(self):
        others = [name.upper() for axis, name in enumerate(AXIS_NAMES) if axis != self.axes.checkedId()]
        for label, name in zip(self.tilt_labels, others):
            label.setText(self.tr("slice_tilt", axis=name))

    def values(self):
        return {"on": self.enabled.isChecked(), "axis": self.axes.checkedId(), "position": self.position.value(),
                "keep": self.keep.currentData(), "tilt": tuple(box.value() for box in self.tilts),
                "centre": tuple(self.centre)}

    def set_position(self, value):
        set_quietly(self.position, value)

    def normal(self):
        values = self.values()
        return plane_normal(values["axis"], values["tilt"])

    def pivot(self):
        """Point the plane passes through: the stored centre, moved to the position on the slicing axis."""
        point = self.centre.copy()
        point[self.axes.checkedId()] = self.position.value()
        return point

    def signed(self, points):
        """Signed distance of points from the plane (positive on the side the normal points to)."""
        return (points - self.pivot()) @ self.normal()

    def mask(self, points):
        """True for points on the kept side (all True when slicing is off)."""
        values = self.values()
        if not values["on"] or not len(points):
            return np.ones(len(points), bool)
        distance = self.signed(points)
        return distance <= 1e-9 if values["keep"] == "below" else distance >= -1e-9

    def box_side(self, low, high):
        """Where a box lies: -1 wholly on the hidden side, 1 wholly on the kept side, 0 cut by the plane."""
        values = self.values()
        normal = self.normal()
        middle = ((low + high) / 2 - self.pivot()) @ normal
        reach = float(np.abs(normal) @ ((high - low) / 2))
        nearest, farthest = middle - reach, middle + reach
        if values["keep"] == "below":
            return 1 if farthest <= 1e-9 else -1 if nearest > 1e-9 else 0
        return 1 if nearest >= -1e-9 else -1 if farthest < -1e-9 else 0


SLICE_DEFAULTS = {"on": False, "axis": 2, "position": 0.0, "keep": "below", "tilt": (0.0, 0.0), "centre": (0.0, 0.0, 0.0)}
