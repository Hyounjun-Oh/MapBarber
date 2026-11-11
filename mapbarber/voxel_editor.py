"""Editor for occupied-voxel maps (OctoMap octrees and voxel archives)."""
import numpy as np

from . import convert, formats
from .editor import Editor
from .formats import CLOUD, GRID, VOXEL
from .gizmo import AXIS_NAMES, SLICE_DEFAULTS, BoxGizmo, SliceControls, SliceGizmo, Snap
from .qt import QtCore, QtWidgets
from .measure_panel import MeasureOverlay
from .ruler import RULER_RGB, Ruler3D, measure
from .scene import VIEWS, Viewport
from .chunk_view import ADDED, MAX_LEVEL, NORMAL, SELECTED, ChunkView
from .voxels import CHUNK, EMPTY, KeySet, VoxelMap, in_range, pack, ray_boxes, ray_pick, unpack
from .widgets import add_button, ask_numbers, AxisRanges, button, danger_button, int_spin, RANGE_LIMIT, Section, select_button, spin

Qt = QtCore.Qt
SELECTED_RGB = np.array([255, 40, 200], np.uint8)
ADDED_RGB = np.array([245, 245, 245], np.uint8)
TOOL_RGB = {"select": (1.0, 0.2, 0.8), "delete": (1.0, 0.15, 0.1), "add": (0.2, 1.0, 0.3)}
MAX_FILL_CELLS = 2_000_000
CUBE_BUDGET = 4_000_000
DEFAULTS = {"brush": 1, "plane": 0.0, "front_only": True, "tolerance": 0.10, "island": 20,
            "box": [(-0.2, 0.2)] * 3, "show_box": False, "range": [(-RANGE_LIMIT, RANGE_LIMIT)] * 3,
            "slice": SLICE_DEFAULTS, "snap": False}


class VoxelEditor(Editor):
    kind = VOXEL
    tools = (("view", "H"), ("select", "V"), ("delete", "E"), ("add", "B"), ("measure", "I"))
    export_filters = (("OctoMap binary", "bt"), ("OctoMap full", "ot"), ("Voxel archive", "npz"),
                      ("PCD point cloud", "pcd"), ("PLY point cloud", "ply"), ("XYZ text", "xyz"), ("CSV text", "csv"),
                      ("NumPy array", "npy"))

    def __init__(self, window):
        super().__init__(window)
        self.map = VoxelMap()
        self.selected = KeySet()
        self.height_range = (0.0, 1.0)
        self.panel_values = dict(DEFAULTS)
        self.viewport = Viewport(window, self._click, self._hover, self._rectangle, self._right_click)
        self.widget = self.viewport.widget
        self.view = ChunkView(self.viewport.renderer)
        self.shown_counts = {}
        self.chunk_bounds = {}
        self._chunk_ids = np.zeros(0, np.int64)
        self._chunk_low = np.zeros((0, 3))
        self._chunk_high = np.zeros((0, 3))
        self._level_timer = QtCore.QTimer()
        self._level_timer.setSingleShot(True)
        self._level_timer.setInterval(80)
        self._level_timer.timeout.connect(self.update_levels)
        self.viewport.renderer.GetActiveCamera().AddObserver("ModifiedEvent", lambda *_: self._level_timer.start())
        self.hover_source, self.hover_actor = self.viewport.outline((1, 1, 1), 2.5)
        self.box_source, self.box_actor = self.viewport.outline((1.0, 0.85, 0.1))
        self.box_gizmo = BoxGizmo(self.viewport, self._box_dragged, Snap(self.map.resolution))
        self.slice_gizmo = SliceGizmo(self.viewport, self._slice_dragged, Snap(self.map.resolution))
        self.viewport.gizmos = [self.slice_gizmo, self.box_gizmo]
        self.ruler = Ruler3D(self.viewport.renderer)
        self.overlay = MeasureOverlay(self.widget, lambda entry: self._ruler_text(entry)[1], self._show_measurement,
                                      lambda: self.tr)
        self.viewport.band_allowed = lambda: self.tool != "measure"
        self.measurement = None
        self.data_bounds = (np.zeros(3), np.ones(3))
        self._previous_mode = (False, 2)
        self._refresh_timer = QtCore.QTimer()
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)
        self._refresh_timer.timeout.connect(self.refresh)

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
        self.selected = KeySet()
        size = self.map.resolution
        self.view.clear()
        self.view.set_resolution(size)
        self.shown_counts, self.chunk_bounds = {}, {}
        extent = 1.0
        limits = self.map.bounds()
        if limits is not None:
            extent = float((limits[1] - limits[0]).max() + 1) * size
            heights = np.concatenate([self.map.cells(chunk)[::17, 2] for chunk in self.map.chunks])
            z_low, z_high = (np.percentile(heights, [0.5, 99.5]) + 0.5) * size
            self.height_range = (float(z_low), float(max(z_high, z_low + size)))
        self.view.height_range = self.height_range
        self.viewport.set_axes_length(max(0.08 * extent, 4 * size))
        self.box_gizmo.snap = Snap(size)
        self.slice_gizmo.snap = Snap(size)
        self.clear_ruler()
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
        marked = set(KeySet.split(self.map.added)[0].tolist())
        self.map.mark_saved()
        self.refresh(marked)

    def _after_change(self):
        """Redraw the chunks the last edit touched and drop selected cells that no longer exist."""
        touched = set(self.map.touched)
        for chunk in touched & set(self.selected.chunks):
            stored = self.map.chunks.get(chunk)
            if stored is None:
                self.selected.remove(self.selected.keys(chunk))
            else:
                gone = np.setdiff1d(self.selected.chunks[chunk], stored, assume_unique=True)
                if len(gone):
                    self.selected.remove(pack(self.selected.cells(chunk, gone)))
        self.refresh(touched)

    def undo(self):
        if self.map.undo():
            self._after_change()

    def redo(self):
        if self.map.redo():
            self._after_change()

    def summary(self):
        added, removed = self.map.changes()
        return self.tr("voxel_counts", n=len(self.map), v=self.visible_count, a=added, r=removed, s=len(self.selected),
                       res=f"{self.map.resolution:g}")

    def info(self):
        return {"voxels": len(self.map), "resolution": self.map.resolution}

    def build_panel(self):
        t, values, W = self.tr, self.panel_values, QtWidgets
        step = self.map.resolution
        panel = W.QWidget()
        layout = W.QVBoxLayout(panel)

        group = Section(t("brush"), "brush")
        form = W.QFormLayout(group)
        self.brush = int_spin(1, 31, values["brush"], t("cells"))
        self.brush.setSingleStep(2)
        self.brush.setToolTip(t("brush_tip"))
        form.addRow(t("brush_size"), self.brush)
        self.plane = spin(-RANGE_LIMIT, RANGE_LIMIT, values["plane"], step)
        self.plane.setToolTip(t("plane_tip"))
        form.addRow(t("work_plane"), self.plane)
        group.add_to(layout)

        group = Section(t("rectangle"), "rectangle")
        form = W.QFormLayout(group)
        self.front_only = W.QCheckBox(t("front_only"))
        self.front_only.setChecked(values["front_only"])
        form.addRow(self.front_only)
        self.tolerance = spin(0.0, RANGE_LIMIT, values["tolerance"], step)
        form.addRow(t("depth_tolerance"), self.tolerance)
        row = W.QHBoxLayout()
        row.addWidget(danger_button(t("delete_selection"), self.delete_selection))
        row.addWidget(button(t("clear_selection"), self.clear_selection))
        form.addRow(row)
        group.add_to(layout)

        group = Section(t("islands"), "islands")
        form = W.QFormLayout(group)
        self.island_size = int_spin(1, 1_000_000, values["island"], t("voxels_suffix"))
        form.addRow(t("island_size"), self.island_size)
        form.addRow(select_button(t("select_islands"), self.select_islands, t("islands_tip")))
        group.add_to(layout)

        group = Section(t("box"), "box")
        group.setToolTip(t("box_handles_tip"))
        grid = W.QGridLayout(group)
        self.box = AxisRanges(grid, 0, values["box"], step, self._box_changed)
        self.show_box = W.QCheckBox(t("show_box"))
        self.show_box.setChecked(values["show_box"])
        self.show_box.toggled.connect(self._box_changed)
        grid.addWidget(self.show_box, 3, 0, 1, 2)
        grid.addWidget(button(t("box_from_selection"), self.box_from_selection), 3, 2)
        grid.addWidget(select_button(t("box_select"), self.box_select), 4, 0, 1, 3)
        grid.addWidget(danger_button(t("box_delete"), self.box_delete), 5, 0, 1, 3)
        grid.addWidget(add_button(t("box_fill"), self.box_fill, t("box_fill_tip")), 6, 0, 1, 3)
        group.add_to(layout)

        group = Section(t("ruler"), "ruler")
        group.setToolTip(t("ruler_tip"))
        form = W.QFormLayout(group)
        self.ruler_snap = W.QCheckBox(t("ruler_snap"))
        self.ruler_snap.setChecked(values["snap"])
        form.addRow(self.ruler_snap)
        self.ruler_label = W.QLabel(self._ruler_text(self.measurement)[1] if self.measurement else t("ruler_hint"))
        self.ruler_label.setWordWrap(True)
        self.ruler_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.ruler_label)
        form.addRow(button(t("ruler_clear"), self.clear_ruler))
        group.add_to(layout)

        self.slice = SliceControls(t, values["slice"], step, self._slice_changed, self.restore_view)
        self.slice.group.add_to(layout)

        group = Section(t("visible_range"), "visible_range")
        group.setToolTip(t("range_tip"))
        grid = W.QGridLayout(group)
        self.ranges = AxisRanges(grid, 0, values["range"], step, lambda *_: self.refresh())
        grid.addWidget(button(t("show_all"), self.reset_range), 3, 0, 1, 3)
        group.add_to(layout)

        layout.addStretch(1)
        legend = W.QLabel(t("voxel_legend"))
        legend.setWordWrap(True)
        legend.setStyleSheet("color: gray;")
        layout.addWidget(legend)
        self._box_changed()
        self._update_slice_gizmo()
        return panel

    def _step_boxes(self):
        boxes = [self.plane, self.tolerance, self.slice.position]
        for ranges in (self.box, self.ranges):
            boxes += [b for pair in ranges.pairs for b in pair]
        return boxes

    def store_panel(self):
        if self.panel_alive:
            self.panel_values = {"brush": self.brush.value(), "plane": self.plane.value(),
                                 "front_only": self.front_only.isChecked(), "tolerance": self.tolerance.value(),
                                 "island": self.island_size.value(), "box": self.box.values(),
                                 "show_box": self.show_box.isChecked(), "range": self.ranges.values(),
                                 "slice": self.slice.values(), "snap": self.ruler_snap.isChecked()}

    def view_actions(self):
        return [(self.tr(f"view_{name}"), lambda d=direction, u=up: self.look_from(d, u), keys)
                for name, direction, up, keys in VIEWS]

    def selection_actions(self):
        return {"delete": self.delete_selection, "select_all": self.select_all, "invert": self.invert_selection,
                "clear": self.clear_selection}

    def conversions(self):
        return [(self.tr("to_grid"), self.to_grid), (self.tr("to_cloud"), self.to_cloud)]

    def activate(self):
        self.viewport.initialize()
        self.look_from(*VIEWS[3][1:3])

    def capture(self):
        return self.viewport.capture()

    @property
    def selection(self):
        """Selected keys, sorted."""
        return self.selected.occupied

    @property
    def visible_count(self):
        return sum(self.shown_counts.values())

    @property
    def hidden(self):
        return len(self.map) - self.visible_count

    @property
    def visible_keys(self):
        """Keys of every cell that is neither sliced away nor outside the visible range (a pass over the map)."""
        parts = [pack(self._shown_cells(chunk)) for chunk in self.map.chunks]
        return np.sort(np.concatenate(parts)) if parts else EMPTY

    def _filters(self):
        """(low, high) when a range or slice hides something, else None."""
        if not self.panel_alive:
            return None
        low, high = self.ranges.bounds()
        if not self.slice.values()["on"] and (low <= -RANGE_LIMIT).all() and (high >= RANGE_LIMIT).all():
            return None
        return low, high

    def shown(self, cells, filters="unset"):
        """Mask of cells that are visible, and therefore editable."""
        filters = self._filters() if isinstance(filters, str) else filters
        if filters is None or not len(cells):
            return np.ones(len(cells), bool)
        low, high = filters
        centres = (cells + 0.5) * self.map.resolution
        return np.all((centres >= low) & (centres <= high), axis=1) & self.slice.mask(centres)

    def _shown_cells(self, chunk, filters="unset"):
        cells = self.map.cells(chunk)
        return cells[self.shown(cells, filters)]

    def _levels(self, chunks):
        """Detail level for each of the given chunk keys at the current camera position.

        Chunks outside the view are drawn at the coarsest level, and when the whole scene would exceed the
        cube budget the farthest chunks are coarsened first.
        """
        if not len(chunks):
            return {}
        everything = list(self.map.chunks)
        origin = np.array([KeySet.chunk_origin(chunk) for chunk in everything], float)
        size = self.map.resolution
        centres = (origin + CHUNK / 2.0) * size
        radius = CHUNK * size * 0.87
        camera = self.viewport.renderer.GetActiveCamera()
        eye = np.array(camera.GetPosition())
        levels = self.view.level_for(centres, radius, eye, self.viewport.pixel_angle())
        distance = np.linalg.norm(centres - eye, axis=1)
        sx, sy, ahead = self.viewport.project(centres)
        width, height = self.viewport.renderer.GetSize()
        margin = radius / (np.maximum(distance, 1e-6) * max(self.viewport.pixel_angle(), 1e-9))
        outside = (sx < -margin) | (sx > width + margin) | (sy < -margin) | (sy > height + margin)
        levels[(outside | ~ahead) & (distance > radius)] = MAX_LEVEL
        counts = np.array([self.shown_counts.get(chunk, len(self.map.chunks[chunk])) for chunk in everything], float)
        far_first = np.argsort(-distance)
        for _ in range(MAX_LEVEL):
            drawn = counts / 4.0 ** levels
            excess = drawn.sum() - CUBE_BUDGET
            if excess <= 0:
                break
            candidates = far_first[levels[far_first] < MAX_LEVEL]
            saved = np.cumsum(drawn[candidates] * 0.75)
            levels[candidates[:int(np.searchsorted(saved, excess)) + 1]] += 1
        table = dict(zip(everything, levels.tolist()))
        return {chunk: table[chunk] for chunk in chunks}

    def refresh(self, chunks=None, render=True):
        """Redraw the given chunks (all of them by default) after cells, the selection or the filters changed."""
        if chunks is None:
            chunks = set(self.map.chunks) | set(self.view.actors)
            self.shown_counts, self.chunk_bounds = {}, {}
        chunks = list(chunks)
        filters = self._filters()
        levels = self._levels([chunk for chunk in chunks if chunk in self.map.chunks])
        added = self.map.added
        added_chunks = set(KeySet.split(added)[0].tolist()) if len(added) else set()
        size = self.map.resolution
        for chunk in chunks:
            if chunk not in self.map.chunks:
                self.view.update(chunk, np.zeros((0, 3), np.int64), None, 0)
                self.shown_counts.pop(chunk, None)
                self.chunk_bounds.pop(chunk, None)
                continue
            cells = self.map.cells(chunk)
            self.chunk_bounds[chunk] = (cells.min(axis=0) * size, (cells.max(axis=0) + 1) * size)
            cells = cells[self.shown(cells, filters)]
            self.shown_counts[chunk] = len(cells)
            flags = np.full(len(cells), NORMAL, np.uint8)
            if len(cells) and (chunk in added_chunks or chunk in self.selected.chunks):
                keys = pack(cells)
                if chunk in added_chunks:
                    flags[np.isin(keys, added)] = ADDED
                if chunk in self.selected.chunks:
                    flags[np.isin(keys, self.selected.keys(chunk))] = SELECTED
            self.view.update(chunk, cells, flags, levels[chunk])
        self._index_chunks()
        self.changed()
        if render:
            self.viewport.render()

    def _index_chunks(self):
        ids = list(self.chunk_bounds)
        self._chunk_ids = np.array(ids, np.int64)
        self._chunk_low = np.array([self.chunk_bounds[c][0] for c in ids]).reshape(-1, 3)
        self._chunk_high = np.array([self.chunk_bounds[c][1] for c in ids]).reshape(-1, 3)
        if len(ids):
            self.data_bounds = (self._chunk_low.min(axis=0), self._chunk_high.max(axis=0))

    def update_levels(self):
        """Switch chunks to the detail level that suits the current camera distance."""
        chunks = list(self.map.chunks)
        wanted = self._levels(chunks)
        stale = [chunk for chunk in chunks if self.view.levels.get(chunk, wanted[chunk]) != wanted[chunk]]
        if stale:
            self.refresh(stale)

    def recolor(self, render=True):
        self.changed()
        if render:
            self.viewport.render()

    def look_from(self, direction, up):
        low, high = self.data_bounds if len(self.map) else (-np.ones(3), np.ones(3))
        self.viewport.look_from(direction, up, (low[0], high[0], low[1], high[1], low[2], high[2]))

    def reset_range(self):
        self.ranges.reset()
        self.refresh()

    def set_tool(self, name):
        self.tool = name
        self.hover_actor.VisibilityOff()
        self.viewport.set_default_cursor(Qt.ArrowCursor if name == "view" else Qt.CrossCursor)
        self.viewport.render()

    def edit(self, add=None, remove=None, label=""):
        added, removed = self.map.apply(add=add, remove=remove)
        if added or removed:
            self._after_change()
            self.status(self.tr("status_edit", what=label, a=added, r=removed))
        else:
            self.status(self.tr("status_no_change", what=label))

    def select(self, keys, mode="add"):
        """Change the selection with visible, occupied keys: 'add', 'remove' or 'replace'."""
        keys = np.asarray(keys, np.int64)
        if len(keys):
            keys = keys[self.map.contains(keys)]
            keys = keys[self.shown(unpack(keys))]
        if mode == "remove":
            touched = self.selected.remove(keys)
        elif mode == "replace":
            touched = self.selected.clear() | self.selected.add(keys)
        else:
            touched = self.selected.add(keys)
        self.refresh(touched)

    def delete_selection(self):
        if len(self.selected):
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
        self.status(self.tr("status_islands", n=count, m=len(self.selected)), 10000)

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

    def _keys_in_box(self):
        low, high = self.box.bounds()
        if not len(self._chunk_ids):
            return EMPTY
        near = np.all((self._chunk_high >= low) & (self._chunk_low <= high), axis=1)
        filters = self._filters()
        parts = []
        for chunk in self._chunk_ids[near].tolist():
            cells = self._shown_cells(chunk, filters)
            centres = (cells + 0.5) * self.map.resolution
            parts.append(pack(cells[np.all((centres >= low) & (centres <= high), axis=1)]))
        return np.concatenate(parts) if parts else EMPTY

    def pick(self, origin, direction):
        """First visible voxel along a ray -> (cell, face axis, outward sign) or None; only chunks on the ray are searched."""
        if not len(self._chunk_ids):
            return None
        hits, entry = ray_boxes(origin, direction, self._chunk_low, self._chunk_high)
        order = np.argsort(entry)
        best = None
        filters = self._filters()
        half = self.map.resolution / 2.0
        for index, distance in zip(hits[order], entry[order]):
            if best is not None and distance > best[3]:
                break
            cells = self._shown_cells(int(self._chunk_ids[index]), filters)
            found = ray_pick(origin, direction, (cells + 0.5) * self.map.resolution, half, with_distance=True)
            if found is not None and (best is None or found[3] < best[3]):
                best = (cells[found[0]], found[1], found[2], found[3])
        return None if best is None else best[:3]

    def set_box(self, low, high):
        self.box.set(low, high)
        self.show_box.setChecked(True)
        self._box_changed()

    def box_from_selection(self):
        if len(self.selected):
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
        self.edit(add=pack(self.editable(cells)), label=self.tr("box_fill"))

    def editable(self, cells):
        """Cells inside the visible range and on the kept side of the slice."""
        cells = cells[in_range(cells)]
        if not self.panel_alive or not len(cells):
            return cells
        centres = (cells + 0.5) * self.map.resolution
        low, high = self.ranges.bounds()
        keep = np.all((centres >= low) & (centres <= high), axis=1) & self.slice.mask(centres)
        return cells[keep]

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

    def target_cells(self, x, y, tool=None):
        """Cells a tool (the active one by default) would change at a screen position, or None."""
        tool = tool or self.tool
        size = self.map.resolution
        width = self.brush.value()
        offsets = np.arange(width) - width // 2
        origin, direction = self.viewport.ray(x, y)
        hit = self.pick(origin, direction)
        if hit is None:
            if tool != "add" or abs(direction[2]) < 1e-9:
                return None
            distance = (self.plane.value() - origin[2]) / direction[2]
            if distance <= 0:
                return None
            point = origin + distance * direction
            base = np.array([np.floor(point[0] / size), np.floor(point[1] / size),
                             np.floor(self.plane.value() / size + 1e-6)], np.int64)
            axis = 2
        else:
            cell, axis, sign = hit
            base = cell.copy()
            if tool == "add":
                base[axis] += sign
        if tool == "add":
            u, v = [a for a in range(3) if a != axis]
            cells = np.repeat(base[None, :], width * width, axis=0)
            grid_u, grid_v = np.meshgrid(offsets, offsets, indexing="ij")
            cells[:, u] += grid_u.ravel()
            cells[:, v] += grid_v.ravel()
        else:
            cells = base[None, :] + np.stack(np.meshgrid(offsets, offsets, offsets, indexing="ij"), -1).reshape(-1, 3)
        return self.editable(cells)

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
        detail = self.tr("ruler_detail_voxel", **result)
        return short, detail

    def adjust_brush(self, step):
        self.brush.stepBy(step)

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
            short, detail = self._ruler_text(measure(self.ruler.first, point, self.map.resolution))
            self.ruler.preview(point, short)
        self.viewport.render()

    def _measure_click(self, x, y):
        point = self.measure_point(x, y)
        if point is None:
            return
        point = self._ruler_target(point)
        if self.ruler.pending:
            self.measurement = measure(self.ruler.first, point, self.map.resolution)
            short, detail = self._ruler_text(self.measurement)
            self.ruler.finish(point, short)
            self.ruler_label.setText(detail)
            self.status(detail, 0)
            self.overlay.add(dict(self.measurement, a=self.ruler.first.copy(), b=self.ruler.second.copy()))
        else:
            self.ruler.marker_size = self.map.resolution * 0.35
            self.ruler.start(point)
            self.ruler_label.setText(self.tr("ruler_second"))
            self.status(self.tr("ruler_second"), 0)
        self.viewport.render()

    def measure_point(self, x, y):
        """Where the cursor ray meets a visible voxel: the surface point, or the voxel centre when snapping."""
        origin, direction = self.viewport.ray(x, y)
        half = self.map.resolution / 2.0
        hit = self.pick(origin, direction)
        if hit is None:
            return None
        cell, axis, sign = hit
        centre = (cell + 0.5) * self.map.resolution
        self.hover_source.SetBounds(*[centre[a] + s * half * 1.08 for a in range(3) for s in (-1, 1)])
        self.hover_actor.GetProperty().SetColor(*RULER_RGB)
        self.hover_actor.VisibilityOn()
        if self.ruler_snap.isChecked():
            return centre.copy()
        distance = (centre[axis] + sign * half - origin[axis]) / direction[axis]
        return origin + distance * direction

    def _hover(self, x, y):
        if self.tool == "view":
            return
        if self.tool == "measure":
            self._measure_hover(x, y)
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
        if self.tool == "measure":
            self._measure_click(x, y)
            return
        cells = self.target_cells(x, y)
        if cells is None or not len(cells):
            return
        keys = pack(cells)
        if self.tool == "select":
            self.select(keys, "remove" if ctrl else "add")
        elif self.tool == "delete":
            self.edit(remove=keys, label=self.tr("tool_delete"))
        else:
            self.edit(add=keys, label=self.tr("tool_add"))
        self._hover(x, y)

    def _right_click(self, x, y):
        cells = self.target_cells(x, y, "select")
        if cells is not None and len(cells) and len(self.selected):
            before = len(self.selected)
            self.select(pack(cells), "remove")
            self.status(self.tr("status_deselected", n=before - len(self.selected)))

    def _chunks_in_rectangle(self, corner_a, corner_b):
        """Chunk keys whose bounding box overlaps a screen rectangle."""
        if not len(self._chunk_ids):
            return []
        low, high = self._chunk_low, self._chunk_high
        corners = np.stack([np.where(np.array(mask, bool), high, low)
                            for mask in ((i, j, k) for i in (0, 1) for j in (0, 1) for k in (0, 1))], axis=1)
        sx, sy, ahead = self.viewport.project(corners.reshape(-1, 3))
        sx, sy, ahead = sx.reshape(-1, 8), sy.reshape(-1, 8), ahead.reshape(-1, 8)
        x0, x1 = sorted((corner_a[0], corner_b[0]))
        y0, y1 = sorted((corner_a[1], corner_b[1]))
        partly_behind = ~ahead.all(axis=1)
        overlap = (sx.max(axis=1) >= x0) & (sx.min(axis=1) <= x1) & (sy.max(axis=1) >= y0) & (sy.min(axis=1) <= y1)
        return self._chunk_ids[(overlap | partly_behind) & ahead.any(axis=1)].tolist()

    def _rectangle(self, corner_a, corner_b, subtract):
        self.hover_actor.VisibilityOff()
        filters = self._filters()
        parts = [self._shown_cells(chunk, filters) for chunk in self._chunks_in_rectangle(corner_a, corner_b)]
        cells = np.vstack(parts) if parts else np.zeros((0, 3), np.int64)
        chosen = self.viewport.rectangle_hits((cells + 0.5) * self.map.resolution, corner_a, corner_b,
                                              self.front_only.isChecked(), self.tolerance.value(), self.map.resolution)
        self.select(pack(cells[chosen]), "remove" if subtract else "add")
        self.status(self.tr("status_rectangle", n=len(chosen), t=len(self.selected)))
