"""Editor for occupied-voxel maps (OctoMap octrees and voxel archives)."""
import time

import numpy as np

from . import convert, formats, labels, loss
from .editor import Editor
from .label_tools import VoxelLabeling
from .timeline import LabelBar
from .formats import CLOUD, GRID, VOXEL
from .grid import FREE, UNKNOWN
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
TOOL_RGB = {"select": (1.0, 0.2, 0.8), "delete": (1.0, 0.15, 0.1), "add": (0.2, 1.0, 0.3), "label": (0.3, 0.85, 0.45),
            "smart": (0.61, 0.48, 0.94)}
EDIT_TOOLS = (("view", "H"), ("select", "V"), ("delete", "E"), ("add", "B"), ("measure", "I"))
LABEL_TOOLS = (("view", "H"), ("select", "V"), ("label", "B"), ("smart", "W"), ("measure", "I"))
MAX_FILL_CELLS = 2_000_000
CUBE_BUDGET = 6_000_000
CACHE_BUDGET = 24_000_000
SYNC_CHUNKS = 24
OUT, IN, CROSS = 0, 1, 2
DEFAULTS = {"brush": 1, "plane": 0.0, "front_only": True, "tolerance": 0.10, "island": 20,
            "box": [(-0.2, 0.2)] * 3, "show_box": False, "range": [(-RANGE_LIMIT, RANGE_LIMIT)] * 3,
            "slice": SLICE_DEFAULTS, "snap": False}


POINT_FORMATS = ("pcd", "ply", "xyz", "las")


class VoxelEditor(VoxelLabeling, Editor):
    kind = VOXEL
    export_filters = (("OctoMap binary", "bt"), ("OctoMap full", "ot"), ("Voxel archive", "npz"),
                      ("PCD point cloud", "pcd"), ("PLY point cloud", "ply"), ("LAS point cloud", "las"),
                      ("XYZ text", "xyz"), ("CSV text", "csv"), ("NumPy array", "npy"))

    def __init__(self, window):
        super().__init__(window)
        self.map = VoxelMap()
        self.source = None
        self.selected = KeySet()
        self._selection_steps = []
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
        self._level_timer.setInterval(30)
        self._level_timer.timeout.connect(self.update_levels)
        self._closed = False
        self._pending = []
        self._stale = set()
        self._clip = {}
        self._slice_timer = QtCore.QTimer()
        self._slice_timer.setSingleShot(True)
        self._slice_timer.setInterval(0)
        self._slice_timer.timeout.connect(self._refine)
        self._camera_watch = self.viewport.renderer.GetActiveCamera().AddObserver(
            "ModifiedEvent", lambda *_: None if self._closed else self._level_timer.start())
        self.hover_source, self.hover_actor = self.viewport.outline((1, 1, 1), 2.5)
        self.box_source, self.box_actor = self.viewport.outline((1.0, 0.85, 0.1))
        self.box_gizmo = BoxGizmo(self.viewport, self._box_dragged, Snap(self.map.resolution))
        self.slice_gizmo = SliceGizmo(self.viewport, self._slice_dragged, Snap(self.map.resolution))
        self.viewport.gizmos = [self.slice_gizmo, self.box_gizmo]
        self.ruler = Ruler3D(self.viewport.renderer)
        self.label_bar = LabelBar(self.widget, lambda: self.tr, lambda on: self._protect_from_bar(on))
        self.overlay = MeasureOverlay(self.widget, lambda entry: self._ruler_text(entry)[1], self._show_measurement,
                                      lambda: self.tr)
        self.overlay.below = self.label_bar
        self.viewport.band_allowed = lambda: self.tool != "measure"
        self.viewport.paint_allowed = lambda: self.tool in ("select", "delete", "label", "smart")
        self.viewport.on_paint = self._paint
        self.viewport.on_paint_end = self._paint_end
        self._stroke = None
        self._init_voxel_labels()
        self.measurement = None
        self.data_bounds = (np.zeros(3), np.ones(3))
        self._previous_mode = (False, 2)
        self._refresh_timer = QtCore.QTimer()
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)
        self._refresh_timer.timeout.connect(self.filters_changed)

    def changes(self):
        return self.map.changes()

    def read(self, path):
        keys, resolution, leaves = formats.read_voxels(path)
        document = VoxelMap(keys, resolution)
        document.leaves = leaves
        if formats.detect(path) in ("bt", "ot", "npz"):
            self.read_voxel_label_files(document, path)
        return document

    def set_document(self, payload, path=None, fmt=None, progress=None):
        """payload: a VoxelMap, or (keys, resolution[, source]) where source is the cloud the voxels came from.

        source holds the points (xyz, table) and, for a labeled cloud, their labels and the voxel classes they voted.
        """
        self.source = None
        if not isinstance(payload, VoxelMap):
            self.source = payload[2] if len(payload) > 2 else None
            payload = VoxelMap(*payload[:2])
        self.map = payload
        self._voxel_labels_from(payload, self.source, path)
        self.path, self.format = path, fmt
        self.selected = KeySet()
        self._selection_steps = []
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
        self.refresh(render=False, progress=progress)

    def export(self, path, fmt=None):
        if not len(self.map):
            raise ValueError(self.tr("empty_map"))
        fmt = fmt or formats.detect(path)
        if self.vlabels.any and fmt in POINT_FORMATS:
            centres = convert.voxels_to_points(self.map.occupied, self.map.resolution)
            formats.save_cloud(path, centres, self._voxel_point_table(centres), fmt)
            self.classes.save(path + ".labels.yaml")
            return
        formats.save_voxels(path, self.map.occupied, self.map.resolution, fmt, self.map.leaves)
        if fmt in ("bt", "ot", "npz"):
            self._write_voxel_labels(path, fmt)

    def losses(self, fmt):
        out = loss.voxel_losses(self.map.leaves, fmt)
        if self.vlabels.any and fmt == "npy":
            out.append((loss.FIELDS, "label"))
        if self.source is not None:
            out.append((loss.POINTS, ""))
        return out

    @property
    def tools(self):
        return LABEL_TOOLS if self.label_mode else EDIT_TOOLS

    @property
    def dirty(self):
        return self.map.dirty or self.voxel_label_dirty()

    def mark_saved(self):
        marked = set(KeySet.split(self.map.added)[0].tolist())
        self.map.mark_saved()
        self.vlabels.mark_saved()
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
        self.step_back(self._order, self._redo_order, True)

    def redo(self):
        self.step_back(self._redo_order, self._order, False)

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

        if self.label_mode:
            self.build_voxel_label_section(layout)
            self.build_voxel_smart_section(layout)

        group = Section(t("brush"), "brush")
        form = W.QFormLayout(group)
        self.brush = int_spin(1, 31, values["brush"], t("cells"))
        self.brush.setSingleStep(2)
        self.brush.setToolTip(t("brush_tip"))
        form.addRow(t("brush_size"), self.brush)
        hint = W.QLabel(t("brush_keys"))
        hint.setStyleSheet("color: gray;")
        form.addRow(hint)
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
        row.addWidget(button(t("clear_selection"), self.clear_selection, icon="clear_selection"))
        form.addRow(row)
        group.add_to(layout)

        group = Section(t("islands"), "islands")
        form = W.QFormLayout(group)
        self.island_size = int_spin(1, 1_000_000, values["island"], t("voxels_suffix"))
        form.addRow(t("island_size"), self.island_size)
        form.addRow(select_button(t("select_islands"), self.select_islands, t("islands_tip"), icon="islands_pick"))
        group.add_to(layout)

        group = Section(t("box"), "box")
        group.setToolTip(t("box_handles_tip"))
        grid = W.QGridLayout(group)
        self.box = AxisRanges(grid, 0, values["box"], step, self._box_changed)
        self.show_box = W.QCheckBox(t("show_box"))
        self.show_box.setChecked(values["show_box"])
        self.show_box.toggled.connect(self._box_changed)
        grid.addWidget(self.show_box, 3, 0, 1, 2)
        grid.addWidget(button(t("box_from_selection"), self.box_from_selection, icon="box_fit"), 3, 2)
        grid.addWidget(select_button(t("box_select"), self.box_select, icon="box_select"), 4, 0, 1, 3)
        grid.addWidget(danger_button(t("box_delete"), self.box_delete, icon="box_erase_in"), 5, 0, 1, 3)
        grid.addWidget(add_button(t("box_fill"), self.box_fill, t("box_fill_tip"), icon="box_fill"), 6, 0, 1, 3)
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
        form.addRow(button(t("ruler_clear"), self.clear_ruler, icon="ruler_clear"))
        group.add_to(layout)

        self.slice = SliceControls(t, values["slice"], step, self._slice_changed, self.restore_view)
        self.slice.group.add_to(layout)

        group = Section(t("visible_range"), "visible_range")
        group.setToolTip(t("range_tip"))
        grid = W.QGridLayout(group)
        self.ranges = AxisRanges(grid, 0, values["range"], step, lambda *_: self.filters_changed())
        grid.addWidget(button(t("show_all"), self.reset_range, icon="show_all"), 3, 0, 1, 3)
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
            self.panel_values.update({"brush": self.brush.value(), "plane": self.plane.value(),
                                      "front_only": self.front_only.isChecked(), "tolerance": self.tolerance.value(),
                                      "island": self.island_size.value(), "box": self.box.values(),
                                      "show_box": self.show_box.isChecked(), "range": self.ranges.values(),
                                      "slice": self.slice.values(), "snap": self.ruler_snap.isChecked()})
            if self.label_mode:
                self.panel_values.update(self.voxel_label_values())

    def view_actions(self):
        return [(self.tr(f"view_{name}"), lambda d=direction, u=up: self.look_from(d, u), keys)
                for name, direction, up, keys in VIEWS]

    def selection_actions(self):
        return {"delete": self.delete_selection, "select_all": self.select_all, "invert": self.invert_selection,
                "clear": self.clear_selection, "back": self.selection_back}

    def conversions(self):
        return [(self.tr("to_grid"), self.to_grid), (self.tr("to_cloud"), self.to_cloud)]

    def extra_actions(self):
        return super().extra_actions() + (self.voxel_label_actions() if self.label_mode else [])

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
        """Visible cells of a chunk; chunks wholly inside or outside the filters need no per-cell test."""
        state = self._clip.get(chunk, IN)
        if state == OUT:
            return np.zeros((0, 3), np.int64)
        cells = self.map.cells(chunk)
        return cells if state == IN else cells[self.shown(cells, filters)]

    def _bounds(self, chunk):
        size = self.map.resolution
        cells = self.map.cells(chunk)
        self.chunk_bounds[chunk] = (cells.min(axis=0) * size, (cells.max(axis=0) + 1) * size)

    def _classify(self, chunks, filters):
        """Record for each chunk whether the range and slice leave it whole (IN), hide it (OUT) or cut it (CROSS)."""
        if filters is None:
            for chunk in chunks:
                self._clip[chunk] = IN
            return
        low, high = filters
        half = self.map.resolution / 2
        sliced = self.slice.values()["on"]
        for chunk in chunks:
            first, last = self.chunk_bounds[chunk][0] + half, self.chunk_bounds[chunk][1] - half
            outside = (last < low).any() or (first > high).any()
            inside = (first >= low).all() and (last <= high).all()
            if sliced:
                side = self.slice.box_side(first, last)
                outside, inside = outside or side < 0, inside and side > 0
            self._clip[chunk] = OUT if outside else IN if inside else CROSS

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

    def _draw(self, chunk, level, filters, added, added_chunks):
        """Build one detail level of one chunk from the current cells, selection and filters."""
        cells = self._shown_cells(chunk, filters)
        self.shown_counts[chunk] = len(cells)
        flags = np.full(len(cells), NORMAL, np.uint8)
        by_class = bool(self.by_class_on() and len(cells))
        keys = pack(cells) if len(cells) and (by_class or chunk in added_chunks or chunk in self.selected.chunks) else None
        if keys is not None:
            if chunk in added_chunks and not by_class:
                flags[np.isin(keys, added)] = ADDED
            if chunk in self.selected.chunks:
                flags[np.isin(keys, self.selected.keys(chunk))] = SELECTED
        self.view.build(chunk, cells, flags, level, self.voxel_colours(keys) if by_class else None)

    def _marks(self):
        added = self.map.added
        return added, (set(KeySet.split(added)[0].tolist()) if len(added) else set())

    def refresh(self, chunks=None, render=True, progress=None):
        """Redraw chunks after their cells or the selection changed (all of them by default).

        A handful of chunks is redrawn at once; a large set is queued and redrawn in short slices, nearest first.
        """
        everything = chunks is None
        if everything:
            chunks = set(self.map.chunks) | set(self.view.actors)
            self.shown_counts, self.chunk_bounds, self._clip, self._stale = {}, {}, {}, set()
        chunks = list(chunks)
        filters = self._filters()
        alive = [chunk for chunk in chunks if chunk in self.map.chunks]
        for chunk in chunks:
            if chunk in self.map.chunks:
                self._bounds(chunk)
            else:
                self.view.forget(chunk)
                self._stale.discard(chunk)
                for table in (self.shown_counts, self.chunk_bounds, self._clip):
                    table.pop(chunk, None)
        self._classify(alive, filters)
        self._index_chunks()
        if everything or len(alive) <= SYNC_CHUNKS:
            levels = self._levels(alive)
            added, added_chunks = self._marks()
            for done, chunk in enumerate(alive):
                if progress and done % 64 == 0:
                    progress(done, len(alive))
                self.view.forget(chunk)
                self._stale.discard(chunk)
                self._draw(chunk, levels[chunk], filters, added, added_chunks)
        else:
            for chunk in alive:
                if self._clip[chunk] == IN:
                    self.shown_counts[chunk] = len(self.map.chunks[chunk])
            self._stale.update(alive)
            self.update_levels()
        self.changed()
        if render:
            self.viewport.render()

    def filters_changed(self):
        """Apply a new visible range or slice: only chunks the boundary cuts through are rebuilt."""
        filters = self._filters()
        chunks = list(self.map.chunks)
        before = dict(self._clip)
        self._classify(chunks, filters)
        for chunk in chunks:
            state = self._clip[chunk]
            if state == OUT:
                self.view.hide(chunk)
                self.shown_counts[chunk] = 0
            elif state == CROSS or before.get(chunk, IN) != IN:
                self._stale.add(chunk)
            if state == IN:
                self.shown_counts[chunk] = len(self.map.chunks[chunk])
        for chunk in list(self.selected.chunks):
            if self._clip.get(chunk, IN) != IN:
                keys = self.selected.keys(chunk)
                self.selected.remove(keys[~self.shown(unpack(keys), filters)] if self._clip[chunk] == CROSS else keys)
                self._stale.add(chunk)
        self.update_levels()
        self.changed()

    def _index_chunks(self):
        ids = list(self.chunk_bounds)
        self._chunk_ids = np.array(ids, np.int64)
        self._chunk_low = np.array([self.chunk_bounds[c][0] for c in ids]).reshape(-1, 3)
        self._chunk_high = np.array([self.chunk_bounds[c][1] for c in ids]).reshape(-1, 3)
        if len(ids):
            self.data_bounds = (self._chunk_low.min(axis=0), self._chunk_high.max(axis=0))

    def shutdown(self):
        self._closed = True
        self._pending = []
        self._level_timer.stop()
        self._slice_timer.stop()
        self._refresh_timer.stop()
        self.viewport.renderer.GetActiveCamera().RemoveObserver(self._camera_watch)
        self.view.clear()

    def update_levels(self):
        """Queue what needs drawing: stale chunks and chunks whose detail level no longer suits the camera.

        Cached levels are swapped in at once; everything else is built in short slices, nearest chunks first.
        Chunks drawn finer than necessary are left alone while the scene stays within the cube budget.
        """
        if self._closed:
            return
        self.viewport.fit_axes()
        chunks = [chunk for chunk in self.map.chunks if self._clip.get(chunk, IN) != OUT]
        wanted = self._levels(chunks)
        pending, finer = [], []
        for chunk in chunks:
            level, current = wanted[chunk], self.view.levels.get(chunk)
            if chunk in self._stale:
                pending.append(chunk)
            elif current == level:
                continue
            elif current is not None and current < level:
                finer.append(chunk)
            elif self.view.has(chunk, level):
                self.view.show(chunk, level)
            else:
                pending.append(chunk)
        centres = {}
        if pending or finer:
            eye = np.array(self.viewport.renderer.GetActiveCamera().GetPosition())
            for chunk in pending + finer:
                low, high = self.chunk_bounds[chunk]
                centres[chunk] = float(np.linalg.norm((low + high) / 2 - eye))
        excess = self.view.drawn() - CUBE_BUDGET
        for chunk in sorted(finer, key=lambda c: -centres[c]):
            if excess <= 0:
                break
            excess -= self.view.count(chunk) * (1 - 0.25 ** (wanted[chunk] - self.view.levels[chunk]))
            if self.view.has(chunk, wanted[chunk]):
                self.view.show(chunk, wanted[chunk])
            else:
                pending.append(chunk)
        self._pending = [(chunk, wanted[chunk]) for chunk in sorted(pending, key=lambda c: centres[c])]
        self.viewport.render()
        if self._pending:
            self._slice_timer.start()

    def _refine(self, budget=0.012):
        """Draw queued chunks, nearest first, for a few milliseconds; then let the window breathe."""
        if self._closed or not self._pending:
            return
        filters = self._filters()
        added, added_chunks = self._marks()
        started = time.perf_counter()
        while self._pending and time.perf_counter() - started < budget:
            chunk, level = self._pending.pop(0)
            if chunk not in self.map.chunks or self._clip.get(chunk, IN) == OUT:
                continue
            if chunk in self._stale:
                self._stale.discard(chunk)
                self.view.forget(chunk)
            elif self.view.has(chunk, level):
                continue
            self._draw(chunk, level, filters, added, added_chunks)
        self.view.trim(CACHE_BUDGET)
        self.changed()
        self.viewport.render()
        if self._pending:
            self._slice_timer.start()

    def finish_levels(self):
        """Build every queued detail level now (used by tests and screenshots)."""
        while self._pending:
            self._refine(1.0)

    def recolor(self, render=True):
        self.changed()
        if render:
            self.viewport.render()

    def look_from(self, direction, up):
        low, high = self.data_bounds if len(self.map) else (-np.ones(3), np.ones(3))
        self.viewport.look_from(direction, up, (low[0], high[0], low[1], high[1], low[2], high[2]))

    def reset_range(self):
        self.ranges.reset()
        self.filters_changed()

    def set_tool(self, name):
        self.tool = name
        self.hover_actor.VisibilityOff()
        self.viewport.set_default_cursor(Qt.ArrowCursor if name == "view" else Qt.CrossCursor)
        self.viewport.render()

    def edit(self, add=None, remove=None, label=""):
        added, removed = self.map.apply(add=add, remove=remove)
        if added or removed:
            self._record("map")
            self._after_change()
            self.status(self.tr("status_edit", what=label, a=added, r=removed))
        else:
            self.status(self.tr("status_no_change", what=label))

    def select(self, keys, mode="add", trusted=False, review=False):
        """Change the selection: 'add', 'remove' or 'replace'. Keys are checked to be occupied and visible
        unless the caller already took them from the visible cells (trusted).

        In labeling mode with protection on, labeled voxels stay out of the selection unless a review tool asks.
        """
        keys = np.asarray(keys, np.int64)
        if len(keys) and not trusted:
            keys = keys[self.map.contains(keys)]
            keys = keys[self.shown(unpack(keys))]
        if len(keys) and mode != "remove" and not review and self.protecting():
            keys = keys[self.vlabels.get(keys) == labels.UNLABELED]
        if mode == "remove":
            keys = keys[self.selected.contains(keys)]
            step = ("remove", keys)
            touched = self.selected.remove(keys)
        elif mode == "replace":
            step = ("replace", self.selection)
            touched = self.selected.clear() | self.selected.add(keys)
        else:
            keys = keys[~self.selected.contains(keys)]
            step = ("add", keys)
            touched = self.selected.add(keys)
        if touched:
            self._selection_steps = self._selection_steps[-63:] + [step]
        self.refresh(touched)

    def selection_back(self):
        """Take back the most recent selection step (one click, rectangle or filter)."""
        if not self._selection_steps:
            return
        kind, keys = self._selection_steps.pop()
        if kind == "add":
            touched = self.selected.remove(keys)
        else:
            touched = self.selected.clear() if kind == "replace" else set()
            keys = keys[self.map.contains(keys)] if len(keys) else keys
            touched |= self.selected.add(keys)
        self.refresh(touched)
        self.status(self.tr("selection_back") + f": {len(self.selected)}")

    def delete_selection(self):
        """Delete removes the selected voxels; in labeling mode it only clears their labels."""
        if self.label_mode:
            return self.assign_selection(labels.UNLABELED)
        if len(self.selected):
            self.edit(remove=self.selection, label=self.tr("delete_selection"))

    def clear_selection(self):
        self.select(EMPTY, "replace")

    def select_all(self):
        self.select(self.visible_keys, "replace", trusted=True)

    def invert_selection(self):
        self.select(np.setdiff1d(self.visible_keys, self.selection, assume_unique=True), "replace", trusted=True)

    def select_islands(self):
        size = self.island_size.value()
        (keys, count), dialog = self.window.busy(self.tr("select_islands") + " …", lambda: self.map.islands(size))
        dialog.finish()
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
        self.filters_changed()
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
        self.filters_changed()
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
        self.select(self._keys_in_box(), trusted=True)

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
        """Voxels -> points. A map that came from a cloud gives back that cloud's own points, not voxel centres.

        Each returning point keeps its own class; only voxels relabeled here pass their class on to their points.
        """
        if not self.ask_relabel_back():
            return None
        origin = {"resolution": self.map.resolution, "classes": self.classes}
        source, vlabels = self.source, self.vlabels

        def work():
            if source is not None:
                restored = convert.restore(source["xyz"], source["table"], self.map.resolution, self.map,
                                           source.get("cls"), source.get("inst"), vlabels, source.get("outside"))
                origin.update(cls=restored["cls"], inst=restored["inst"])
                return CLOUD, (restored["xyz"], restored["table"], origin)
            keys = self.map.occupied
            if vlabels.any:
                origin.update(cls=vlabels.get(keys), inst=None)
            return CLOUD, (convert.voxels_to_points(keys, self.map.resolution), None, origin)
        return work

    def to_grid(self):
        if not len(self.map):
            return None
        low, high = self.data_bounds
        band = ask_numbers(self.window, self.tr("band_title"), [
            (self.tr("band_low"), float(low[2]), -RANGE_LIMIT, RANGE_LIMIT, 3),
            (self.tr("band_high"), float(high[2]), -RANGE_LIMIT, RANGE_LIMIT, 3),
            (self.tr("empty_as_free"), False)])
        if band is None:
            return None
        empty = FREE if band[2] else UNKNOWN
        keys, size, vlabels, classes = self.map.occupied, self.map.resolution, self.vlabels, self.classes
        if not vlabels.any:
            return lambda: (GRID, convert.voxels_to_grid(keys, size, *sorted(band[:2]), empty))

        def work():
            obstacles, free = convert.split_by_role(keys, vlabels.get(keys), classes)
            return GRID, convert.voxels_to_grid(obstacles, size, *sorted(band[:2]), empty, free)
        return work

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
        if self.tool == "smart":
            self._smart_click(x, y, ctrl)
            return
        cells = self.target_cells(x, y)
        if cells is None or not len(cells):
            return
        keys = pack(cells)
        if self.tool == "select":
            self.select(keys, "remove" if ctrl else "add")
        elif self.tool == "delete":
            self.edit(remove=keys, label=self.tr("tool_delete"))
        elif self.tool == "label":
            self.label_voxels(keys, labels.UNLABELED if ctrl else self.active_class, "tool_label")
        else:
            self.edit(add=keys, label=self.tr("tool_add"))
        self._hover(x, y)

    def _paint(self, x, y, subtract=False):
        """Ctrl + drag: keep applying the brush under the cursor while the view stays still.

        The left button applies the tool; the right button takes back (deselects, or clears labels).
        """
        if self._stroke is None:
            self._stroke = (len(self._selection_steps), self.map.undo_depth(), len(self._order),
                            self.vlabels.undo_depth())
        cells = self.target_cells(x, y)
        if cells is None or not len(cells):
            return
        if self.tool in ("select", "smart"):
            self.select(pack(cells), "remove" if subtract else "add")
        elif self.tool == "label":
            self.label_voxels(pack(cells), labels.UNLABELED if subtract else self.active_class, "tool_label")
        elif not subtract:
            self.edit(remove=pack(cells), label=self.tr("tool_delete"))
        self._hover(x, y)

    def _paint_end(self):
        """Fold a finished stroke into a single selection step and a single undo step."""
        if self._stroke is None:
            return
        steps, depth, order, label_depth = self._stroke
        self._stroke = None
        painted = [keys for kind, keys in self._selection_steps[steps:] if kind == "add"]
        if len(painted) > 1:
            self._selection_steps[steps:] = [("add", np.unique(np.concatenate(painted)))]
        squashed = self.map.squash(depth)
        if self.vlabels.undo_depth() - label_depth > 1:
            self.vlabels.squash(label_depth)
            squashed = True
        if squashed:
            self._order[order:] = self._order[order:order + 1]

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
        self.select(pack(cells[chosen]), "remove" if subtract else "add", trusted=True)
        self.status(self.tr("status_rectangle", n=len(chosen), t=len(self.selected)))
