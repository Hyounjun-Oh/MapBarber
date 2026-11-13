"""Editor for point clouds: points are removed, never moved, and every per-point field is kept on save."""
import os
import time

import numpy as np
import vtk
from vtk.util import numpy_support

from . import cloud, convert, formats, frames, labels, loss
from .chunk_view import PointChunkView
from .editor import Editor
from .formats import CLOUD, GRID, VOXEL
from .grid import FREE, UNKNOWN
from .label_tools import Labelling
from .timeline import LabelBar, TimelineBar
from .gizmo import AXIS_NAMES, SLICE_DEFAULTS, BoxGizmo, SliceControls, SliceGizmo, Snap
from .qt import QtCore, QtWidgets
from .measure_panel import MeasureOverlay
from .ruler import RULER_RGB, Ruler3D, measure
from .scene import VIEWS, Viewport, ramp
from .voxels import ray_boxes
from .widgets import ask_numbers, AxisRanges, button, danger_button, int_spin, RANGE_LIMIT, Section, select_button, spin

Qt = QtCore.Qt
SELECTED_RGB = np.array([255, 40, 200], np.uint8)
TOOL_RGB = {"select": (1.0, 0.2, 0.8), "delete": (1.0, 0.15, 0.1), "label": (0.3, 0.85, 0.45)}
BRUSH_TOOLS = ("select", "delete", "label", "smart")
LABEL_MODES = ("label", "instance")
PICK_PIXELS = 6
MAX_LEVEL = 4
POINT_BUDGET = 8_000_000
CACHE_BUDGET = 40_000_000
COLOUR_FIELDS_SKIPPED = {"x", "y", "z", "rgb", "rgba", "red", "green", "blue", "alpha", "r", "g", "b", "a"}
DEFAULTS = {"ground_cell": 0.5, "ground_slope": 15.0, "ground_height": 0.15, "radius": 0.10, "point_size": 3, "colour": "height", "front_only": True, "tolerance": 0.10,
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


EDIT_TOOLS = (("view", "H"), ("select", "V"), ("delete", "E"), ("measure", "I"))
LABEL_TOOLS = (("view", "H"), ("select", "V"), ("label", "B"), ("smart", "W"), ("measure", "I"))


class CloudEditor(Labelling, Editor):
    kind = CLOUD
    export_filters = (("PCD point cloud", "pcd"), ("PLY point cloud", "ply"), ("LAS point cloud", "las"),
                      ("LAZ point cloud", "laz"), ("XYZ text", "xyz"), ("CSV text", "csv"), ("LiDAR scan", "bin"),
                      ("NumPy array", "npy"), ("NumPy archive", "npz"))

    def __init__(self, window):
        super().__init__(window)
        self.cloud = cloud.PointCloud(np.zeros((0, 3)))
        self.origin = None
        self.colours = None
        self.selected = np.zeros(0, bool)
        self.chunks = cloud.PointChunks(self.cloud.xyz, self.cloud.alive)
        self.shown_counts = {}
        self.panel_values = dict(DEFAULTS)
        self.viewport = Viewport(window, self._click, self._hover, self._rectangle, self._right_click)
        self.widget = self.viewport.widget
        self.view = PointChunkView(self.viewport.renderer)
        self._colour_range = (0.0, 1.0)
        self._pending = []
        self._closed = False
        self._level_timer = QtCore.QTimer()
        self._level_timer.setSingleShot(True)
        self._level_timer.setInterval(30)
        self._level_timer.timeout.connect(self.update_levels)
        self._slice_timer = QtCore.QTimer()
        self._slice_timer.setSingleShot(True)
        self._slice_timer.setInterval(0)
        self._slice_timer.timeout.connect(self._refine)
        self._camera_watch = self.viewport.renderer.GetActiveCamera().AddObserver(
            "ModifiedEvent", lambda *_: None if self._closed else self._level_timer.start())
        self.hover_source, self.hover_actor = self.viewport.wire_sphere((1, 1, 1))
        self.hover_actor.GetProperty().SetRepresentationToSurface()
        self.hover_actor.GetProperty().SetOpacity(0.22)
        self._selection_steps = []
        self.preview = vtk.vtkPolyData()
        preview_mapper = vtk.vtkPolyDataMapper()
        preview_mapper.SetInputData(self.preview)
        self.preview_actor = vtk.vtkActor()
        self.preview_actor.SetMapper(preview_mapper)
        self.preview_actor.GetProperty().SetRenderPointsAsSpheres(True)
        self.preview_actor.GetProperty().LightingOff()
        self.preview_actor.PickableOff()
        self.preview_actor.VisibilityOff()
        self.viewport.renderer.AddActor(self.preview_actor)
        self.box_source, self.box_actor = self.viewport.outline((1.0, 0.85, 0.1))
        self.box_gizmo = BoxGizmo(self.viewport, self._box_dragged, Snap(0.01))
        self.slice_gizmo = SliceGizmo(self.viewport, self._slice_dragged, Snap(0.01))
        self.viewport.gizmos = [self.slice_gizmo, self.box_gizmo]
        self.ruler = Ruler3D(self.viewport.renderer)
        self.overlay = MeasureOverlay(self.viewport.widget, lambda entry: self._ruler_text(entry)[1],
                                      self._show_measurement, lambda: self.tr)
        self.label_bar = LabelBar(self.viewport.widget, lambda: self.tr, self._protect_from_bar)
        self.overlay.below = self.label_bar
        self.timeline = TimelineBar(lambda first, last: self.show_frames(range(first, last + 1)), self.step_frame,
                                    lambda: self.tr, lambda direction, whole: self.step_frame(direction, whole),
                                    lambda name: self._anchor_changed())
        self.timeline.hide()
        self.widget = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(self.widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.viewport.widget, 1)
        column.addWidget(self.timeline)
        self.viewport.band_allowed = lambda: self.tool != "measure"
        self.viewport.paint_allowed = lambda: self.tool in BRUSH_TOOLS
        self.viewport.on_paint = self._paint
        self.viewport.on_paint_end = self._paint_end
        self._stroke = None
        self.measurement = None
        self.data_bounds = (np.zeros(3), np.ones(3))
        self._previous_mode = (False, 2)
        self._refresh_timer = QtCore.QTimer()
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)
        self._refresh_timer.timeout.connect(self.refresh)
        self._init_labels()

    @property
    def tools(self):
        return LABEL_TOOLS if self.label_mode else EDIT_TOOLS

    @property
    def dirty(self):
        return self.cloud.dirty or self.label_dirty()

    def read(self, path):
        """A file gives (xyz, table); a folder of frames gives a Sequence with its first frame already read."""
        if os.path.isdir(path):
            sequence = frames.Sequence(path)
            sequence.load(0)
            return sequence
        return formats.read_cloud(path)

    def set_document(self, payload, path=None, fmt=None, progress=None):
        """payload: a frames.Sequence, or (xyz, table[, origin]).

        origin describes where converted points came from: the voxel size of the map, and the labels they carry.
        """
        self.path, self.format = path, fmt
        self.frame_store, self.frame_dirty, self.frame_ids = {}, set(), []
        if isinstance(payload, frames.Sequence):
            self.sequence, self.origin, self.format = payload, None, formats.FRAMES
            self.switch_label_mode(True)
            self.panel_values.update(stop_bends=False, gap=0.3, object_gap=0.5)
            if os.path.isfile(payload.class_file):
                self.classes = labels.ClassList.load(payload.class_file)
            elif payload.layout != "folder":
                self.classes = labels.ClassList("semantickitti")
            self.active_class = self.classes.numbers()[0] if len(self.classes) else labels.UNLABELED
            self.show_frames([0], progress, store=False, fresh=True)
        else:
            self.sequence = None
            xyz, table = payload[:2]
            self.origin = payload[2] if len(payload) > 2 else None
            self._install(xyz, table, *self._initial_labels(xyz, table, path), progress, True)
        self.offer_recovery()

    def _install(self, xyz, table, cls, inst, progress=None, fresh=True):
        """Make a cloud and its labels the content of the editor (a whole document, or the frames now on screen)."""
        self.cloud = cloud.PointCloud(xyz, table)
        self.colours = point_colours(table)
        self.selected = np.zeros(len(self.cloud.xyz), bool)
        self._selection_steps = []
        self.chunks = cloud.PointChunks(self.cloud.xyz, self.cloud.alive)
        self.view.clear()
        if len(self.chunks):
            self.data_bounds = (self.chunks.low.min(axis=0), self.chunks.high.max(axis=0))
        extent = float((self.data_bounds[1] - self.data_bounds[0]).max()) if len(self.chunks) else 1.0
        self.viewport.set_axes_length(max(0.08 * extent, 1e-3))
        self._above = {}
        self._reset_labels(len(self.cloud.xyz), cls, inst, fresh)
        if fresh:
            self.clear_ruler()
            self.panel_values["range"] = DEFAULTS["range"]
        if self.panel_alive:
            self.panel_values["colour"] = self.colour_box.currentData() or self.panel_values["colour"]
        if self.panel_values["colour"] not in self.colour_modes():
            self.panel_values["colour"] = "height"
        if self.panel_alive:
            if fresh:
                self.ranges.reset()
            self._fill_colour_modes()
        self.refresh(render=not fresh, progress=progress)

    def export(self, path, fmt=None):
        if self.sequence is not None and os.path.isdir(path):
            self._save_frames()
        else:
            self._write_labelled(path, fmt)

    def losses(self, fmt):
        pending = self.pending_count()
        suggested = [(loss.PENDING, str(pending))] if pending else []
        if fmt == formats.FRAMES:
            return suggested
        table = self.cloud.table
        if self.labels.any and fmt in ("pcd", "ply", "xyz", "las"):
            table = formats.with_labels(self.cloud.xyz[:1], None if table is None else table[:1],
                                        self.labels.cls[:1], self.labels.inst[:1] if self.labels.inst.any() else None)
        return loss.cloud_losses(table, fmt) + suggested

    def mark_saved(self):
        self.cloud.mark_saved()
        self.labels.mark_saved()
        self.frame_dirty.clear()
        self.boxes_saved()
        self.clear_recovery()
        if self.sequence is not None and self.panel_alive:
            self._fill_frames()
        self.changed()

    def keeps_path(self, path):
        """Saving the frames on screen to a single file exports a copy; the document stays the frame folder."""
        return self.sequence is not None and not os.path.isdir(path)

    def _after_change(self):
        """Redraw the chunks the last removal or undo touched."""
        ids = self.cloud.touched
        self.selected[ids] &= self.cloud.alive[ids]
        self.refresh(self.chunks.touched(ids))
        self._stats_timer.start()

    def _step(self, source, target, undo):
        """Undo (or redo) the most recent step: points, labels, frames, boxes or the class list, alone or together."""
        entry = source.pop() if source else "cloud"
        kinds = entry if isinstance(entry, tuple) else (entry,)
        swaps = {"label": (self.labels.undo, self.labels.redo, self._after_labels),
                 "frames": (lambda: self._swap_frames(self._frame_undo, self._frame_redo),
                            lambda: self._swap_frames(self._frame_redo, self._frame_undo), self._after_labels),
                 "classes": (lambda: self._swap_classes(self._class_undo, self._class_redo),
                             lambda: self._swap_classes(self._class_redo, self._class_undo), self.changed),
                 "boxes": (lambda: self._swap_boxes(self._box_undo, self._box_redo),
                           lambda: self._swap_boxes(self._box_redo, self._box_undo), self.changed),
                 "cloud": (self.cloud.undo, self.cloud.redo, self._after_change)}
        done = []
        for kind in (reversed(kinds) if undo else kinds):
            back, forth, after = swaps[kind]
            if (back if undo else forth)():
                done.append(after)
        if done:
            target.append(entry)
            for after in dict.fromkeys(done):
                after()

    def undo(self):
        self._step(self._order, self._redo_order, True)

    def redo(self):
        self._step(self._redo_order, self._order, False)

    def summary(self):
        done, total = self.progress()
        return self.tr("cloud_counts", n=len(self.cloud), v=self.visible_count, r=self.cloud.removed(),
                       s=int(self.selected.sum())) + (f"  ·  {self.tr('label_share', p=100.0 * done / max(total, 1))}"
                                                      if done else "")

    @property
    def selection(self):
        """Indices of the selected points."""
        return np.flatnonzero(self.selected)

    @property
    def visible_count(self):
        return sum(self.shown_counts.values())

    @property
    def hidden(self):
        return len(self.cloud) - self.visible_count

    @property
    def visible_ids(self):
        """Indices of every point that is alive and not hidden by the range or slice (a pass over the cloud)."""
        ids = self._class_filter(self.cloud.ids())
        return ids[self.shown(self.cloud.xyz[ids])]

    @property
    def visible_points(self):
        return self.cloud.xyz[self.visible_ids]

    def _filters(self):
        """(low, high) when a range or slice hides something, else None."""
        if not self.panel_alive:
            return None
        low, high = self.ranges.bounds()
        if not self.slice.values()["on"] and (low <= -RANGE_LIMIT).all() and (high >= RANGE_LIMIT).all():
            return None
        return low, high

    def shown(self, points, filters="unset"):
        """Mask of points that are visible, and therefore editable."""
        filters = self._filters() if isinstance(filters, str) else filters
        if filters is None or not len(points):
            return np.ones(len(points), bool)
        low, high = filters
        return np.all((points >= low) & (points <= high), axis=1) & self.slice.mask(points)

    def chunk_ids(self, chunk, filters="unset"):
        """Indices of a chunk's points that are alive and visible."""
        ids = self.chunks.ids[chunk]
        ids = self._class_filter(ids[self.cloud.alive[ids]])
        return ids[self.shown(self.cloud.xyz[ids], filters)]

    def colour_modes(self):
        modes = ["height"]
        if self.colours is not None:
            modes.append("rgb")
        modes += list(LABEL_MODES)
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
            label = self.tr(f"colour_{mode}") if mode in ("height", "rgb") + LABEL_MODES else mode
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

        if self.label_mode:
            self.build_label_sections(layout)

        group = Section(t("brush"), "brush")
        form = W.QFormLayout(group)
        self.radius = spin(0.001, RANGE_LIMIT, values["radius"], 0.01)
        self.radius.setToolTip(t("cloud_brush_tip"))
        form.addRow(t("brush_radius"), self.radius)
        hint = W.QLabel(t("brush_keys"))
        hint.setStyleSheet("color: gray;")
        form.addRow(hint)
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
        row.addWidget(button(t("clear_selection"), self.clear_selection, icon="clear_selection"))
        form.addRow(row)
        group.add_to(layout)

        if not self.label_mode:
            self._build_cleaning_sections(layout)
        self._build_ground_section(layout)

        group = Section(t("box"), "box")
        group.setToolTip(t("box_handles_tip"))
        grid = W.QGridLayout(group)
        self.box = AxisRanges(grid, 0, values["box"], 0.05, self._box_changed)
        self.show_box = W.QCheckBox(t("show_box"))
        self.show_box.setChecked(values["show_box"])
        self.show_box.toggled.connect(self._box_changed)
        grid.addWidget(self.show_box, 3, 0, 1, 2)
        grid.addWidget(button(t("box_from_selection"), self.box_from_selection, icon="box_fit"), 3, 2)
        grid.addWidget(select_button(t("box_select"), self.box_select, icon="box_select"), 4, 0, 1, 3)
        if not self.label_mode:
            grid.addWidget(danger_button(t("box_delete"), self.box_delete, icon="box_erase_in"), 5, 0, 1, 3)
            grid.addWidget(danger_button(t("box_delete_outside"), self.box_delete_outside, t("crop_tip"), icon="box_erase_out"), 6, 0, 1, 3)
        group.add_to(layout)

        group = Section(t("ruler"), "ruler")
        group.setToolTip(t("ruler_tip"))
        form = W.QFormLayout(group)
        self.ruler_label = W.QLabel(self._ruler_text(self.measurement)[1] if self.measurement else t("ruler_hint"))
        self.ruler_label.setWordWrap(True)
        self.ruler_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.ruler_label)
        form.addRow(button(t("ruler_clear"), self.clear_ruler, icon="ruler_clear"))
        group.add_to(layout)

        self.slice = SliceControls(t, values["slice"], 0.01, self._slice_changed, self.restore_view)
        self.slice.group.add_to(layout)

        group = Section(t("visible_range"), "visible_range")
        group.setToolTip(t("range_tip"))
        grid = W.QGridLayout(group)
        self.ranges = AxisRanges(grid, 0, values["range"], 0.05, lambda *_: self.refresh())
        grid.addWidget(button(t("show_all"), self.reset_range, icon="show_all"), 3, 0, 1, 3)
        group.add_to(layout)

        layout.addStretch(1)
        legend = W.QLabel(t("cloud_legend") + ("\n" + t("label_legend") if self.label_mode else ""))
        legend.setWordWrap(True)
        legend.setStyleSheet("color: gray;")
        layout.addWidget(legend)
        self._fill_colour_modes()
        self._style_changed()
        self._box_changed()
        self._update_slice_gizmo()
        return panel

    def _build_ground_section(self, layout):
        """Ground filter: in editing mode to remove or keep the ground, in labelling mode to label it."""
        t, values, W = self.tr, self.panel_values, QtWidgets
        group = Section(t("ground"), "ground")
        group.setToolTip(t("ground_tip"))
        form = W.QFormLayout(group)
        self.ground_cell = spin(0.05, 100.0, values["ground_cell"], 0.1)
        self.ground_slope = spin(1.0, 60.0, values["ground_slope"], 1.0, decimals=1)
        self.ground_height = spin(0.01, 10.0, values["ground_height"], 0.01)
        form.addRow(t("ground_cell"), self.ground_cell)
        form.addRow(t("ground_slope"), self.ground_slope)
        form.addRow(t("ground_height"), self.ground_height)
        row = W.QHBoxLayout()
        row.addWidget(select_button(t("ground_select"), lambda: self.select_ground(True), icon="ground_select"))
        row.addWidget(select_button(t("ground_others"), lambda: self.select_ground(False), icon="ground_others"))
        form.addRow(row)
        group.add_to(layout)

    def select_ground(self, wanted=True):
        """Select the ground under the visible points (wanted=True) or everything standing on it."""
        ids = self.visible_ids
        settings = {"cell": self.ground_cell.value(), "slope": self.ground_slope.value(),
                    "tolerance": self.ground_height.value()}
        table, xyz = self.cloud.table, self.cloud.xyz[ids]
        frames = table["frame"][ids] if table is not None and "frame" in table.dtype.names else None
        try:
            mask = self.compute(self.tr("ground") + " …", lambda: labels.ground_by_group(xyz, frames, **settings)
                                if frames is not None else labels.ground(xyz, **settings))
        except ValueError as error:
            QtWidgets.QMessageBox.warning(self.window, self.tr("ground"), str(error))
            return
        self.select(ids[mask if wanted else ~mask], "replace")
        self.status(self.tr("status_filter", n=int(self.selected.sum())) +
                    ("   ·   " + self.tr("label_mode_on").split(":")[0] + ": Enter" if self.label_mode else ""), 10000)

    def _build_cleaning_sections(self, layout):
        """Noise filters and thinning: editing mode only."""
        t, values, W = self.tr, self.panel_values, QtWidgets
        group = Section(t("noise_filters"), "noise_filters")
        form = W.QFormLayout(group)
        self.neighbours = int_spin(2, 200, values["neighbours"])
        self.ratio = spin(0.1, 10.0, values["ratio"], 0.1, decimals=2)
        form.addRow(t("neighbours"), self.neighbours)
        form.addRow(t("std_ratio"), self.ratio)
        form.addRow(select_button(t("select_outliers"), self.select_outliers, t("outliers_tip"), icon="outliers"))
        self.sparse_radius = spin(0.001, RANGE_LIMIT, values["sparse_radius"], 0.01)
        self.sparse_min = int_spin(1, 1000, values["sparse_min"])
        form.addRow(t("search_radius"), self.sparse_radius)
        form.addRow(t("min_neighbours"), self.sparse_min)
        form.addRow(select_button(t("select_sparse"), self.select_sparse, t("sparse_tip"), icon="sparse"))
        group.add_to(layout)

        group = Section(t("downsample"), "downsample")
        form = W.QFormLayout(group)
        self.leaf = spin(0.001, RANGE_LIMIT, values["leaf"], 0.01)
        form.addRow(t("cell_size"), self.leaf)
        form.addRow(danger_button(t("thin_out"), self.thin_out, t("thin_tip"), icon="thin_out"))
        group.add_to(layout)

    def store_panel(self):
        if not self.panel_alive:
            return
        self.panel_values.update({"ground_cell": self.ground_cell.value(), "ground_slope": self.ground_slope.value(),
                                  "ground_height": self.ground_height.value(),
                                  "radius": self.radius.value(), "point_size": self.point_size.value(),
                                  "colour": self.colour_box.currentData() or "height",
                                  "front_only": self.front_only.isChecked(), "tolerance": self.tolerance.value(),
                                  "box": self.box.values(), "show_box": self.show_box.isChecked(),
                                  "range": self.ranges.values(), "slice": self.slice.values()})
        if self.label_mode:
            self.panel_values.update(self.label_panel_values())
        else:
            self.panel_values.update({"neighbours": self.neighbours.value(), "ratio": self.ratio.value(),
                                      "sparse_radius": self.sparse_radius.value(), "sparse_min": self.sparse_min.value(),
                                      "leaf": self.leaf.value()})

    def view_actions(self):
        return [(self.tr(f"view_{name}"), lambda d=direction, u=up: self.look_from(d, u), keys)
                for name, direction, up, keys in VIEWS]

    def selection_actions(self):
        return {"delete": self.delete_selection, "select_all": self.select_all, "invert": self.invert_selection,
                "clear": self.clear_selection, "back": self.selection_back}

    def extra_actions(self):
        return super().extra_actions() + (self.label_actions() if self.label_mode else [])

    def conversions(self):
        return [(self.tr("to_voxels"), self.to_voxels), (self.tr("to_grid"), self.to_grid)]

    def shutdown(self):
        self._closed = True
        self._pending = []
        self.clear_recovery(only_own=True)
        for timer in (self._refresh_timer, self._level_timer, self._slice_timer, self._stats_timer, self._autosave):
            timer.stop()
        self.viewport.renderer.GetActiveCamera().RemoveObserver(self._camera_watch)
        self.view.clear()

    def activate(self):
        self.viewport.initialize()
        self.look_from(*VIEWS[3][1:3])

    def capture(self):
        return self.viewport.capture()

    def _colour_setup(self):
        """Colour mode and the value range its ramp spans, taken from a sample of the cloud."""
        mode = self.colour_box.currentData() if self.panel_alive else "height"
        mode = mode or "height"
        if mode not in ("rgb",) + LABEL_MODES:
            sample = self.cloud.ids()[::max(1, len(self.cloud) // 200_000)]
            values = self.cloud.xyz[sample, 2] if mode == "height" else self.cloud.table[mode][sample].astype(np.float64)
            if len(values):
                self._colour_range = tuple(np.percentile(values, [1, 99]))
        return mode

    def _levels(self, chunks):
        """Thinning level per chunk: no more points than the pixels it covers, and within the point budget."""
        if not len(chunks) or not len(self.chunks):
            return {}
        low, high = self.chunks.low, self.chunks.high
        centres, size = (low + high) / 2, np.linalg.norm(high - low, axis=1)
        camera = self.viewport.renderer.GetActiveCamera()
        eye = np.array(camera.GetPosition())
        angle = max(self.viewport.pixel_angle(), 1e-9)
        distance = np.maximum(np.linalg.norm(centres - eye, axis=1), 1e-6)
        counts = np.array([self.shown_counts.get(chunk, len(self.chunks.ids[chunk])) for chunk in range(len(self.chunks))],
                          float)
        pixels = np.maximum(size / (np.maximum(distance - size / 2, 1e-6) * angle), 1.0) ** 2
        levels = np.clip(np.ceil(np.log(np.maximum(counts / (2.0 * pixels), 1.0)) / np.log(4.0)), 0, MAX_LEVEL).astype(int)
        sx, sy, ahead = self.viewport.project(centres)
        width, height = self.viewport.renderer.GetSize()
        margin = size / (distance * angle)
        outside = (sx < -margin) | (sx > width + margin) | (sy < -margin) | (sy > height + margin)
        levels[(outside | ~ahead) & (distance > size)] = MAX_LEVEL
        far_first = np.argsort(-distance)
        for _ in range(MAX_LEVEL):
            drawn = counts / 4.0 ** levels
            excess = drawn.sum() - POINT_BUDGET
            if excess <= 0:
                break
            candidates = far_first[levels[far_first] < MAX_LEVEL]
            saved = np.cumsum(drawn[candidates] * 0.75)
            levels[candidates[:int(np.searchsorted(saved, excess)) + 1]] += 1
        return {chunk: int(levels[chunk]) for chunk in chunks}

    def _draw(self, chunk, level, filters, mode):
        """Build one thinning level of one chunk from the current points, selection and filters."""
        ids = self.chunk_ids(chunk, filters)
        self.shown_counts[chunk] = len(ids)
        if level:
            keep = np.zeros(len(ids), bool)
            keep[:-(-len(ids) // 4 ** level)] = True
            ids = ids[keep | self.selected[ids]]
        points = self.cloud.xyz[ids]
        if mode in LABEL_MODES:
            colours = self.label_colours(ids, mode)
        elif mode == "rgb" and self.colours is not None:
            colours = self.colours[ids].copy()
        else:
            values = points[:, 2] if mode == "height" else self.cloud.table[mode][ids].astype(np.float64)
            colours = ramp(values, *self._colour_range)
        colours[self.selected[ids]] = SELECTED_RGB
        self.view.build(chunk, points, colours, level)

    def refresh(self, chunks=None, render=True, progress=None):
        """Redraw the given chunks (all of them by default) after points, the selection or the filters changed."""
        everything = chunks is None
        if everything:
            chunks = range(len(self.chunks))
            self.shown_counts = {}
            self.view.clear()
        chunks = list(chunks)
        filters = self._filters()
        mode = self._colour_setup() if everything else self._mode
        self._mode = mode
        levels = self._levels(chunks)
        for done, chunk in enumerate(chunks):
            if progress and done % 16 == 0:
                progress(done, len(chunks))
            self.view.forget(chunk)
            self._draw(chunk, levels[chunk], filters, mode)
        self.changed()
        if render:
            self.viewport.render()

    def update_levels(self):
        """Move chunks to the thinning level that suits the camera: cached levels at once, the rest in small slices."""
        if self._closed:
            return
        self.viewport.fit_axes()
        if not len(self.chunks):
            return
        chunks = list(range(len(self.chunks)))
        wanted = self._levels(chunks)
        pending = []
        for chunk in chunks:
            level = wanted[chunk]
            if self.view.levels.get(chunk, level) == level:
                continue
            if self.view.has(chunk, level):
                self.view.show(chunk, level)
            else:
                pending.append(chunk)
        if pending:
            centres = (self.chunks.low[pending] + self.chunks.high[pending]) / 2
            eye = np.array(self.viewport.renderer.GetActiveCamera().GetPosition())
            order = np.argsort(np.linalg.norm(centres - eye, axis=1))
            pending = [(pending[i], wanted[pending[i]]) for i in order]
        self._pending = pending
        self.viewport.render()
        if pending:
            self._slice_timer.start()

    def _refine(self, budget=0.012):
        """Build queued thinning levels, nearest chunks first, for a few milliseconds at a time."""
        if self._closed or not self._pending:
            return
        filters = self._filters()
        started = time.perf_counter()
        while self._pending and time.perf_counter() - started < budget:
            chunk, level = self._pending.pop(0)
            if not self.view.has(chunk, level):
                self._draw(chunk, level, filters, self._mode)
        self.view.trim(CACHE_BUDGET)
        self.viewport.render()
        if self._pending:
            self._slice_timer.start()

    def finish_levels(self):
        """Build every queued thinning level now (used by tests and screenshots)."""
        while self._pending:
            self._refine(1.0)

    def recolor(self, render=True):
        """Recolour everything, for example after the colour mode changed."""
        self.refresh(render=render)

    def _style_changed(self, *_):
        self.view.set_point_size(self.point_size.value())
        self.viewport.render()

    def look_from(self, direction, up):
        low, high = self.data_bounds if len(self.chunks) else (-np.ones(3), np.ones(3))
        self.viewport.look_from(direction, up, (low[0], high[0], low[1], high[1], low[2], high[2]))

    def reset_range(self):
        self.ranges.reset()
        self.refresh()

    def set_tool(self, name):
        self.tool = name
        self.hover_actor.VisibilityOff()
        self.preview_actor.VisibilityOff()
        self.viewport.set_default_cursor(Qt.ArrowCursor if name == "view" else Qt.CrossCursor)
        self.viewport.render()

    def remove(self, ids, label):
        if self.sequence is not None:
            return self.status(self.tr("frames_no_erase"), 8000)
        removed = self.cloud.remove(ids)
        if removed:
            self._order.append("cloud")
            self._redo_order.clear()
            self._after_change()
            self.status(self.tr("status_removed", what=label, n=removed))
        else:
            self.status(self.tr("status_no_change", what=label))

    def select(self, ids, mode="add", review=False):
        """Change the selection with alive, visible points: 'add', 'remove' or 'replace'.

        In labelling mode with protection on, points the next labelling may not change are left out, so the
        selection shows exactly what will be labelled; review tools (review=True) pick labelled points on purpose.
        """
        ids = np.asarray(ids, np.int64)
        self._delete_target = None
        if len(ids):
            ids = self._class_filter(ids[self.cloud.alive[ids]])
            ids = ids[self.shown(self.cloud.xyz[ids])]
            if mode != "remove" and not review and self.protecting():
                ids = self._writable(ids)
        if mode == "remove":
            changed = ids[self.selected[ids]]
            self.selected[changed] = False
            step = ("remove", changed)
        elif mode == "replace":
            before = self.selection
            self.selected[:] = False
            self.selected[ids] = True
            changed = np.union1d(before, ids)
            step = ("replace", before)
        else:
            changed = ids[~self.selected[ids]]
            self.selected[changed] = True
            step = ("add", changed)
        if len(changed):
            self._selection_steps = self._selection_steps[-63:] + [step]
            self.refresh(self.chunks.touched(changed))
        else:
            self.changed()

    def selection_back(self):
        """Take back the most recent selection step (one click, rectangle or filter)."""
        if not self._selection_steps:
            return
        kind, ids = self._selection_steps.pop()
        changed = ids
        if kind == "add":
            self.selected[ids] = False
        elif kind == "remove":
            self.selected[ids] = self.cloud.alive[ids]
        else:
            changed = np.union1d(self.selection, ids)
            self.selected[:] = False
            self.selected[ids] = self.cloud.alive[ids]
        self.refresh(self.chunks.touched(changed))
        self.status(self.tr("selection_back") + f": {int(self.selected.sum())}")

    def delete_selection(self):
        if self.label_mode:
            return self.label_delete()
        if self.selected.any():
            self.remove(self.selection, self.tr("delete_selection"))

    def clear_selection(self):
        self.select(np.zeros(0, np.int64), "replace")

    def select_all(self):
        self.select(self.visible_ids, "replace")

    def invert_selection(self):
        ids = self.visible_ids
        self.select(ids[~self.selected[ids]], "replace")

    def _select_filtered(self, ids):
        self.select(ids, "replace", review=True)
        self.status(self.tr("status_filter", n=int(self.selected.sum())), 10000)

    def select_outliers(self):
        ids = self.visible_ids
        xyz, neighbours, ratio = self.cloud.xyz[ids], self.neighbours.value(), self.ratio.value()
        local = self.compute(self.tr("select_outliers") + " …", lambda: cloud.statistical_outliers(xyz, neighbours, ratio))
        self._select_filtered(ids[local])

    def select_sparse(self):
        ids = self.visible_ids
        xyz, radius, least = self.cloud.xyz[ids], self.sparse_radius.value(), self.sparse_min.value()
        local = self.compute(self.tr("select_sparse") + " …", lambda: cloud.sparse_points(xyz, radius, least))
        self._select_filtered(ids[local])

    def thin_out(self):
        ids = self.visible_ids
        xyz, leaf = self.cloud.xyz[ids], self.leaf.value()
        surplus = self.compute(self.tr("thin_out") + " …", lambda: cloud.downsample_surplus(xyz, leaf))
        self.remove(ids[surplus], self.tr("thin_out"))

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
        self.slice_gizmo.update(values["axis"], values["position"], self.data_bounds, self.slice.normal(),
                                self.slice.centre)
        self.slice_gizmo.show(values["on"])

    def _slice_changed(self):
        values = self.slice.values()
        axis = values["axis"]
        low, high = self.data_bounds
        mode = (values["on"], axis)
        if values["on"] and (mode != self._previous_mode or not low[axis] <= values["position"] <= high[axis]):
            self.slice.centre = (low + high) / 2
            self.slice.set_position(float((low[axis] + high[axis]) / 2))
        self._previous_mode = mode
        self._update_slice_gizmo()
        self.refresh()
        self._report_slice()

    def _slice_dragged(self, position):
        self.slice.set_position(position)
        self._update_slice_gizmo()
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

    def _ids_in_box(self):
        low, high = self.box.bounds()
        filters = self._filters()
        parts = []
        for chunk in self.chunks.overlapping(low, high):
            ids = self.chunk_ids(chunk, filters)
            points = self.cloud.xyz[ids]
            parts.append(ids[np.all((points >= low) & (points <= high), axis=1)])
        return np.concatenate(parts) if parts else np.zeros(0, np.int64)

    def box_from_selection(self):
        if self.selected.any():
            points = self.cloud.xyz[self.selection]
            self.box.set(points.min(axis=0), points.max(axis=0))
            self.show_box.setChecked(True)
            self._box_changed()

    def box_select(self):
        self.show_box.setChecked(True)
        self.select(self._ids_in_box())

    def box_delete(self):
        self.show_box.setChecked(True)
        self.remove(self._ids_in_box(), self.tr("box_delete"))

    def box_delete_outside(self):
        self.show_box.setChecked(True)
        self.remove(np.setdiff1d(self.visible_ids, self._ids_in_box(), assume_unique=True), self.tr("box_delete_outside"))

    def _ask_size(self):
        xyz, _ = self.cloud.surviving()
        if not len(xyz):
            return None, None
        guess = self.origin["resolution"] if self.origin else formats.estimate_resolution(xyz)
        answer = ask_numbers(self.window, self.tr("voxel_size_title"), [(self.tr("voxel_size_cloud"), guess, 1e-4, 1e3, 4)])
        return (xyz, answer[0]) if answer else (None, None)

    def _labelled_source(self, xyz):
        """What a conversion needs to know about the labels of the surviving points, or None when there are none."""
        if not self.labels.any:
            return None
        alive = self.cloud.alive
        return {"cls": self.labels.cls[alive], "inst": self.labels.inst[alive], "classes": self.classes}

    def _ask_ignore(self, source):
        """With labels present, ask whether classes marked 'ignore' stay out of the converted map."""
        ignored = self.classes.with_role(labels.IGNORE) if source else []
        if not ignored:
            return np.zeros(0, np.int64)
        names = ", ".join(self.classes.name(number) for number in ignored)
        answer = ask_numbers(self.window, self.tr("convert_classes"), [(self.tr("convert_skip_ignored", names=names), True)])
        if answer is None:
            return None
        return np.array(ignored if answer[0] else [], np.int64)

    def to_voxels(self):
        xyz, size = self._ask_size()
        if size is None:
            return None
        table = self.cloud.surviving()[1]
        source = {"xyz": xyz, "table": table}
        marks = self._labelled_source(xyz)
        ignored = self._ask_ignore(marks)
        if ignored is None:
            return None
        if marks:
            source.update(marks, outside=np.isin(marks["cls"], ignored))

        classes = self.classes

        def work():
            if not marks:
                return VOXEL, (convert.points_to_voxels(xyz, size), size, source)
            inside = ~source["outside"]
            source["voxel"] = convert.vote_voxels(xyz[inside], marks["cls"][inside], size, classes)
            return VOXEL, (convert.points_to_voxels(xyz[inside], size), size, source)
        return work

    def to_grid(self):
        xyz, size = self._ask_size()
        if size is None:
            return None
        band = ask_numbers(self.window, self.tr("band_title"), [
            (self.tr("band_low"), float(xyz[:, 2].min()), -RANGE_LIMIT, RANGE_LIMIT, 3),
            (self.tr("band_high"), float(xyz[:, 2].max()), -RANGE_LIMIT, RANGE_LIMIT, 3),
            (self.tr("empty_as_free"), False)])
        if band is None:
            return None
        empty = FREE if band[2] else UNKNOWN
        marks = self._labelled_source(xyz)
        if not marks:
            return lambda: (GRID, convert.voxels_to_grid(convert.points_to_voxels(xyz, size), size, *sorted(band[:2]), empty))
        classes = self.classes

        def work():
            obstacles, free = convert.voxels_by_role(xyz, marks["cls"], size, classes)
            return GRID, convert.voxels_to_grid(obstacles, size, *sorted(band[:2]), empty, free)
        return work

    def _pick(self, x, y):
        """Nearest visible point close to the cursor ray, searching only the chunks the ray passes."""
        if not len(self.chunks):
            return None
        origin, direction = self.viewport.eye_ray(x, y)
        angle = PICK_PIXELS * self.viewport.pixel_angle()
        reach = np.linalg.norm(self.chunks.high - origin, axis=1).max() * angle
        hits, entry = ray_boxes(origin, direction, self.chunks.low - reach, self.chunks.high + reach)
        order = np.argsort(entry)
        filters = self._filters()
        best, best_distance = None, np.inf
        for chunk, distance in zip(hits[order], entry[order]):
            if distance > best_distance:
                break
            points = self.cloud.xyz[self.chunk_ids(int(chunk), filters)]
            index = cloud.pick_along_ray(origin, direction, points, angle)
            if index is not None:
                along = float((points[index] - origin) @ direction)
                if along < best_distance:
                    best, best_distance = points[index], along
        return best

    def _brush_ids(self, centre):
        radius = self.radius.value()
        filters = self._filters()
        parts = []
        for chunk in self.chunks.near(centre, radius):
            ids = self.chunk_ids(int(chunk), filters)
            offset = self.cloud.xyz[ids] - centre
            parts.append(ids[np.einsum("ij,ij->i", offset, offset) <= radius * radius])
        return np.concatenate(parts) if parts else np.zeros(0, np.int64)

    def clear_ruler(self):
        """Remove the ruler from the view and forget every stored measurement."""
        self.ruler.clear()
        self.measurement = None
        self.overlay.clear()
        if self.panel_alive:
            self.ruler_label.setText(self.tr("ruler_hint"))
        self.viewport.render()

    def _show_measurement(self, entry):
        """Draw a stored measurement in the view (called when its tab is chosen)."""
        if entry is None:
            self.ruler.clear()
        else:
            self.measurement = entry
            short, detail = self._ruler_text(entry)
            self.ruler.first = entry["a"]
            self.ruler.finish(entry["b"], short)
            if self.panel_alive:
                self.ruler_label.setText(detail)
        self.viewport.render()

    def _ruler_text(self, result):
        short = self.tr("ruler_short", **result)
        detail = self.tr("ruler_detail_cloud", **result)
        return short, detail

    def adjust_brush(self, step):
        if self.tool == "smart":
            return self.adjust_smart(step)
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
            self.overlay.add(dict(self.measurement, a=self.ruler.first.copy(), b=self.ruler.second.copy()))
        else:
            self.ruler.marker_size = self._marker_size()
            self.ruler.start(point)
            self.ruler_label.setText(self.tr("ruler_second"))
            self.status(self.tr("ruler_second"), 0)
        self.viewport.render()

    def measure_point(self, x, y):
        """Point under the cursor, marked with a small sphere so it is clear what will be measured."""
        point = self._pick(x, y) if self.visible_count else None
        if point is not None:
            self.hover_source.SetCenter(*point)
            self.hover_source.SetRadius(self._marker_size() * 2.5)
            self.hover_actor.GetProperty().SetColor(*RULER_RGB)
            self.hover_actor.VisibilityOn()
        return point

    def _marker_size(self):
        """Radius for ruler and hover markers: a few pixels at the current zoom, not a share of the data extent."""
        return max(self.viewport.pixel_size() * 3.0, 1e-4)

    def _hover(self, x, y):
        if self.tool == "view":
            return
        if self.tool == "measure":
            self._measure_hover(x, y)
            return
        centre = None if not self.visible_count else self._pick(x, y)
        if centre is None:
            if self.hover_actor.GetVisibility():
                self.hover_actor.VisibilityOff()
                self.preview_actor.VisibilityOff()
                self.viewport.render()
            return
        if self.tool == "smart":
            self.hover_source.SetCenter(*centre)
            self.hover_source.SetRadius(self._marker_size() * 2.5)
            self.hover_actor.GetProperty().SetColor(*TOOL_RGB["label"])
            self.hover_actor.VisibilityOn()
            self.status(self.tr("status_hover", x=centre[0], y=centre[1], z=centre[2]), 0)
            self.viewport.render()
            return
        rgb = tuple(v / 255.0 for v in self.classes.rgb(self.active_class)) if self.tool == "label" else TOOL_RGB[self.tool]
        self.hover_source.SetCenter(*centre)
        self.hover_source.SetRadius(self.radius.value())
        self.hover_actor.GetProperty().SetColor(*rgb)
        self.hover_actor.VisibilityOn()
        inside = self.cloud.xyz[self._brush_ids(centre)]
        self._show_preview(inside, rgb)
        eye = np.array(self.viewport.renderer.GetActiveCamera().GetPosition())
        self.status(self.tr("status_hover", x=centre[0], y=centre[1], z=centre[2]) + "   ·   "
                    + self.tr("status_brush", n=len(inside), d=float(np.linalg.norm(centre - eye))), 0)
        self.viewport.render()

    def _show_preview(self, points, rgb):
        """Light up the points the brush would affect, so its depth in the cloud is obvious."""
        vtk_points = vtk.vtkPoints()
        cells = vtk.vtkCellArray()
        if len(points):
            vtk_points.SetData(numpy_support.numpy_to_vtk(np.ascontiguousarray(points), deep=True))
            cells.SetData(numpy_support.numpy_to_vtkIdTypeArray(np.arange(len(points) + 1, dtype=np.int64), deep=True),
                          numpy_support.numpy_to_vtkIdTypeArray(np.arange(len(points), dtype=np.int64), deep=True))
        self.preview.SetPoints(vtk_points)
        self.preview.SetVerts(cells)
        self.preview.Modified()
        self.preview_actor.GetProperty().SetColor(*rgb)
        self.preview_actor.GetProperty().SetPointSize(self.point_size.value() + 3)
        self.preview_actor.SetVisibility(bool(len(points)))

    def _click(self, x, y, ctrl):
        if self.tool == "view" or not self.visible_count:
            return
        if self.tool == "measure":
            self._measure_click(x, y)
            return
        if self.viewport.interactor.GetAltKey():
            self.pick_class(x, y)
            return
        if self.tool == "smart":
            self._smart_click(x, y, ctrl)
            return
        centre = self._pick(x, y)
        if centre is None:
            return
        self._brush(self._brush_ids(centre), ctrl)
        self._hover(x, y)

    def _brush(self, ids, subtract=False):
        if self.tool in ("select", "smart"):
            self.select(ids, "remove" if subtract else "add")
        elif self.tool == "label":
            self.assign(ids, labels.UNLABELED if subtract else self.active_class, "tool_label")
        elif not subtract:
            self.remove(ids, self.tr("tool_delete"))

    def _paint(self, x, y, subtract=False):
        """Ctrl + drag: keep applying the brush under the cursor while the view stays still.

        The left button applies the tool; the right button takes back (deselects, or clears labels).
        """
        if self._stroke is None:
            self._stroke = (len(self._selection_steps), self.cloud.undo_depth(), self.labels.undo_depth(), len(self._order))
        centre = self._pick(x, y) if self.visible_count else None
        if centre is None:
            return
        self._brush(self._brush_ids(centre), subtract)
        self._hover(x, y)

    def _paint_end(self):
        """Fold a finished stroke into a single selection step and a single undo step."""
        if self._stroke is None:
            return
        steps, depth, label_depth, order = self._stroke
        self._stroke = None
        painted = [ids for kind, ids in self._selection_steps[steps:] if kind == "add"]
        if len(painted) > 1:
            self._selection_steps[steps:] = [("add", np.unique(np.concatenate(painted)))]
        self.cloud.squash(depth)
        self.labels.squash(label_depth)
        self._order[order:] = self._order[order:order + 1]

    def _right_click(self, x, y):
        if not self.selected.any() or not self.visible_count:
            return
        centre = self._pick(x, y)
        if centre is not None:
            before = int(self.selected.sum())
            self.select(self._brush_ids(centre), "remove")
            self.status(self.tr("status_deselected", n=before - int(self.selected.sum())))

    def _chunks_in_rectangle(self, corner_a, corner_b):
        """Chunk numbers whose bounding box overlaps a screen rectangle."""
        low, high = self.chunks.low, self.chunks.high
        corners = np.stack([np.where(np.array(mask, bool), high, low)
                            for mask in ((i, j, k) for i in (0, 1) for j in (0, 1) for k in (0, 1))], axis=1)
        sx, sy, ahead = self.viewport.project(corners.reshape(-1, 3))
        sx, sy, ahead = sx.reshape(-1, 8), sy.reshape(-1, 8), ahead.reshape(-1, 8)
        x0, x1 = sorted((corner_a[0], corner_b[0]))
        y0, y1 = sorted((corner_a[1], corner_b[1]))
        overlap = (sx.max(axis=1) >= x0) & (sx.min(axis=1) <= x1) & (sy.max(axis=1) >= y0) & (sy.min(axis=1) <= y1)
        return np.flatnonzero((overlap | ~ahead.all(axis=1)) & ahead.any(axis=1))

    def _rectangle(self, corner_a, corner_b, subtract):
        self.hover_actor.VisibilityOff()
        if not len(self.chunks):
            return
        filters = self._filters()
        parts = [self.chunk_ids(int(chunk), filters) for chunk in self._chunks_in_rectangle(corner_a, corner_b)]
        ids = np.concatenate(parts) if parts else np.zeros(0, np.int64)
        chosen = self.viewport.rectangle_hits(self.cloud.xyz[ids], corner_a, corner_b, self.front_only.isChecked(),
                                              self.tolerance.value())
        self.select(ids[chosen], "remove" if subtract else "add")
        self.status(self.tr("status_rectangle", n=len(chosen), t=int(self.selected.sum())))
