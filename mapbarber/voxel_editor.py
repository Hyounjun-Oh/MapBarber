"""Editor for occupied-voxel maps (OctoMap octrees and voxel archives)."""
import numpy as np
import vtk
from vtk.util import numpy_support

from . import convert, formats
from .editor import Editor
from .formats import CLOUD, GRID, VOXEL
from .qt import QtCore, QtWidgets
from .scene import VIEWS, Viewport, ramp
from .voxels import EMPTY, VoxelMap, in_range, pack, ray_pick, unpack
from .widgets import RANGE_LIMIT, AxisRanges, ask_numbers, button, int_spin, spin

Qt = QtCore.Qt
SELECTED_RGB = np.array([255, 40, 200], np.uint8)
ADDED_RGB = np.array([245, 245, 245], np.uint8)
TOOL_RGB = {"select": (1.0, 0.2, 0.8), "delete": (1.0, 0.15, 0.1), "add": (0.2, 1.0, 0.3)}
MAX_FILL_CELLS = 2_000_000
DEFAULTS = {"brush": 1, "plane": 0.0, "front_only": True, "tolerance": 0.10, "island": 20,
            "box": [(-0.2, 0.2)] * 3, "show_box": False, "range": [(-RANGE_LIMIT, RANGE_LIMIT)] * 3}


class VoxelEditor(Editor):
    kind = VOXEL
    tools = (("view", "1"), ("select", "2"), ("delete", "3"), ("add", "4"))
    export_filters = (("OctoMap binary", "bt"), ("OctoMap full", "ot"), ("Voxel archive", "npz"),
                      ("PCD point cloud", "pcd"), ("PLY point cloud", "ply"), ("XYZ text", "xyz"), ("CSV text", "csv"),
                      ("NumPy array", "npy"))

    def __init__(self, window):
        super().__init__(window)
        self.map = VoxelMap()
        self.selection = EMPTY
        self.visible_keys = EMPTY
        self.visible_centers = np.zeros((0, 3))
        self.height_range = (0.0, 1.0)
        self.panel_values = dict(DEFAULTS)
        self.viewport = Viewport(window, self._click, self._hover, self._rectangle)
        self.widget = self.viewport.widget

        self.cube = vtk.vtkCubeSource()
        self.points = vtk.vtkPolyData()
        mapper = vtk.vtkGlyph3DMapper()
        mapper.SetSourceConnection(self.cube.GetOutputPort())
        mapper.SetInputData(self.points)
        mapper.ScalingOff()
        mapper.OrientOff()
        mapper.SetScalarModeToUsePointData()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetAmbient(0.35)
        actor.GetProperty().SetDiffuse(0.75)
        self.viewport.renderer.AddActor(actor)
        self.hover_source, self.hover_actor = self.viewport.outline((1, 1, 1), 2.5)
        self.box_source, self.box_actor = self.viewport.outline((1.0, 0.85, 0.1))

    @property
    def dirty(self):
        return self.map.dirty

    def changes(self):
        return self.map.changes()

    def load(self, path):
        keys, resolution = formats.load_voxels(path)
        self.set_document((keys, resolution), path, formats.detect(path))

    def set_document(self, payload, path=None, fmt=None):
        keys, resolution = payload
        self.map = VoxelMap(keys, resolution)
        self.path, self.format = path, fmt
        self.selection = EMPTY
        size = self.map.resolution
        for setter in (self.cube.SetXLength, self.cube.SetYLength, self.cube.SetZLength):
            setter(size * 0.94)
        extent = 1.0
        if len(self.map):
            cells = unpack(self.map.occupied)
            extent = float((cells.max(axis=0) - cells.min(axis=0)).max() + 1) * size
        self.viewport.set_axes_length(max(0.08 * extent, 4 * size))
        self.panel_values["range"] = DEFAULTS["range"]
        if self.panel_alive:
            self.ranges.reset()
            for box in self._step_boxes():
                box.setSingleStep(size)
        self.refresh(render=False)

    def save(self, path, fmt=None):
        if not len(self.map):
            raise ValueError(self.tr("empty_map"))
        formats.save_voxels(path, self.map.occupied, self.map.resolution, fmt)
        self.map.mark_saved()
        self.recolor()

    def undo(self):
        if self.map.undo():
            self.refresh()

    def redo(self):
        if self.map.redo():
            self.refresh()

    def summary(self):
        added, removed = self.map.changes()
        return self.tr("voxel_counts", n=len(self.map), v=len(self.visible_keys), a=added, r=removed, s=len(self.selection),
                       res=f"{self.map.resolution:g}")

    def info(self):
        return {"voxels": len(self.map), "resolution": self.map.resolution}

    def build_panel(self):
        t, values, W = self.tr, self.panel_values, QtWidgets
        step = self.map.resolution
        panel = W.QWidget()
        layout = W.QVBoxLayout(panel)

        group = W.QGroupBox(t("brush"))
        form = W.QFormLayout(group)
        self.brush = int_spin(1, 31, values["brush"], t("cells"))
        self.brush.setSingleStep(2)
        self.brush.setToolTip(t("brush_tip"))
        form.addRow(t("brush_size"), self.brush)
        self.plane = spin(-RANGE_LIMIT, RANGE_LIMIT, values["plane"], step)
        self.plane.setToolTip(t("plane_tip"))
        form.addRow(t("work_plane"), self.plane)
        layout.addWidget(group)

        group = W.QGroupBox(t("rectangle"))
        form = W.QFormLayout(group)
        self.front_only = W.QCheckBox(t("front_only"))
        self.front_only.setChecked(values["front_only"])
        form.addRow(self.front_only)
        self.tolerance = spin(0.0, RANGE_LIMIT, values["tolerance"], step)
        form.addRow(t("depth_tolerance"), self.tolerance)
        row = W.QHBoxLayout()
        row.addWidget(button(t("delete_selection"), self.delete_selection))
        row.addWidget(button(t("clear_selection"), self.clear_selection))
        form.addRow(row)
        layout.addWidget(group)

        group = W.QGroupBox(t("islands"))
        form = W.QFormLayout(group)
        self.island_size = int_spin(1, 1_000_000, values["island"], t("voxels_suffix"))
        form.addRow(t("island_size"), self.island_size)
        form.addRow(button(t("select_islands"), self.select_islands, t("islands_tip")))
        layout.addWidget(group)

        group = W.QGroupBox(t("box"))
        grid = W.QGridLayout(group)
        self.box = AxisRanges(grid, 0, values["box"], step, self._box_changed)
        self.show_box = W.QCheckBox(t("show_box"))
        self.show_box.setChecked(values["show_box"])
        self.show_box.toggled.connect(self._box_changed)
        grid.addWidget(self.show_box, 3, 0, 1, 2)
        grid.addWidget(button(t("box_from_selection"), self.box_from_selection), 3, 2)
        grid.addWidget(button(t("box_select"), self.box_select), 4, 0, 1, 3)
        grid.addWidget(button(t("box_delete"), self.box_delete), 5, 0, 1, 3)
        grid.addWidget(button(t("box_fill"), self.box_fill, t("box_fill_tip")), 6, 0, 1, 3)
        layout.addWidget(group)

        group = W.QGroupBox(t("visible_range"))
        group.setToolTip(t("range_tip"))
        grid = W.QGridLayout(group)
        self.ranges = AxisRanges(grid, 0, values["range"], step, lambda *_: self.refresh())
        grid.addWidget(button(t("show_all"), self.reset_range), 3, 0, 1, 3)
        layout.addWidget(group)

        layout.addStretch(1)
        legend = W.QLabel(t("voxel_legend"))
        legend.setWordWrap(True)
        legend.setStyleSheet("color: gray;")
        layout.addWidget(legend)
        self._box_changed()
        return panel

    def _step_boxes(self):
        boxes = [self.plane, self.tolerance]
        for ranges in (self.box, self.ranges):
            boxes += [b for pair in ranges.pairs for b in pair]
        return boxes

    def store_panel(self):
        if self.panel_alive:
            self.panel_values = {"brush": self.brush.value(), "plane": self.plane.value(),
                                 "front_only": self.front_only.isChecked(), "tolerance": self.tolerance.value(),
                                 "island": self.island_size.value(), "box": self.box.values(),
                                 "show_box": self.show_box.isChecked(), "range": self.ranges.values()}

    def view_actions(self):
        return [(self.tr(f"view_{name}"), lambda d=direction, u=up: self.look_from(d, u)) for name, direction, up in VIEWS]

    def selection_actions(self):
        return {"delete": self.delete_selection, "select_all": self.select_all, "invert": self.invert_selection,
                "clear": self.clear_selection}

    def conversions(self):
        return [(self.tr("to_grid"), self.to_grid), (self.tr("to_cloud"), self.to_cloud)]

    def activate(self):
        self.viewport.initialize()
        self.look_from(*VIEWS[3][1:])

    def capture(self):
        return self.viewport.capture()

    def refresh(self, render=True):
        """Rebuild the visible voxel list after the voxel set or the visible range changed."""
        all_centers = (unpack(self.map.occupied) + 0.5) * self.map.resolution
        low, high = self.ranges.bounds() if self.panel_alive else (-np.inf, np.inf)
        shown = np.all((all_centers >= low) & (all_centers <= high), axis=1) if len(all_centers) else np.zeros(0, bool)
        self.visible_keys = self.map.occupied[shown]
        self.visible_centers = np.ascontiguousarray(all_centers[shown])
        self.selection = self.selection[np.isin(self.selection, self.visible_keys, assume_unique=True)]
        if len(all_centers):
            z_low, z_high = np.percentile(all_centers[:, 2], [0.5, 99.5])
            self.height_range = (float(z_low), float(max(z_high, z_low + self.map.resolution)))
        points = vtk.vtkPoints()
        if len(self.visible_centers):
            points.SetData(numpy_support.numpy_to_vtk(self.visible_centers, deep=True))
        self.points.SetPoints(points)
        self.recolor(render)

    def recolor(self, render=True):
        colors = np.zeros((0, 3), np.uint8)
        if len(self.visible_centers):
            colors = ramp(self.visible_centers[:, 2], *self.height_range)
            colors[~np.isin(self.visible_keys, self.map.saved, assume_unique=True)] = ADDED_RGB
            colors[np.isin(self.visible_keys, self.selection, assume_unique=True)] = SELECTED_RGB
        array = numpy_support.numpy_to_vtk(np.ascontiguousarray(colors), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        array.SetName("rgb")
        self.points.GetPointData().SetScalars(array)
        self.points.Modified()
        self.changed()
        if render:
            self.viewport.render()

    def look_from(self, direction, up):
        bounds = self.points.GetBounds() if len(self.visible_centers) else (-1, 1, -1, 1, -1, 1)
        self.viewport.look_from(direction, up, bounds)

    def reset_range(self):
        self.ranges.reset()
        self.refresh()

    def set_tool(self, name):
        self.tool = name
        self.hover_actor.VisibilityOff()
        self.widget.setCursor(Qt.ArrowCursor if name == "view" else Qt.CrossCursor)
        self.viewport.render()

    def edit(self, add=None, remove=None, label=""):
        added, removed = self.map.apply(add=add, remove=remove)
        if added or removed:
            self.refresh()
            self.status(self.tr("status_edit", what=label, a=added, r=removed))
        else:
            self.status(self.tr("status_no_change", what=label))

    def select(self, keys, mode="add"):
        keys = np.intersect1d(np.asarray(keys, np.int64), self.visible_keys)
        if mode == "remove":
            self.selection = np.setdiff1d(self.selection, keys)
        elif mode == "replace":
            self.selection = keys
        else:
            self.selection = np.union1d(self.selection, keys)
        self.recolor()

    def delete_selection(self):
        if len(self.selection):
            self.edit(remove=self.selection, label=self.tr("delete_selection"))

    def clear_selection(self):
        self.select(EMPTY, "replace")

    def select_all(self):
        self.select(self.visible_keys, "replace")

    def invert_selection(self):
        self.select(np.setdiff1d(self.visible_keys, self.selection, assume_unique=True), "replace")

    def select_islands(self):
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            keys, count = self.map.islands(self.island_size.value())
        except MemoryError as error:
            QtWidgets.QMessageBox.warning(self.window, self.tr("islands"), str(error))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.select(keys, "replace")
        self.status(self.tr("status_islands", n=count, m=len(self.selection)), 10000)

    def _box_changed(self, *_):
        low, high = self.box.bounds()
        self.box_source.SetBounds(low[0], high[0], low[1], high[1], low[2], high[2])
        self.box_actor.SetVisibility(self.show_box.isChecked())
        self.viewport.render()

    def _keys_in_box(self):
        if not len(self.visible_centers):
            return EMPTY
        low, high = self.box.bounds()
        return self.visible_keys[np.all((self.visible_centers >= low) & (self.visible_centers <= high), axis=1)]

    def set_box(self, low, high):
        self.box.set(low, high)
        self.show_box.setChecked(True)
        self._box_changed()

    def box_from_selection(self):
        if len(self.selection):
            cells = unpack(self.selection)
            self.set_box(cells.min(axis=0) * self.map.resolution, (cells.max(axis=0) + 1) * self.map.resolution)

    def box_select(self):
        self.show_box.setChecked(True)
        self.select(self._keys_in_box())

    def box_delete(self):
        self.show_box.setChecked(True)
        self.edit(remove=self._keys_in_box(), label=self.tr("box_delete"))

    def box_fill(self):
        self.show_box.setChecked(True)
        size = self.map.resolution
        low, high = self.box.bounds()
        first = np.ceil(low / size - 0.5 - 1e-6).astype(np.int64)
        last = np.floor(high / size - 0.5 + 1e-6).astype(np.int64)
        total = float(np.prod(np.maximum(last - first + 1, 0).astype(np.float64)))
        if total == 0:
            self.status(self.tr("status_box_empty"))
            return
        if total > MAX_FILL_CELLS:
            QtWidgets.QMessageBox.warning(self.window, self.tr("box_fill"), self.tr("box_too_large", n=int(total)))
            return
        cells = np.stack(np.meshgrid(*[np.arange(a, b + 1) for a, b in zip(first, last)], indexing="ij"), -1).reshape(-1, 3)
        self.edit(add=pack(cells[in_range(cells)]), label=self.tr("box_fill"))

    def to_cloud(self):
        return CLOUD, (convert.voxels_to_points(self.map.occupied, self.map.resolution), None)

    def to_grid(self):
        if not len(self.map):
            return None
        z = (unpack(self.map.occupied)[:, 2] + 0.5) * self.map.resolution
        band = ask_numbers(self.window, self.tr("band_title"), [
            (self.tr("band_low"), float(z.min()), -RANGE_LIMIT, RANGE_LIMIT, 3),
            (self.tr("band_high"), float(z.max()), -RANGE_LIMIT, RANGE_LIMIT, 3)])
        if band is None:
            return None
        return GRID, convert.voxels_to_grid(self.map.occupied, self.map.resolution, *sorted(band))

    def target_cells(self, x, y):
        """Cells the active tool would change at a screen position (None when nothing is under the cursor)."""
        size = self.map.resolution
        width = self.brush.value()
        offsets = np.arange(width) - width // 2
        origin, direction = self.viewport.ray(x, y)
        hit = ray_pick(origin, direction, self.visible_centers, size / 2.0)
        if hit is None:
            if self.tool != "add" or abs(direction[2]) < 1e-9:
                return None
            distance = (self.plane.value() - origin[2]) / direction[2]
            if distance <= 0:
                return None
            point = origin + distance * direction
            base = np.array([np.floor(point[0] / size), np.floor(point[1] / size),
                             np.floor(self.plane.value() / size + 1e-6)], np.int64)
            axis = 2
        else:
            index, axis, sign = hit
            base = unpack(self.visible_keys[index:index + 1])[0]
            if self.tool == "add":
                base[axis] += sign
        if self.tool == "add":
            u, v = [a for a in range(3) if a != axis]
            cells = np.repeat(base[None, :], width * width, axis=0)
            grid_u, grid_v = np.meshgrid(offsets, offsets, indexing="ij")
            cells[:, u] += grid_u.ravel()
            cells[:, v] += grid_v.ravel()
        else:
            cells = base[None, :] + np.stack(np.meshgrid(offsets, offsets, offsets, indexing="ij"), -1).reshape(-1, 3)
        return cells[in_range(cells)]

    def _hover(self, x, y):
        if self.tool == "view":
            return
        cells = self.target_cells(x, y)
        if cells is None or not len(cells):
            if self.hover_actor.GetVisibility():
                self.hover_actor.VisibilityOff()
                self.viewport.render()
            return
        size = self.map.resolution
        low, high = cells.min(axis=0) * size, (cells.max(axis=0) + 1) * size
        self.hover_source.SetBounds(low[0], high[0], low[1], high[1], low[2], high[2])
        self.hover_actor.GetProperty().SetColor(*TOOL_RGB[self.tool])
        self.hover_actor.VisibilityOn()
        middle = (low + high) / 2
        self.status(self.tr("status_hover", x=middle[0], y=middle[1], z=middle[2]), 0)
        self.viewport.render()

    def _click(self, x, y, ctrl):
        if self.tool == "view":
            return
        cells = self.target_cells(x, y)
        if cells is None or not len(cells):
            return
        keys = pack(cells)
        if self.tool == "select":
            self.select(keys, "remove" if ctrl else "add")
        elif self.tool == "delete":
            self.edit(remove=np.intersect1d(keys, self.visible_keys), label=self.tr("tool_delete"))
        else:
            self.edit(add=keys, label=self.tr("tool_add"))
        self._hover(x, y)

    def _rectangle(self, corner_a, corner_b, subtract):
        self.hover_actor.VisibilityOff()
        chosen = self.viewport.rectangle_hits(self.visible_centers, corner_a, corner_b, self.front_only.isChecked(),
                                              self.tolerance.value())
        self.select(self.visible_keys[chosen], "remove" if subtract else "add")
        self.status(self.tr("status_rectangle", n=len(chosen), t=len(self.selection)))
