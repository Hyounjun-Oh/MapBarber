"""Editor for point clouds: points are removed, never moved, and every per-point field is kept on save."""
import numpy as np
import vtk
from vtk.util import numpy_support

from . import cloud, convert, formats
from .editor import Editor
from .formats import CLOUD, GRID, VOXEL
from .gizmo import AXIS_NAMES, SLICE_DEFAULTS, BoxGizmo, SliceControls, SliceGizmo, Snap
from .qt import QtCore, QtWidgets
from .ruler import RULER_RGB, Ruler3D, measure
from .scene import VIEWS, Viewport, ramp
from .widgets import ask_numbers, AxisRanges, button, danger_button, int_spin, RANGE_LIMIT, Section, select_button, spin

Qt = QtCore.Qt
SELECTED_RGB = np.array([255, 40, 200], np.uint8)
TOOL_RGB = {"select": (1.0, 0.2, 0.8), "delete": (1.0, 0.15, 0.1)}
PICK_PIXELS = 6
COLOUR_FIELDS_SKIPPED = {"x", "y", "z", "rgb", "rgba", "red", "green", "blue", "alpha", "r", "g", "b", "a"}
DEFAULTS = {"radius": 0.10, "point_size": 3, "colour": "height", "front_only": True, "tolerance": 0.10,
            "neighbours": 16, "ratio": 2.0, "sparse_radius": 0.10, "sparse_min": 4, "leaf": 0.05,
            "box": [(-0.5, 0.5)] * 3, "show_box": False, "range": [(-RANGE_LIMIT, RANGE_LIMIT)] * 3,
            "slice": SLICE_DEFAULTS}


def point_colours(table):
    """Per-point RGB stored in the file, or None."""
    if table is None:
        return None
    names = table.dtype.names
    for packed in ("rgb", "rgba"):
        if packed in names and table.dtype[packed].itemsize == 4:
            value = np.ascontiguousarray(table[packed]).view(np.uint32)
            return np.stack([(value >> 16) & 255, (value >> 8) & 255, value & 255], axis=1).astype(np.uint8)
    for triple in (("red", "green", "blue"), ("r", "g", "b")):
        if all(name in names for name in triple):
            channels = np.stack([table[name].astype(np.float64) for name in triple], axis=1)
            if channels.max(initial=0) <= 1.0:
                channels *= 255.0
            return np.clip(channels, 0, 255).astype(np.uint8)
    return None


class CloudEditor(Editor):
    kind = CLOUD
    tools = (("view", "H"), ("select", "V"), ("delete", "E"), ("measure", "I"))
    export_filters = (("PCD point cloud", "pcd"), ("PLY point cloud", "ply"), ("XYZ text", "xyz"), ("CSV text", "csv"),
                      ("NumPy array", "npy"), ("NumPy archive", "npz"))

    def __init__(self, window):
        super().__init__(window)
        self.cloud = cloud.PointCloud(np.zeros((0, 3)))
        self.colours = None
        self.selection = np.zeros(0, np.int64)
        self.visible_ids = np.zeros(0, np.int64)
        self.visible_points = np.zeros((0, 3))
        self._tree = None
        self.panel_values = dict(DEFAULTS)
        self.viewport = Viewport(window, self._click, self._hover, self._rectangle, self._right_click)
        self.widget = self.viewport.widget
        self.polydata = vtk.vtkPolyData()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(self.polydata)
        mapper.SetScalarModeToUsePointData()
        self.actor = vtk.vtkActor()
        self.actor.SetMapper(mapper)
        self.actor.GetProperty().SetPointSize(DEFAULTS["point_size"])
        self.actor.GetProperty().SetRenderPointsAsSpheres(True)
        self.viewport.renderer.AddActor(self.actor)
        self.hover_source, self.hover_actor = self.viewport.wire_sphere((1, 1, 1))
        self.box_source, self.box_actor = self.viewport.outline((1.0, 0.85, 0.1))
        self.box_gizmo = BoxGizmo(self.viewport, self._box_dragged, Snap(0.01))
        self.slice_gizmo = SliceGizmo(self.viewport, self._slice_dragged, Snap(0.01))
        self.viewport.gizmos = [self.slice_gizmo, self.box_gizmo]
        self.ruler = Ruler3D(self.viewport.renderer)
        self.viewport.band_allowed = lambda: self.tool != "measure"
        self.measurement = None
        self.data_bounds = (np.zeros(3), np.ones(3))
        self.hidden = 0
        self._previous_mode = (False, 2)
        self._refresh_timer = QtCore.QTimer()
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)
        self._refresh_timer.timeout.connect(self.refresh)

    @property
    def dirty(self):
        return self.cloud.dirty

    def load(self, path):
        self.set_document(formats.read_cloud(path), path, formats.detect(path))

    def set_document(self, payload, path=None, fmt=None):
        xyz, table = payload
        self.cloud = cloud.PointCloud(xyz, table)
        self.colours = point_colours(table)
        self.path, self.format = path, fmt
        self.selection = np.zeros(0, np.int64)
        alive = self.cloud.xyz[self.cloud.alive]
        extent = float(np.ptp(alive, axis=0).max()) if len(alive) else 1.0
        self.viewport.set_axes_length(max(0.08 * extent, 1e-3))
        self.clear_ruler()
        self.panel_values["range"] = DEFAULTS["range"]
        if self.panel_values["colour"] not in self.colour_modes():
            self.panel_values["colour"] = "height"
        if self.panel_alive:
            self.ranges.reset()
            self._fill_colour_modes()
        self.refresh(render=False)

    def save(self, path, fmt=None):
        xyz, table = self.cloud.surviving()
        if not len(xyz):
            raise ValueError(self.tr("empty_map"))
        formats.save_cloud(path, xyz, table, fmt)
        self.cloud.mark_saved()
        self.changed()

    def undo(self):
        if self.cloud.undo():
            self.refresh()

    def redo(self):
        if self.cloud.redo():
            self.refresh()

    def summary(self):
        return self.tr("cloud_counts", n=len(self.cloud), v=len(self.visible_ids), r=self.cloud.removed(),
                       s=len(self.selection))

    def colour_modes(self):
        modes = ["height"]
        if self.colours is not None:
            modes.append("rgb")
        table = self.cloud.table
        if table is not None:
            modes += [name for name in table.dtype.names
                      if name.lower() not in COLOUR_FIELDS_SKIPPED and not table.dtype[name].shape
                      and table.dtype[name].kind in "fiu"]
        return modes

    def _fill_colour_modes(self):
        self.colour_box.blockSignals(True)
        self.colour_box.clear()
        for mode in self.colour_modes():
            label = self.tr("colour_height") if mode == "height" else self.tr("colour_rgb") if mode == "rgb" else mode
            self.colour_box.addItem(label, mode)
        index = self.colour_box.findData(self.panel_values["colour"])
        self.colour_box.setCurrentIndex(max(index, 0))
        self.colour_box.blockSignals(False)

    def build_panel(self):
        t, values, W = self.tr, self.panel_values, QtWidgets
        panel = W.QWidget()
        layout = W.QVBoxLayout(panel)

        group = Section(t("display"), "display")
        form = W.QFormLayout(group)
        self.point_size = int_spin(1, 20, values["point_size"], " px", self._style_changed)
        form.addRow(t("point_size"), self.point_size)
        self.colour_box = W.QComboBox()
        self.colour_box.currentIndexChanged.connect(lambda *_: self.recolor())
        form.addRow(t("colour_by"), self.colour_box)
        group.add_to(layout)

        group = Section(t("brush"), "brush")
        form = W.QFormLayout(group)
        self.radius = spin(0.001, RANGE_LIMIT, values["radius"], 0.01)
        self.radius.setToolTip(t("cloud_brush_tip"))
        form.addRow(t("brush_radius"), self.radius)
        group.add_to(layout)

        group = Section(t("rectangle"), "rectangle")
        form = W.QFormLayout(group)
        self.front_only = W.QCheckBox(t("front_only"))
        self.front_only.setChecked(values["front_only"])
        form.addRow(self.front_only)
        self.tolerance = spin(0.0, RANGE_LIMIT, values["tolerance"], 0.01)
        form.addRow(t("depth_tolerance"), self.tolerance)
        row = W.QHBoxLayout()
        row.addWidget(danger_button(t("delete_selection"), self.delete_selection))
        row.addWidget(button(t("clear_selection"), self.clear_selection))
        form.addRow(row)
        group.add_to(layout)

        group = Section(t("noise_filters"), "noise_filters")
        form = W.QFormLayout(group)
        self.neighbours = int_spin(2, 200, values["neighbours"])
        self.ratio = spin(0.1, 10.0, values["ratio"], 0.1, decimals=2)
        form.addRow(t("neighbours"), self.neighbours)
        form.addRow(t("std_ratio"), self.ratio)
        form.addRow(select_button(t("select_outliers"), self.select_outliers, t("outliers_tip")))
        self.sparse_radius = spin(0.001, RANGE_LIMIT, values["sparse_radius"], 0.01)
        self.sparse_min = int_spin(1, 1000, values["sparse_min"])
        form.addRow(t("search_radius"), self.sparse_radius)
        form.addRow(t("min_neighbours"), self.sparse_min)
        form.addRow(select_button(t("select_sparse"), self.select_sparse, t("sparse_tip")))
        group.add_to(layout)

        group = Section(t("downsample"), "downsample")
        form = W.QFormLayout(group)
        self.leaf = spin(0.001, RANGE_LIMIT, values["leaf"], 0.01)
        form.addRow(t("cell_size"), self.leaf)
        form.addRow(danger_button(t("thin_out"), self.thin_out, t("thin_tip")))
        group.add_to(layout)

        group = Section(t("box"), "box")
        group.setToolTip(t("box_handles_tip"))
        grid = W.QGridLayout(group)
        self.box = AxisRanges(grid, 0, values["box"], 0.05, self._box_changed)
        self.show_box = W.QCheckBox(t("show_box"))
        self.show_box.setChecked(values["show_box"])
        self.show_box.toggled.connect(self._box_changed)
        grid.addWidget(self.show_box, 3, 0, 1, 2)
        grid.addWidget(button(t("box_from_selection"), self.box_from_selection), 3, 2)
        grid.addWidget(select_button(t("box_select"), self.box_select), 4, 0, 1, 3)
        grid.addWidget(danger_button(t("box_delete"), self.box_delete), 5, 0, 1, 3)
        grid.addWidget(danger_button(t("box_delete_outside"), self.box_delete_outside, t("crop_tip")), 6, 0, 1, 3)
        group.add_to(layout)

        group = Section(t("ruler"), "ruler")
        group.setToolTip(t("ruler_tip"))
        form = W.QFormLayout(group)
        self.ruler_label = W.QLabel(self._ruler_text(self.measurement)[1] if self.measurement else t("ruler_hint"))
        self.ruler_label.setWordWrap(True)
        self.ruler_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.ruler_label)
        form.addRow(button(t("ruler_clear"), self.clear_ruler))
        group.add_to(layout)

        self.slice = SliceControls(t, values["slice"], 0.01, self._slice_changed, self.restore_view)
        self.slice.group.add_to(layout)

        group = Section(t("visible_range"), "visible_range")
        group.setToolTip(t("range_tip"))
        grid = W.QGridLayout(group)
        self.ranges = AxisRanges(grid, 0, values["range"], 0.05, lambda *_: self.refresh())
        grid.addWidget(button(t("show_all"), self.reset_range), 3, 0, 1, 3)
        group.add_to(layout)

        layout.addStretch(1)
        legend = W.QLabel(t("cloud_legend"))
        legend.setWordWrap(True)
        legend.setStyleSheet("color: gray;")
        layout.addWidget(legend)
        self._fill_colour_modes()
        self._style_changed()
        self._box_changed()
        self._update_slice_gizmo()
        return panel

    def store_panel(self):
        if self.panel_alive:
            self.panel_values = {"radius": self.radius.value(), "point_size": self.point_size.value(),
                                 "colour": self.colour_box.currentData() or "height",
                                 "front_only": self.front_only.isChecked(), "tolerance": self.tolerance.value(),
                                 "neighbours": self.neighbours.value(), "ratio": self.ratio.value(),
                                 "sparse_radius": self.sparse_radius.value(), "sparse_min": self.sparse_min.value(),
                                 "leaf": self.leaf.value(), "box": self.box.values(), "show_box": self.show_box.isChecked(),
                                 "range": self.ranges.values(), "slice": self.slice.values()}

    def view_actions(self):
        return [(self.tr(f"view_{name}"), lambda d=direction, u=up: self.look_from(d, u), keys)
                for name, direction, up, keys in VIEWS]

    def selection_actions(self):
        return {"delete": self.delete_selection, "select_all": self.select_all, "invert": self.invert_selection,
                "clear": self.clear_selection}

    def conversions(self):
        return [(self.tr("to_voxels"), self.to_voxels), (self.tr("to_grid"), self.to_grid)]

    def activate(self):
        self.viewport.initialize()
        self.look_from(*VIEWS[3][1:3])

    def capture(self):
        return self.viewport.capture()

    def refresh(self, render=True):
        ids = self.cloud.ids()
        points = self.cloud.xyz[ids]
        if len(points):
            self.data_bounds = (points.min(axis=0), points.max(axis=0))
        total = len(ids)
        if self.panel_alive and len(points):
            low, high = self.ranges.bounds()
            inside = np.all((points >= low) & (points <= high), axis=1) & self.slice.mask(points)
            ids, points = ids[inside], points[inside]
        self.hidden = total - len(ids)
        self.visible_ids, self.visible_points = ids, np.ascontiguousarray(points)
        self.selection = self.selection[np.isin(self.selection, ids, assume_unique=True)]
        self._tree = None
        vtk_points = vtk.vtkPoints()
        cells = vtk.vtkCellArray()
        if len(points):
            vtk_points.SetData(numpy_support.numpy_to_vtk(self.visible_points, deep=True))
            cells.SetData(numpy_support.numpy_to_vtkIdTypeArray(np.arange(len(points) + 1, dtype=np.int64), deep=True),
                          numpy_support.numpy_to_vtkIdTypeArray(np.arange(len(points), dtype=np.int64), deep=True))
        self.polydata.SetPoints(vtk_points)
        self.polydata.SetVerts(cells)
        self.recolor(render)

    def recolor(self, render=True):
        mode = self.colour_box.currentData() if self.panel_alive else "height"
        colours = np.zeros((0, 3), np.uint8)
        if len(self.visible_ids):
            if mode == "rgb" and self.colours is not None:
                colours = self.colours[self.visible_ids].copy()
            else:
                values = (self.visible_points[:, 2] if mode in (None, "height")
                          else self.cloud.table[mode][self.visible_ids].astype(np.float64))
                low, high = np.percentile(values, [1, 99])
                colours = ramp(values, low, high)
            colours[np.isin(self.visible_ids, self.selection, assume_unique=True)] = SELECTED_RGB
        array = numpy_support.numpy_to_vtk(np.ascontiguousarray(colours), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        array.SetName("rgb")
        self.polydata.GetPointData().SetScalars(array)
        self.polydata.Modified()
        self.changed()
        if render:
            self.viewport.render()

    def _style_changed(self, *_):
        self.actor.GetProperty().SetPointSize(self.point_size.value())
        self.viewport.render()

    def look_from(self, direction, up):
        bounds = self.polydata.GetBounds() if len(self.visible_ids) else (-1, 1, -1, 1, -1, 1)
        self.viewport.look_from(direction, up, bounds)

    def reset_range(self):
        self.ranges.reset()
        self.refresh()

    def set_tool(self, name):
        self.tool = name
        self.hover_actor.VisibilityOff()
        self.viewport.set_default_cursor(Qt.ArrowCursor if name == "view" else Qt.CrossCursor)
        self.viewport.render()

    def remove(self, ids, label):
        removed = self.cloud.remove(ids)
        if removed:
            self.refresh()
            self.status(self.tr("status_removed", what=label, n=removed))
        else:
            self.status(self.tr("status_no_change", what=label))

    def select(self, ids, mode="add"):
        ids = np.intersect1d(np.asarray(ids, np.int64), self.visible_ids)
        if mode == "remove":
            self.selection = np.setdiff1d(self.selection, ids)
        elif mode == "replace":
            self.selection = ids
        else:
            self.selection = np.union1d(self.selection, ids)
        self.recolor()

    def delete_selection(self):
        if len(self.selection):
            self.remove(self.selection, self.tr("delete_selection"))

    def clear_selection(self):
        self.select(np.zeros(0, np.int64), "replace")

    def select_all(self):
        self.select(self.visible_ids, "replace")

    def invert_selection(self):
        self.select(np.setdiff1d(self.visible_ids, self.selection, assume_unique=True), "replace")

    def _select_filtered(self, local):
        self.select(self.visible_ids[local], "replace")
        self.status(self.tr("status_filter", n=len(self.selection)), 10000)

    def select_outliers(self):
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            local = cloud.statistical_outliers(self.visible_points, self.neighbours.value(), self.ratio.value())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._select_filtered(local)

    def select_sparse(self):
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            local = cloud.sparse_points(self.visible_points, self.sparse_radius.value(), self.sparse_min.value())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._select_filtered(local)

    def thin_out(self):
        local = cloud.downsample_surplus(self.visible_points, self.leaf.value())
        self.remove(self.visible_ids[local], self.tr("thin_out"))

    def _box_changed(self, *_):
        low, high = self.box.bounds()
        self.box_source.SetBounds(low[0], high[0], low[1], high[1], low[2], high[2])
        self.box_actor.SetVisibility(self.show_box.isChecked())
        self.box_gizmo.set_box(low, high)
        self.box_gizmo.show(self.show_box.isChecked())
        self.viewport.render()

    def _box_dragged(self, low, high):
        self.box.set(low, high)
        self.box_source.SetBounds(low[0], high[0], low[1], high[1], low[2], high[2])
        self.status(self.tr("status_box", x0=low[0], x1=high[0], y0=low[1], y1=high[1], z0=low[2], z1=high[2]), 0)

    def _update_slice_gizmo(self):
        values = self.slice.values()
        self.slice_gizmo.update(values["axis"], values["position"], self.data_bounds)
        self.slice_gizmo.show(values["on"])

    def _slice_changed(self):
        values = self.slice.values()
        axis = values["axis"]
        low, high = self.data_bounds
        mode = (values["on"], axis)
        if values["on"] and (mode != self._previous_mode or not low[axis] <= values["position"] <= high[axis]):
            self.slice.set_position(float((low[axis] + high[axis]) / 2))
        self._previous_mode = mode
        self._update_slice_gizmo()
        self.refresh()
        self._report_slice()

    def _slice_dragged(self, position):
        self.slice.set_position(position)
        self._refresh_timer.start()
        self._report_slice()

    def _report_slice(self):
        values = self.slice.values()
        if values["on"]:
            self.status(self.tr("status_slice", axis=AXIS_NAMES[values["axis"]],
                                op="≤" if values["keep"] == "below" else "≥", pos=values["position"], n=self.hidden), 0)

    def restore_view(self):
        self.slice.enabled.blockSignals(True)
        self.slice.enabled.setChecked(False)
        self.slice.enabled.blockSignals(False)
        self.slice_gizmo.show(False)
        self.ranges.reset()
        self.refresh()
        self.status(self.tr("status_view_restored"))

    def _inside_box(self):
        low, high = self.box.bounds()
        if not len(self.visible_points):
            return np.zeros(0, bool)
        return np.all((self.visible_points >= low) & (self.visible_points <= high), axis=1)

    def box_from_selection(self):
        if len(self.selection):
            points = self.cloud.xyz[self.selection]
            self.box.set(points.min(axis=0), points.max(axis=0))
            self.show_box.setChecked(True)
            self._box_changed()

    def box_select(self):
        self.show_box.setChecked(True)
        self.select(self.visible_ids[self._inside_box()])

    def box_delete(self):
        self.show_box.setChecked(True)
        self.remove(self.visible_ids[self._inside_box()], self.tr("box_delete"))

    def box_delete_outside(self):
        self.show_box.setChecked(True)
        self.remove(self.visible_ids[~self._inside_box()], self.tr("box_delete_outside"))

    def _ask_size(self):
        xyz, _ = self.cloud.surviving()
        if not len(xyz):
            return None, None
        guess = formats.estimate_resolution(xyz)
        answer = ask_numbers(self.window, self.tr("voxel_size_title"), [(self.tr("voxel_size_cloud"), guess, 1e-4, 1e3, 4)])
        return (xyz, answer[0]) if answer else (None, None)

    def to_voxels(self):
        xyz, size = self._ask_size()
        if size is None:
            return None
        return VOXEL, (convert.points_to_voxels(xyz, size), size)

    def to_grid(self):
        xyz, size = self._ask_size()
        if size is None:
            return None
        band = ask_numbers(self.window, self.tr("band_title"), [
            (self.tr("band_low"), float(xyz[:, 2].min()), -RANGE_LIMIT, RANGE_LIMIT, 3),
            (self.tr("band_high"), float(xyz[:, 2].max()), -RANGE_LIMIT, RANGE_LIMIT, 3)])
        if band is None:
            return None
        return GRID, convert.voxels_to_grid(convert.points_to_voxels(xyz, size), size, *sorted(band))

    def _pick(self, x, y):
        origin, direction = self.viewport.eye_ray(x, y)
        index = cloud.pick_along_ray(origin, direction, self.visible_points, PICK_PIXELS * self.viewport.pixel_angle())
        return None if index is None else self.visible_points[index]

    def _brush_ids(self, centre):
        if self._tree is None:
            from scipy.spatial import cKDTree
            self._tree = cKDTree(self.visible_points)
        return self.visible_ids[np.asarray(self._tree.query_ball_point(centre, self.radius.value()), np.int64)]

    def clear_ruler(self):
        self.ruler.clear()
        self.measurement = None
        if self.panel_alive:
            self.ruler_label.setText(self.tr("ruler_hint"))
        self.viewport.render()

    def _ruler_text(self, result):
        short = self.tr("ruler_short", **result)
        detail = self.tr("ruler_detail_cloud", **result)
        return short, detail

    def adjust_brush(self, step):
        self.radius.setValue(self.radius.value() * (1.25 if step > 0 else 0.8))

    def zoom(self, factor):
        self.viewport.zoom(factor)

    def _ruler_target(self, point):
        """Second ruler point; with Shift held it is locked to the dominant axis from the first point."""
        if self.ruler.pending and self.viewport.interactor.GetShiftKey():
            delta = point - self.ruler.first
            locked = np.zeros(3)
            axis = int(np.argmax(np.abs(delta)))
            locked[axis] = delta[axis]
            return self.ruler.first + locked
        return point

    def _measure_hover(self, x, y):
        point = self.measure_point(x, y)
        if point is None:
            if self.hover_actor.GetVisibility():
                self.hover_actor.VisibilityOff()
                self.viewport.render()
            return
        point = self._ruler_target(point)
        self.status(self.tr("status_hover", x=point[0], y=point[1], z=point[2]), 0)
        if self.ruler.pending:
            short, detail = self._ruler_text(measure(self.ruler.first, point))
            self.ruler.preview(point, short)
        self.viewport.render()

    def _measure_click(self, x, y):
        point = self.measure_point(x, y)
        if point is None:
            return
        point = self._ruler_target(point)
        if self.ruler.pending:
            self.measurement = measure(self.ruler.first, point)
            short, detail = self._ruler_text(self.measurement)
            self.ruler.finish(point, short)
            self.ruler_label.setText(detail)
            self.status(detail, 0)
        else:
            self.ruler.marker_size = self._marker_size()
            self.ruler.start(point)
            self.ruler_label.setText(self.tr("ruler_second"))
            self.status(self.tr("ruler_second"), 0)
        self.viewport.render()

    def measure_point(self, x, y):
        """Point under the cursor, marked with a small sphere so it is clear what will be measured."""
        point = self._pick(x, y) if len(self.visible_points) else None
        if point is not None:
            self.hover_source.SetCenter(*point)
            self.hover_source.SetRadius(self._marker_size() * 2.5)
            self.hover_actor.GetProperty().SetColor(*RULER_RGB)
            self.hover_actor.VisibilityOn()
        return point

    def _marker_size(self):
        low, high = self.data_bounds
        return max(float(np.max(high - low)) * 0.006, 1e-3)

    def _hover(self, x, y):
        if self.tool == "view":
            return
        if self.tool == "measure":
            self._measure_hover(x, y)
            return
        centre = None if not len(self.visible_points) else self._pick(x, y)
        if centre is None:
            if self.hover_actor.GetVisibility():
                self.hover_actor.VisibilityOff()
                self.viewport.render()
            return
        self.hover_source.SetCenter(*centre)
        self.hover_source.SetRadius(self.radius.value())
        self.hover_actor.GetProperty().SetColor(*TOOL_RGB[self.tool])
        self.hover_actor.VisibilityOn()
        self.status(self.tr("status_hover", x=centre[0], y=centre[1], z=centre[2]), 0)
        self.viewport.render()

    def _click(self, x, y, ctrl):
        if self.tool == "view" or not len(self.visible_points):
            return
        if self.tool == "measure":
            self._measure_click(x, y)
            return
        centre = self._pick(x, y)
        if centre is None:
            return
        ids = self._brush_ids(centre)
        if self.tool == "select":
            self.select(ids, "remove" if ctrl else "add")
        else:
            self.remove(ids, self.tr("tool_delete"))
        self._hover(x, y)

    def _right_click(self, x, y):
        if not len(self.selection) or not len(self.visible_points):
            return
        centre = self._pick(x, y)
        if centre is not None:
            before = len(self.selection)
            self.select(self._brush_ids(centre), "remove")
            self.status(self.tr("status_deselected", n=before - len(self.selection)))

    def _rectangle(self, corner_a, corner_b, subtract):
        self.hover_actor.VisibilityOff()
        chosen = self.viewport.rectangle_hits(self.visible_points, corner_a, corner_b, self.front_only.isChecked(),
                                              self.tolerance.value())
        self.select(self.visible_ids[chosen], "remove" if subtract else "add")
        self.status(self.tr("status_rectangle", n=len(chosen), t=len(self.selection)))
