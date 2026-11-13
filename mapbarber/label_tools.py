"""Labeling for the point cloud editor: classes, assignment rules, assisted picking, review, instances and frames."""
import copy
import hashlib
import json
import os

import numpy as np

from . import boxes as box_labels
from . import export, formats, labels, tracking
from .labels import ClassList, LabelLayer, UNLABELED
from .qt import QtCore, QtGui, QtWidgets, run
from .safeio import replacing
from .voxels import pack
from .widgets import (add_button, ask_numbers, button, danger_button, int_spin, RANGE_LIMIT, Section, select_button, spin,
                      tint)

Qt = QtCore.Qt
FRAME_POINT_LIMIT = 40_000_000
LOST_SCORE = 0.25
LABEL_DEFAULTS = {"track_reach": 1.5, "track_accept": 0.6, "object_gap": 0.2, "min_points": 20, "show_boxes": True, "robust_boxes": True, "clearance": 0.15, "stop_bends": True, "rule": "unlabeled", "rule_class": 1, "smart": "object", "reach": 5.0, "flatness": 0.03, "bend": 30.0, "gap": 0.10,
                  "at_once": False, "own_instance": False, "fill_radius": 0.15, "island": 20, "frame_radius": 0.10,
                  "paint_frame": -1}
SMART_MODES = ("object", "plane", "surface")
WORK_LIMIT = 1_500_000
INSIDE_FORMATS = ("pcd", "ply", "xyz", "las")
NAME, POINTS, SHOWN, LOCKED = range(4)
EMPTY = np.zeros(0, np.int64)


def swatch(rgb, size=14):
    image = QtGui.QPixmap(size, size)
    image.fill(QtGui.QColor(*rgb))
    return QtGui.QIcon(image)


def ask_class(parent, t, classes, number=None):
    """Dialog for a new class, or for editing class `number`; returns (number, name, rgb, role) or None."""
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(t("class_edit") if number else t("class_add"))
    form = QtWidgets.QFormLayout(dialog)
    number_box = int_spin(1, 65535, number or classes.next_free())
    number_box.setEnabled(number is None)
    name_box = QtWidgets.QLineEdit(classes.name(number) if number else "")
    colour = [classes.rgb(number) if number else labels.shade(classes.next_free())]
    colour_button = QtWidgets.QPushButton()

    def paint():
        colour_button.setIcon(swatch(colour[0], 32))

    def choose():
        picked = QtWidgets.QColorDialog.getColor(QtGui.QColor(*colour[0]), dialog)
        if picked.isValid():
            colour[0] = (picked.red(), picked.green(), picked.blue())
            paint()

    colour_button.clicked.connect(choose)
    paint()
    role_box = QtWidgets.QComboBox()
    for role in labels.ROLES:
        role_box.addItem(t(f"role_{role}"), role)
    role_box.setCurrentIndex(labels.ROLES.index(classes.role(number)) if number else 0)
    role_box.setToolTip(t("role_tip"))
    form.addRow(t("class_number"), number_box)
    form.addRow(t("class_name"), name_box)
    form.addRow(t("class_colour"), colour_button)
    form.addRow(t("class_role"), role_box)
    wins = QtWidgets.QCheckBox(t("class_wins"))
    wins.setChecked(bool(number and classes.items[number]["wins"]))
    wins.setToolTip(t("class_wins_tip"))
    form.addRow(wins)
    soft = QtWidgets.QCheckBox(t("class_soft"))
    soft.setChecked(bool(number and classes.items[number]["soft"]))
    soft.setToolTip(t("class_soft_tip"))
    form.addRow(soft)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if run(dialog) != QtWidgets.QDialog.Accepted:
        return None
    return (number_box.value(), name_box.text().strip() or f"class {number_box.value()}", colour[0],
            role_box.currentData(), wins.isChecked(), soft.isChecked())



class ClassHistory:
    """Class list changes go into the same undo history as the labels."""

    def _remember_classes(self):
        """Call before changing the class list."""
        self._class_undo.append(copy.deepcopy(self.classes.items))
        self._class_redo.clear()
        self._record_step("classes")

    def _swap_classes(self, source, target):
        if not source:
            return False
        target.append(copy.deepcopy(self.classes.items))
        self.classes.items = source.pop()
        if self.active_class not in self.classes:
            self.active_class = (self.classes.numbers() or [UNLABELED])[0]
        self._after_classes()
        return True


class Labeling(ClassHistory):
    """Mixed into the point cloud editor. Assisted tools only ever select; a class key then labels the selection."""

    @property
    def label_panel(self):
        """True while the labeling sections of the panel exist (labeling mode with the panel shown)."""
        return self.panel_alive and self.label_mode

    def _init_labels(self):
        self.label_mode = False
        self._edit_tool = "view"
        self._wrote_recovery = False
        self._delete_target = None
        self._colour_before = None
        self.labels = LabelLayer(0)
        self._class_undo, self._class_redo = [], []
        self._frame_undo, self._frame_redo = [], []
        self._box_undo, self._box_redo = [], []
        self.box_store, self._boxes_saved, self.active_box = {}, {}, None
        self._box_actor = self._box_focus = None
        self._above = {}
        self._stray_counts = {}
        self._anchor_object = 0
        self.classes = ClassList("indoor")
        self.active_class = self.classes.numbers()[0]
        self.hidden_classes, self.locked_classes = set(), set()
        self.sequence, self.frame_ids, self.frame_starts = None, [], np.array([0])
        self.frame_store, self.frame_dirty = {}, set()
        self._order, self._redo_order = [], []
        self._last_smart = None
        self._palette = self.classes.palette(1)
        self.panel_values.update(LABEL_DEFAULTS)
        self._stats_timer = QtCore.QTimer()
        self._stats_timer.setSingleShot(True)
        self._stats_timer.setInterval(250)
        self._stats_timer.timeout.connect(self._update_stats)
        self._autosave = QtCore.QTimer()
        self._autosave.setInterval(60_000)
        self._autosave.timeout.connect(self.write_recovery)
        self._autosave.start()

    # ---- documents

    def _class_file(self, path):
        return path + ".labels.yaml"

    def _write_boxes(self, path):
        if self.box_store.get(None) or os.path.isfile(path + ".boxes.json"):
            box_labels.save(path + ".boxes.json", self.box_store.get(None, []), self.classes)

    def _initial_labels(self, xyz, table, path):
        """Labels a newly opened cloud starts with: handed over by a conversion, a file beside it, or its own fields."""
        cls = inst = None
        self._pending_boxes = box_labels.load(path + ".boxes.json") if path and os.path.isfile(path + ".boxes.json") else []
        origin = self.origin or {}
        if origin.get("cls") is not None:
            cls, inst = origin["cls"], origin.get("inst")
            if origin.get("classes") is not None:
                self.classes = origin["classes"]
        elif path:
            sidecar = formats.label_sidecar(path)
            if os.path.isfile(sidecar):
                try:
                    cls, inst = formats.read_label_file(sidecar, len(xyz))
                except ValueError:
                    cls = None
            for candidate in (self._class_file(path), os.path.join(os.path.dirname(path), "labels.yaml")):
                if os.path.isfile(candidate):
                    self.classes = ClassList.load(candidate)
                    break
        if cls is None:
            cls, inst = formats.table_labels(table)
        if cls is not None:
            self.classes.ensure(cls)
        return cls, inst

    def _reset_labels(self, count, cls, inst, fresh=True):
        """New label layer; a fresh document also starts a new undo history (other frames keep theirs)."""
        self.labels = LabelLayer(count, cls, inst)
        if fresh:
            self._order, self._redo_order = [], []
            self._class_undo, self._class_redo = [], []
            self._frame_undo, self._frame_redo = [], []
            self._box_undo, self._box_redo = [], []
            self.box_store, self._boxes_saved, self.active_box = {}, {}, None
        self._last_smart = None
        if fresh and getattr(self, "_pending_boxes", None):
            self.box_store[None], self._pending_boxes = self._pending_boxes, []
            self.boxes_saved()
        if self.active_class not in self.classes and len(self.classes):
            self.active_class = self.classes.numbers()[0]
        self._classes_changed(redraw=False)

    @property
    def box_dirty(self):
        """Frames (or None for a single cloud) whose boxes differ from what was last saved."""
        return {key for key, found in self.box_store.items() if found != self._boxes_saved.get(key, [])}

    def boxes_saved(self):
        self._boxes_saved = copy.deepcopy(self.box_store)

    def label_dirty(self):
        return self.labels.dirty or bool(self.frame_dirty) or bool(self.box_dirty)

    def pending_count(self):
        """Suggested labels nobody confirmed yet, in the open document (every frame of a sequence)."""
        if self.sequence is None:
            return int(self.labels.pending[self.cloud.alive].sum())
        on_screen = set(self.frame_ids)
        stored = sum(int(item[2].sum()) for index, item in self.frame_store.items() if index not in on_screen)
        return stored + int(self.labels.pending.sum())

    def _write_labeled(self, path, fmt):
        """Save the cloud with its labels: inside the file when the format can hold them, else beside it."""
        xyz, table = self.cloud.surviving()
        if not len(xyz):
            raise ValueError(self.tr("empty_map"))
        fmt = fmt or formats.detect(path)
        sidecar = formats.label_sidecar(path)
        self._write_boxes(path)
        if not self.labels.any:
            formats.save_cloud(path, xyz, table, fmt)
            return
        alive = self.cloud.alive
        cls, inst = self.labels.cls[alive], self.labels.inst[alive]
        inside = fmt in INSIDE_FORMATS
        formats.save_cloud(path, xyz, formats.with_labels(xyz, table, cls, inst) if inside else table, fmt)
        if not inside or os.path.isfile(sidecar):
            formats.write_label_file(sidecar, cls, inst)
        self.classes.save(self._class_file(path))

    def _save_frames(self):
        self._store_frames()
        for index in sorted(self.frame_dirty):
            cls, inst, _ = self.frame_store[index]
            self.sequence.save_labels(index, cls, inst)
        for index in sorted(self.box_dirty):
            folder = os.path.join(self.sequence.folder, "boxes")
            os.makedirs(folder, exist_ok=True)
            box_labels.save(os.path.join(folder, self.sequence.names[index] + ".json"), self.box_store.get(index, []),
                            self.classes, self.sequence.names[index])
        self.classes.save(self.sequence.class_file)

    def save_labels_only(self):
        """Write the labels to a file beside the cloud and leave the cloud file untouched."""
        if self.sequence is not None:
            return self.window.save()
        if not self.path or self.cloud.dirty:
            return self.status(self.tr("labels_only_refused"), 8000)
        formats.write_label_file(formats.label_sidecar(self.path), self.labels.cls, self.labels.inst)
        self.classes.save(self._class_file(self.path))
        self.labels.mark_saved()
        self.clear_recovery()
        self.changed()
        self.status(self.tr("labels_only_saved", name=os.path.basename(formats.label_sidecar(self.path))), 8000)

    def load_labels(self):
        """Take labels from a file (for example a model's predictions) as suggestions to review."""
        if self.sequence is not None:
            return self.load_frame_labels()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self.window, self.tr("labels_load"), os.path.dirname(self.path or ""),
                                                        "Labels (*.label *.npz *.npy *.txt);;* (*)")
        if not path:
            return
        try:
            cls, inst = formats.read_label_file(path)
            if len(cls) == len(self.labels):
                ids = np.arange(len(cls))
            elif len(cls) == len(self.cloud):
                ids = self.cloud.ids()
            else:
                raise ValueError(self.tr("labels_count", n=len(cls), m=len(self.cloud)))
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.critical(self.window, self.tr("labels_load"), str(error))
            return
        self.classes.ensure(cls)
        self._classes_changed(redraw=False)
        keep = np.isin(ids, self._writable(ids[cls != UNLABELED]))
        self._commit(self.labels.assign(ids[keep], cls[keep], inst[keep], pending=True), "labels_load")

    def export_standard(self, folder=None, wanted=None):
        """Write the labels in benchmark layouts.

        wanted: [SemanticKITTI, KITTI object, OpenPCDet, KITTI tracking, include suggestions]:
        - SemanticKITTI: velodyne/*.bin, labels/*.label (class and object number), poses.txt, calib.txt and
          semantic-kitti.yaml;
        - KITTI object: velodyne/*.bin, label_2/*.txt (a file for every frame) and calib/*.txt, ImageSets/train.txt;
        - OpenPCDet custom dataset: openpcdet/points/*.npy, openpcdet/labels/*.txt, openpcdet/ImageSets/train.txt;
        - KITTI tracking: tracking/label_02/0000.txt (object numbers as track ids) and tracking/calib/0000.txt.
        Suggestions not yet accepted (pale points, boxes marked '?') are left out unless the last option is on.
        """
        t = self.tr
        if wanted is None:
            answer = ask_numbers(self.window, t("label_export"), [(t("export_semantic_kitti"), True),
                                                                  (t("export_kitti_boxes"), True),
                                                                  (t("export_pcdet_boxes"), True),
                                                                  (t("export_kitti_tracking"), self.sequence is not None),
                                                                  (t("export_include_pending"), False)])
            if answer is None:
                return
            wanted = answer
        semantic, objects, pcdet, tracks, pending_too = (list(wanted) + [False] * 5)[:5]
        tracks = tracks and self.sequence is not None
        folder = folder or QtWidgets.QFileDialog.getExistingDirectory(self.window, t("label_export"),
                                                                      os.path.dirname(self.path or "") or os.getcwd())
        if not folder:
            return
        if self.sequence is not None:
            self._store_frames()
            for key in range(len(self.sequence)):
                self._boxes_of(key)
        accept = self.track_accept.value() if self.label_panel else self.panel_values["track_accept"]

        def sure(box):
            return pending_too or box.get("key") or box.get("accepted") or box.get("score", 1.0) >= accept

        def write_all():
            from .frames import kitti_calibration
            if self.sequence is not None:
                keys, names = list(range(len(self.sequence))), self.sequence.names
                poses, calib = self.sequence.poses, self.sequence.kitti_calibration()
            else:
                keys, names, poses, calib = [None], ["000000"], None, kitti_calibration()
            link = export.rectified(calib)
            left_out = [0, 0]

            def frames():
                for key, name in zip(keys, names):
                    if key is None:
                        alive = self.cloud.alive
                        xyz, table = self.cloud.surviving()
                        cls, inst, waiting = self.labels.cls[alive], self.labels.inst[alive], self.labels.pending[alive]
                    else:
                        xyz, table = self.sequence.load(key)
                        stored = self.frame_store.get(key)
                        cls, inst = stored[:2] if stored is not None else self.sequence.labels(key)
                        waiting = stored[2] if stored is not None else np.zeros(len(cls), bool)
                    if not pending_too and waiting.any():
                        cls, inst = cls.copy(), inst.copy()
                        cls[waiting], inst[waiting] = UNLABELED, 0
                        left_out[0] += int(waiting.sum())
                    intensity = table["intensity"] if table is not None and "intensity" in table.dtype.names else None
                    if pcdet:
                        os.makedirs(os.path.join(folder, "openpcdet", "points"), exist_ok=True)
                        export.pcdet_points(os.path.join(folder, "openpcdet", "points", name + ".npy"), xyz, intensity)
                    yield name, xyz, intensity, cls, inst

            if semantic:
                written = export.semantic_kitti(folder, frames(), self.classes, poses)
            else:
                written = 0
                for name, xyz, intensity, _, _ in frames():
                    if objects:
                        os.makedirs(os.path.join(folder, "velodyne"), exist_ok=True)
                        cloud = np.column_stack([xyz, np.zeros(len(xyz)) if intensity is None else intensity])
                        with replacing(os.path.join(folder, "velodyne", name + ".bin")) as part:
                            cloud.astype("<f4").tofile(part)
                    written += 1
            boxes, rows = 0, []
            for number, (key, name) in enumerate(zip(keys, names)):
                every = self._boxes_of(key)
                found = [box for box in every if sure(box)]
                left_out[1] += len(every) - len(found)
                boxes += len(found)
                rows += [(number, box) for box in found]
                if objects:
                    for sub in ("label_2", "calib"):
                        os.makedirs(os.path.join(folder, sub), exist_ok=True)
                    export.kitti_objects(os.path.join(folder, "label_2", name + ".txt"), found, self.classes, link)
                    export.kitti_calib(os.path.join(folder, "calib", name + ".txt"), calib)
                if pcdet:
                    os.makedirs(os.path.join(folder, "openpcdet", "labels"), exist_ok=True)
                    export.pcdet_boxes(os.path.join(folder, "openpcdet", "labels", name + ".txt"), found, self.classes)
            for on, base in ((objects, folder), (pcdet, os.path.join(folder, "openpcdet"))):
                if on:
                    os.makedirs(os.path.join(base, "ImageSets"), exist_ok=True)
                    with replacing(os.path.join(base, "ImageSets", "train.txt")) as part, open(part, "w") as f:
                        f.write("".join(name + "\n" for name in names))
            if tracks:
                for sub in ("label_02", "calib"):
                    os.makedirs(os.path.join(folder, "tracking", sub), exist_ok=True)
                export.kitti_tracking(os.path.join(folder, "tracking", "label_02", "0000.txt"), rows, self.classes, link)
                export.kitti_calib(os.path.join(folder, "tracking", "calib", "0000.txt"), calib)
            return written, boxes, left_out

        try:
            written, boxes, left_out = self.compute(t("label_export") + " …", write_all)
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.critical(self.window, t("label_export"), str(error))
            return
        text = t("status_exported", f=written, b=boxes, folder=folder)
        if any(left_out):
            text += "  ·  " + t("export_skipped", n=left_out[0], b=left_out[1])
        self.status(text, 15000)

    def load_frame_labels(self, folder=None):
        """Suggestions for every frame from a folder holding one label file per frame (same name as the frame).

        They only fill points that have no label yet, so nothing already labeled is overwritten.
        """
        folder = folder or QtWidgets.QFileDialog.getExistingDirectory(self.window, self.tr("labels_load"), self.path)
        if not folder:
            return
        self._store_frames()
        found = suggested = 0
        changes = {}
        for index, name in enumerate(self.sequence.names):
            path = next((os.path.join(folder, name + ext) for ext in (".label", ".npz", ".npy", ".txt")
                         if os.path.isfile(os.path.join(folder, name + ext))), None)
            if path is None:
                continue
            cls, inst, pending = self._frame_labels(index)
            try:
                guess, _ = formats.read_label_file(path, len(cls))
            except (OSError, ValueError):
                continue
            found += 1
            take = (cls == UNLABELED) & (guess != UNLABELED)
            if take.any():
                local = np.flatnonzero(take)
                changes[index] = (local,) + self._frame_values(index, local)
                cls, pending = cls.copy(), pending.copy()
                cls[take], pending[take] = guess[take], True
                self.frame_store[index] = (cls, inst, pending)
                self.frame_dirty.add(index)
                suggested += int(take.sum())
                self.classes.ensure(guess)
        self._frames_step(changes)
        self.show_frames(self.frame_ids, store=False)
        self._classes_changed()
        self.changed()
        self.status(self.tr("status_propagated", n=suggested, f=found), 10000)

    # ---- recovery

    def _recovery_path(self):
        if not self.path:
            return None
        folder = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.CacheLocation) or \
            os.path.join(os.path.expanduser("~"), ".cache", "mapbarber")
        return os.path.join(folder, "recovery", hashlib.sha1(self.path.encode()).hexdigest() + ".npz")

    def write_recovery(self):
        """Keep unsaved labels in the cache folder so that a crash does not lose them."""
        path = self._recovery_path()
        if path is None or not self.label_dirty():
            return
        arrays = {}
        if self.sequence is not None:
            self._store_frames()
            for index in self.frame_dirty:
                arrays[f"cls_{index}"], arrays[f"inst_{index}"] = self.frame_store[index][:2]
        else:
            arrays = {"cls": self.labels.cls, "inst": self.labels.inst}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".part", "wb") as f:
                np.savez_compressed(f, **arrays)
            os.replace(path + ".part", path)
            self._wrote_recovery = True
        except OSError:
            pass

    def clear_recovery(self, only_own=False):
        """Remove the recovery copy; on closing, only the one this window wrote (another window may own it)."""
        path = self._recovery_path()
        if path and os.path.isfile(path) and (self._wrote_recovery or not only_own):
            os.remove(path)
        self._wrote_recovery = False

    def offer_recovery(self):
        """After opening: bring back labels a previous session did not get to save."""
        path = self._recovery_path()
        if not path or not os.path.isfile(path):
            return
        answer = QtWidgets.QMessageBox.question(self.window, self.tr("recover_title"), self.tr("recover_text"))
        if answer != QtWidgets.QMessageBox.Yes:
            return self.clear_recovery()
        try:
            with np.load(path) as archive:
                if self.sequence is None:
                    if len(archive["cls"]) == len(self.labels):
                        ids = np.arange(len(self.labels))
                        self._commit(self.labels.assign(ids, archive["cls"], archive["inst"]), "recover_title")
                else:
                    for name in [n for n in archive.files if n.startswith("cls_")]:
                        index = int(name[4:])
                        self.frame_store[index] = (archive[name], archive[f"inst_{index}"],
                                                   np.zeros(len(archive[name]), bool))
                        self.frame_dirty.add(index)
                    self.show_frames(self.frame_ids, store=False)
        except (OSError, ValueError, KeyError):
            self.clear_recovery()

    # ---- drawing and visibility

    def _classes_changed(self, redraw=True):
        top = max([int(self.labels.cls.max(initial=0))] + self.classes.numbers() + [1])
        self._palette = self.classes.palette(top)
        self._sync_label_bar()
        if self.label_panel:
            self._fill_classes()
            if redraw:
                self.refresh()

    def _class_filter(self, ids):
        """Drop points of hidden classes (labeling mode): what is hidden cannot be selected or labeled."""
        if not self.label_mode or not self.hidden_classes or not len(ids):
            return ids
        return ids[~np.isin(self.labels.cls[ids], np.fromiter(self.hidden_classes, np.int64))]

    def label_colours(self, ids, mode):
        if mode == "instance":
            return labels.instance_colours(self.labels.inst[ids])
        colours = self._palette[np.minimum(self.labels.cls[ids], len(self._palette) - 1)].copy()
        inst = self.labels.inst[ids]
        if inst.any():
            shade = np.where(inst > 0, 0.72 + 0.5 * ((inst * 0.6180339887) % 1.0), 1.0)
            colours = np.clip(colours * shade[:, None], 0, 255).astype(np.uint8)
        pending = self.labels.pending[ids]
        colours[pending] = colours[pending] // 2 + 120
        return colours

    def _show_labels(self):
        if self.label_panel and self.colour_box.currentData() not in ("label", "instance"):
            index = self.colour_box.findData("label")
            self.colour_box.blockSignals(True)
            self.colour_box.setCurrentIndex(index)
            self.colour_box.blockSignals(False)
            self.refresh()
            return True
        return False

    # ---- assignment

    def _rule(self):
        return self.rule_box.currentData() if self.label_panel else self.panel_values["rule"]

    def _writable(self, ids):
        """Points a label write may touch under the current rule, locks and frame restriction."""
        ids = np.asarray(ids, np.int64)
        rule = self._rule()
        target = self.rule_class.currentData() if self.label_panel else self.panel_values["rule_class"]
        ids = self.labels.allowed(ids, rule if rule in ("unlabeled", "only") else "all", target, self.locked_classes)
        frame = self.paint_frame.currentData() if self.label_panel and self.sequence is not None else -1
        if frame is not None and frame >= 0 and len(ids):
            ids = ids[self.cloud.table["frame"][ids] == frame]
        return ids

    def _record_step(self, kind):
        self._order.append(kind)
        self._redo_order.clear()

    def _group_since(self, depth):
        """Fold the history steps recorded since `depth` into one, so a single Ctrl+Z takes them all back."""
        kinds = []
        for entry in self._order[depth:]:
            kinds += list(entry) if isinstance(entry, tuple) else [entry]
        if len(kinds) > 1:
            self._order[depth:] = [tuple(kinds)]

    def _after_classes(self):
        self._classes_changed()

    def _commit(self, changed, what):
        """Book-keeping after the label layer changed: history, redraw and a status line."""
        if not changed:
            return self.status(self.tr("status_no_change", what=self.tr(what)))
        self._record_step("label")
        self._after_labels()
        kept = getattr(self, "_protected", 0)
        self._protected = 0
        self.status(self.tr("status_labeled", what=self.tr(what), n=changed)
                    + (f"  ·  {self.tr('status_protected', n=kept)}" if kept else ""))

    def _after_labels(self):
        ids = self.labels.touched
        if int(self.labels.cls.max(initial=0)) >= len(self._palette):
            self._classes_changed(redraw=False)
        if not self._show_labels():
            self.refresh(self.chunks.touched(ids))
        self._stats_timer.start()
        if self.label_panel and len(self.labels.touched) < 2_000_000:
            self._fill_instances()

    def assign(self, ids, number, what="label_assign"):
        """Label points. Protection keeps labeled points from being relabeled, but never from being cleared."""
        asked = len(ids)
        if number == UNLABELED:
            ids = self.labels.allowed(np.asarray(ids, np.int64), "all", locked=self.locked_classes)
        else:
            ids = self._writable(ids)
        self._protected = asked - len(ids)
        instance = None
        if self.label_panel and self.own_instance.isChecked() and number != UNLABELED:
            instance = self.labels.next_instance()
        elif number == UNLABELED:
            instance = 0
        self._commit(self.labels.assign(ids, number, instance), what)

    def assign_selection(self, number=None):
        """Label the selected points with a class (the active one by default) and let go of the selection."""
        number = self.active_class if number is None else number
        if number != UNLABELED:
            self.set_active(number)
        if not self.selected.any():
            return
        ids = self.selection
        self.selected[ids] = False
        self._selection_steps = []
        self.assign(ids, number)
        self.refresh(self.chunks.touched(ids))

    def set_active(self, number):
        if number in self.classes:
            self.active_class = number
            if self.label_panel:
                self._mark_active()
            self._sync_label_bar()

    def class_key(self, position):
        """Ctrl+1..9: the n-th class of the list. With a selection it labels it, otherwise it becomes the active class."""
        numbers = self.classes.numbers()
        if position <= len(numbers):
            self.assign_selection(numbers[position - 1])

    def pick_class(self, x, y):
        """Alt + click: make the class under the cursor the active one."""
        point = self._pick(x, y)
        if point is None:
            return
        ids = self._near(point, self._marker_size() * 4)
        if len(ids):
            nearest = ids[np.argmin(np.linalg.norm(self.cloud.xyz[ids] - point, axis=1))]
            number = int(self.labels.cls[nearest])
            if number != UNLABELED:
                self.set_active(number)
                self.status(self.tr("status_picked", name=self.classes.name(number)))

    def select_class(self):
        ids = self.visible_ids
        self.select(ids[self.labels.cls[ids] == self.active_class], "replace", review=True)

    def protecting(self):
        return self.label_mode and self._rule() != "all"

    def toggle_protect(self):
        """P: switch between protecting labeled points and overwriting them."""
        self._protect_from_bar(self._rule() == "all")

    def _protect_from_bar(self, on):
        rule = "unlabeled" if on else "all"
        if self.label_panel:
            self.rule_box.setCurrentIndex(self.rule_box.findData(rule))
        else:
            self.panel_values["rule"] = rule
        self._sync_label_bar()
        self.status(self.tr("rule_" + rule), 4000)

    def _sync_label_bar(self):
        """Keep the corner strip in step with the active class and the protection rule."""
        self.label_bar.setVisible(self.label_mode)
        if self.label_mode:
            self.label_bar.update_state(self.classes.name(self.active_class), self.classes.rgb(self.active_class),
                                        self.protecting())
        self.overlay.place()

    # ---- labeling mode

    def switch_label_mode(self, on):
        """Enter or leave labeling mode: its own tools, panel and colours; leaving restores the editing state."""
        if on == self.label_mode:
            return
        self.label_mode = on
        if on:
            self._edit_tool = self.tool
            self._colour_before = self.panel_values["colour"]
            self.panel_values["colour"] = "label"
            self.tool = "label" if self.tool == "delete" else self.tool if self.tool in dict(self.tools) else "view"
        else:
            self.panel_values["colour"] = self._colour_before or "height"
            self.tool = self._edit_tool if self._edit_tool in dict(self.tools) else "view"
        self.hover_actor.VisibilityOff()
        self.preview_actor.VisibilityOff()
        self._sync_label_bar()
        self._draw_boxes()

    # ---- assisted picking

    def _near(self, centre, radius):
        """Visible point indices within `radius` of a position."""
        filters = self._filters()
        parts = []
        for chunk in self.chunks.near(centre, radius):
            ids = self.chunk_ids(int(chunk), filters)
            offset = self.cloud.xyz[ids] - centre
            parts.append(ids[np.einsum("ij,ij->i", offset, offset) <= radius * radius])
        return np.concatenate(parts) if parts else EMPTY

    def smart_ids(self, point, mode=None):
        """Points the assisted pick finds from a clicked position, searched within `reach` of it.

        Points that labeling may not change (protected, locked) are never picked and never join anything,
        but they still count as scenery: the ground under an object is found even when it is already labeled.
        """
        mode = mode or self.smart_box.currentData()
        ids = self._near(point, self.reach.value())
        if not len(ids):
            return EMPTY
        if len(ids) > WORK_LIMIT:
            self.status(self.tr("smart_too_many", n=len(ids)), 8000)
            return EMPTY
        local = self.cloud.xyz[ids]
        seed = int(np.argmin(np.einsum("ij,ij->i", local - point, local - point)))
        usable = np.ones(len(ids), bool)
        if self._rule() in ("unlabeled", "only"):
            usable = np.isin(ids, self._writable(ids))
        if not usable[seed]:
            self.status(self.tr("status_protected", n=1), 6000)
            return EMPTY
        text = self.tr("smart") + " …"
        if mode == "object":
            settings = self._connected_settings()
            return ids[self.compute(text, lambda: self._connected(local, seed, ids, usable, settings))]
        open_ids = np.flatnonzero(usable)
        start = int(np.searchsorted(open_ids, seed))
        if mode == "plane":
            radius, flatness = max(self.radius.value(), 3 * self.flatness.value()), self.flatness.value()
            found = self.compute(text, lambda: labels.plane_at(local[open_ids], start, radius, flatness))
        else:
            gap, bend = self.gap.value(), self.bend.value()
            found = self.compute(text, lambda: labels.grow(local[open_ids], start, gap, bend))
        return ids[open_ids[found]]

    def _connected_settings(self):
        """What the connected-object pick needs from the panel, read before it runs."""
        return {"clearance": self.clearance.value(), "cell": self.ground_cell.value(), "slope": self.ground_slope.value(),
                "bend": self.bend.value() if self.stop_bends.isChecked() else None, "gap": self.gap.value(),
                "reach": self.reach.value(), "frames": self.cloud.table["frame"] if self.sequence is not None else None}

    def _connected(self, local, seed, ids, usable, settings=None):
        """Connected points around the seed, kept from running into what the object merely touches.

        Two things stop the search: a wide surface that faces another way (when 'stop at sharp bends' is on),
        and the ground, from which points within `clearance` are kept apart. The second matters for sparse
        LiDAR scans, whose points lie on scan lines and give no usable surface directions. An object found
        above the ground then takes back its own lowest points, down to a third of the clearance.
        """
        values = settings or self._connected_settings()
        clearance, part, low = values["clearance"], np.flatnonzero(usable), EMPTY
        if clearance > 0:
            ground = {"cell": values["cell"], "slope": values["slope"], "tolerance": clearance}
            try:
                height = (labels.by_group(local, values["frames"][ids],
                                          lambda points: labels.height_above_ground(points, **ground))
                          if values["frames"] is not None else labels.height_above_ground(local, **ground))
                flat = np.isfinite(height) & (height <= clearance)
                part = np.flatnonzero((flat == flat[seed]) & usable)
                if not flat[seed]:
                    low = np.flatnonzero(flat & usable & (height > clearance / 3.0))
            except ValueError:
                pass
        found = part[labels.connected(local[part], int(np.searchsorted(part, seed)), values["gap"], values["bend"],
                                      values["reach"] / 3.0)]
        return labels.with_feet(local, found, low, values["gap"])

    def _smart_click(self, x, y, ctrl):
        point = self._pick(x, y)
        if point is None:
            return
        ids = self.smart_ids(point)
        self._last_smart = None
        if not len(ids):
            return
        if self.at_once.isChecked() and not ctrl:
            self.assign(ids, self.active_class, "tool_smart")
        else:
            self.select(ids, "remove" if ctrl else "add")
            self._last_smart = point if not ctrl else None
            self.status(self.tr("status_smart", n=len(ids)), 0)

    def adjust_smart(self, step):
        """[ and ] with the assisted tool: loosen or tighten the pick and redo the last one."""
        mode = self.smart_box.currentData()
        box = {"plane": self.flatness, "surface": self.bend}.get(mode, self.gap)
        box.setValue(box.value() * (1.25 if step > 0 else 0.8))
        if self._last_smart is not None and self._selection_steps:
            point = self._last_smart
            self.selection_back()
            self.select(self.smart_ids(point), "add")
            self._last_smart = point
        self.status(f"{self.tr('smart_' + mode)}: {box.value():.3f}", 4000)

    # ---- review

    def progress(self):
        alive = self.cloud.alive
        return int(np.count_nonzero(self.labels.cls[alive])), int(alive.sum())

    def _update_stats(self):
        if self._closed or not self.label_panel:
            return
        counts = self.labels.counts(self.cloud.alive)
        for row in range(self.class_list.topLevelItemCount()):
            item = self.class_list.topLevelItem(row)
            item.setText(POINTS, f"{counts.get(item.data(NAME, Qt.UserRole), 0):,}")
        done, total = self.progress()
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        pending = int(self.labels.pending.sum())
        self._fill_instances()
        if self._refresh_strays():
            self._fill_boxes()
        self.progress_bar.setFormat(self.tr("label_progress", p=100.0 * done / max(total, 1), n=total - done)
                                    + (f"  ·  {self.tr('label_pending', n=pending)}" if pending else ""))

    def _sample(self, ids, limit=2_000_000):
        return ids[::max(1, -(-len(ids) // limit))]

    def next_unlabeled(self):
        """Select the largest group of visible points that has no label yet and bring it into view."""
        ids = self.visible_ids
        ids = self._sample(ids[self.labels.cls[ids] == UNLABELED])
        if not len(ids):
            return self.status(self.tr("review_done"), 8000)
        group = labels.components(self.cloud.xyz[ids], self.gap.value())
        chosen = ids[group == np.bincount(group).argmax()]
        self.select(chosen, "replace")
        self.focus(self.cloud.xyz[chosen])
        self.status(self.tr("status_smart", n=len(chosen)), 0)

    def focus(self, points):
        low, high = points.min(axis=0), points.max(axis=0)
        pad = max(float((high - low).max()) * 0.5, 4 * self._marker_size())
        camera = self.viewport.renderer.GetActiveCamera()
        direction = np.array(camera.GetPosition()) - np.array(camera.GetFocalPoint())
        low, high = low - pad, high + pad
        self.viewport.look_from(direction, camera.GetViewUp(), (low[0], high[0], low[1], high[1], low[2], high[2]))

    def _busy_select(self, what, find):
        """Select what `find(xyz, cls, ids)` returns (positions into ids), worked out behind the busy dialog."""
        ids = self._sample(self.visible_ids)
        xyz, cls = self.cloud.xyz[ids], self.labels.cls[ids].copy()
        found = ids[self.compute(self.tr(what) + " …", lambda: find(xyz, cls, ids))]
        self._select_filtered(found)

    def select_disagreeing(self):
        """Select labeled points that most of their neighbours contradict: slips of the brush and ragged borders."""
        self._busy_select("review_disagree", lambda xyz, cls, ids: labels.disagreeing(xyz, cls))

    def select_label_islands(self):
        """Select small detached patches of each class."""
        gap, size = self.gap.value(), self.island.value()

        def find(xyz, cls, ids):
            parts = []
            for number in np.unique(cls).tolist():
                if number != UNLABELED:
                    members = np.flatnonzero(cls == number)
                    parts.append(members[labels.small_groups(xyz[members], gap, size)])
            return np.concatenate(parts) if parts else EMPTY
        self._busy_select("review_islands", find)

    def fill_gaps(self):
        """Suggest a class for unlabeled points from the labeled points around them; suggestions wait for review."""
        ids = self._sample(self.visible_ids)
        xyz, cls, radius = self.cloud.xyz[ids], self.labels.cls[ids].copy(), self.fill_radius.value()
        local, guess = self.compute(self.tr("review_fill") + " …", lambda: labels.suggest(xyz, cls, radius))
        ids = ids[local]
        keep = np.isin(ids, self._writable(ids))
        self._commit(self.labels.assign(ids[keep], guess[keep], pending=True), "review_fill")

    def confirm_pending(self):
        """Accept every suggestion on screen: pale points, and boxes marked '?' by auto 3D box labeling."""
        depth = len(self._order)
        accept = self.track_accept.value()
        unsure = [box for key in self._box_keys() for box in self._boxes_of(key)
                  if box.get("score", 1.0) < accept and not box.get("accepted") and not box.get("key")]
        changed = self.labels.confirm()
        if changed or not unsure:
            self._commit(changed, "review_confirm")
        if unsure:
            self._remember_boxes()
            for box in unsure:
                box["accepted"] = True
            self._boxes_changed()
            self._group_since(depth)

    def reject_pending(self):
        ids = np.flatnonzero(self.labels.pending)
        self._commit(self.labels.assign(ids, UNLABELED, 0), "review_reject")

    # ---- instances

    def _instance_scope(self):
        """The points instance tools work on: the selection, or else every point of the active class."""
        if self.selected.any():
            return self.selection
        ids = self.cloud.ids()
        return ids[self.labels.cls[ids] == self.active_class]

    def split_instances(self):
        """Give every connected group its own instance number; groups smaller than the minimum get none.

        Groups never span two classes, and in a sequence never two frames.
        """
        ids = self._instance_scope()
        if not len(ids):
            return
        with self.working(self.tr("instance_split") + " …") as report:
            number, small = self._object_numbers(ids, report)
        self._commit(self.labels.assign(ids, inst=number), "instance_split")
        self.status(self.tr("status_instances", n=len(np.unique(number[number > 0])), s=small), 10000)
        self._fill_instances()

    def _object_numbers(self, ids, report=None):
        """New instance numbers for points, one per connected group: (number per point, points left without one)."""
        key = self.labels.cls[ids].astype(np.int64)
        if self.sequence is not None:
            key = key * len(self.sequence) + self.cloud.table["frame"][ids]
        number = np.zeros(len(ids), np.uint32)
        start, small = self.labels.next_instance(), 0
        values = np.unique(key)
        for done, value in enumerate(values):
            if report:
                report(done, len(values))
            members = np.flatnonzero(key == value)
            group = labels.components(self.cloud.xyz[ids[members]], self.object_gap.value())
            sizes = np.bincount(group)
            big = np.flatnonzero(sizes >= self.min_points.value())
            rank = np.full(len(sizes), -1)
            rank[big] = np.arange(len(big))
            given = rank[group]
            number[members[given >= 0]] = start + given[given >= 0]
            start += len(big)
            small += int((given < 0).sum())
        return number, small

    def merge_instance(self):
        if self.selected.any():
            ids = self.selection
            self._commit(self.labels.assign(ids, inst=self.labels.next_instance()), "instance_merge")
            self._fill_instances()

    def clear_instances(self):
        """Back to classes only: the selection (or the active class) keeps its class and loses its instance numbers."""
        self._dissolve(self._instance_scope())

    def _dissolve(self, ids):
        """Take the instance numbers off points, together with the boxes of instances that no longer exist."""
        numbers = np.unique(self.labels.inst[ids])
        numbers = numbers[numbers > 0]
        depth = len(self._order)
        self._commit(self.labels.assign(ids, inst=0), "instance_clear")
        alive = self.cloud.ids()
        gone = set(numbers[~np.isin(numbers, self.labels.inst[alive])].tolist())
        if gone and any(box.get("instance") in gone for key in self._box_keys() for box in self._boxes_of(key)):
            self._remember_boxes()
            for key in self._box_keys():
                self.box_store[key] = [box for box in self._boxes_of(key) if box.get("instance") not in gone]
            self.active_box = None
            self._boxes_changed()
        self._group_since(depth)
        self._fill_instances()

    def dissolve_instance(self, number):
        """Delete one object: its points keep their class."""
        ids = self.cloud.ids()
        self._dissolve(ids[self.labels.inst[ids] == number])

    def label_delete(self):
        """Delete in labeling mode never removes points.

        It acts on what was clicked last: a box in the box list is deleted, an object in the object list
        is dissolved (its points keep their class), and otherwise the selected points lose their label.
        """
        target, self._delete_target = self._delete_target, None
        if target == "box" and self.active_box is not None:
            return self.delete_box()
        if target is not None and target != "box":
            return self.dissolve_instance(target)
        if self.selected.any():
            self.assign_selection(UNLABELED)

    def _fill_instances(self):
        if not self.label_panel:
            return
        ids = self.cloud.ids()
        ids = ids[self.labels.inst[ids] > 0]
        tree = self.instance_list
        tree.clear()
        if not len(ids):
            return
        numbers, first, counts = np.unique(self.labels.inst[ids], return_index=True, return_counts=True)
        for number, at, count in list(zip(numbers, first, counts))[:2000]:
            cls = int(self.labels.cls[ids[at]])
            item = QtWidgets.QTreeWidgetItem([str(int(number)), self.classes.name(cls), f"{int(count):,}"])
            item.setData(0, Qt.UserRole, int(number))
            item.setIcon(1, swatch(self.classes.rgb(cls)))
            tree.addTopLevelItem(item)

    def _instance_chosen(self, item, *_):
        if item is None:
            return
        ids = self.cloud.ids()
        ids = ids[self.labels.inst[ids] == item.data(0, Qt.UserRole)]
        if len(ids):
            self.select(ids, "replace", review=True)
            self.focus(self.cloud.xyz[ids])
            self._delete_target = item.data(0, Qt.UserRole)

    # ---- 3D boxes

    def _box_keys(self):
        return list(self.frame_ids) if self.sequence is not None else [None]

    def _boxes_of(self, key):
        if key not in self.box_store and key is not None:
            path = os.path.join(self.sequence.folder, "boxes", self.sequence.names[key] + ".json")
            self.box_store[key] = box_labels.load(path) if os.path.isfile(path) else []
            self._boxes_saved[key] = copy.deepcopy(self.box_store[key])
        return self.box_store.setdefault(key, [])

    def _pose(self, key):
        if key is None or self.sequence is None or self.sequence.poses is None:
            return np.eye(4)
        return self.sequence.poses[key]

    def _key_ids(self, key):
        """Indices of the alive points that belong to a frame (or to the whole cloud)."""
        ids = self.cloud.ids()
        if key is None:
            return ids
        return ids[self.cloud.table["frame"][ids] == key]

    def _local(self, key, ids):
        """Coordinates of points in their own frame (the sensor frame of a sequence)."""
        pose = self._pose(key)
        return (self.cloud.xyz[ids] - pose[:3, 3]) @ pose[:3, :3]

    def _remember_boxes(self):
        self._box_undo.append(copy.deepcopy(self.box_store))
        self._box_redo.clear()
        self._record_step("boxes")

    def _swap_boxes(self, source, target):
        if not source:
            return False
        target.append(copy.deepcopy(self.box_store))
        self.box_store = source.pop()
        if self.active_box is not None and self.active_box[1] >= len(self.box_store.get(self.active_box[0], [])):
            self.active_box = None
        self._boxes_changed()
        return True

    def _box_settings(self):
        """(gap between objects, whether stray points are kept out of boxes)."""
        if self.label_panel:
            return self.object_gap.value(), self.robust_boxes.isChecked()
        return self.panel_values["object_gap"], self.panel_values["robust_boxes"]

    def _fit(self, points, cls, number):
        """A box for an object's points and how many of them it leaves out as strays.

        Unless that is switched off, the few points that stand apart from the body do not shape the box.
        """
        gap, robust = self._box_settings()
        box = box_labels.fit(points, cls, number, gap=gap if robust else None)
        return box, box.pop("stray", 0)

    def _boxes_made(self, key, made, strays):
        text = self.tr(key, n=made) if isinstance(key, str) else key
        if strays:
            text += "  ·  " + self.tr("status_stray", n=strays)
        self.status(text, 10000)

    def fit_boxes(self):
        """A box around every instance on screen (instances must exist: split a class into objects first)."""
        self._remember_boxes()
        made = strays = 0
        keys = self._box_keys()
        with self.working(self.tr("boxes_fit") + " …") as report:
            for done, key in enumerate(keys):
                report(done, len(keys))
                ids = self._key_ids(key)
                ids = ids[self.labels.inst[ids] > 0]
                kept = [box for box in self._boxes_of(key) if not box.get("instance")]
                local, inst = self._local(key, ids), self.labels.inst[ids]
                for number in np.unique(inst):
                    members = inst == number
                    cls = int(np.bincount(self.labels.cls[ids[members]]).argmax())
                    box, left_out = self._fit(local[members], cls, int(number))
                    box["key"] = True
                    kept.append(box)
                    made += 1
                    strays += left_out
                self.box_store[key] = kept
        if not made:
            self._box_undo.pop()
            self._order.pop()
            return self.status(self.tr("boxes_none"), 8000)
        self._boxes_changed()
        self._boxes_made("status_boxes", made, strays)

    def boxes_for_class(self):
        """The box workflow for one class: its objects are told apart, and each gets a box.

        Points of the active class that have no object number yet are split into connected objects (objects
        already numbered, for instance after merging by hand, stay as they are). Then every object of the
        class on screen gets an upright box, replacing the boxes made this way before.
        """
        chosen = self.active_class
        ids = self.cloud.ids()
        ids = ids[self.labels.cls[ids] == chosen]
        if not len(ids):
            return self.status(self.tr("boxes_no_class", name=self.classes.name(chosen)), 8000)
        depth = len(self._order)
        fresh = ids[self.labels.inst[ids] == 0]
        keys = self._box_keys()
        with self.working(self.tr("boxes_class", name=self.classes.name(chosen)) + " …") as report:
            if len(fresh):
                number, _ = self._object_numbers(fresh, lambda done, total: report(done, total + len(keys)))
                changed = self.labels.assign(fresh, inst=number)
                if changed:
                    self._record_step("label")
                    self._after_labels()
            self._remember_boxes()
            made = strays = 0
            for done, key in enumerate(keys):
                report(len(keys) // 2 + done, len(keys) + len(keys) // 2)
                mine = self._key_ids(key)
                mine = mine[(self.labels.cls[mine] == chosen) & (self.labels.inst[mine] > 0)]
                kept = [box for box in self._boxes_of(key) if not (box["class"] == chosen and box.get("instance"))]
                local, inst = self._local(key, mine), self.labels.inst[mine]
                for number in np.unique(inst):
                    box, left_out = self._fit(local[inst == number], chosen, int(number))
                    box["key"] = True
                    kept.append(box)
                    made += 1
                    strays += left_out
                self.box_store[key] = kept
        self._group_since(depth)
        self._fill_instances()
        self._boxes_changed()
        self._boxes_made(self.tr("status_class_boxes", name=self.classes.name(chosen), n=made), made, strays)

    def _above_ground(self, key):
        """Indices of a frame's points that stand above the ground (kept until other frames are shown)."""
        if key not in self._above:
            ids = self._key_ids(key)
            tolerance = self.ground_height.value()
            height = labels.height_above_ground(self._local(key, ids), self.ground_cell.value(),
                                                self.ground_slope.value(), tolerance)
            self._above[key] = ids[np.isfinite(height) & (height > tolerance)]
        return self._above[key]

    def track_boxes(self, direction=1):
        """Auto 3D box labeling through the frames on screen, forwards in time (direction 1) or backwards (-1).

        Every box made or corrected by hand (by Auto 3D boxes, from a selection, or edited) is a starting point:
        its object is followed from that frame in the chosen direction until the range ends, the object is lost,
        or the next such box of the same object, which stays as it is. So an object labeled in the middle of the
        range can be followed from there either way. Each frame is judged only by the frame or two before it on
        the way, and the starting frame is the reference: what stood beside the object there without belonging
        to it is not taken later (tracking.Track). Box overlap (where the object was expected against where its
        points put it) and alignment make the score: above the accept score labels are applied, below it they
        arrive as suggestions marked '?', far below it the track ends.
        """
        if self.sequence is None or self.sequence.poses is None:
            return self.status(self.tr("frames_need_poses"), 8000)
        frames = list(self.frame_ids) if direction > 0 else list(self.frame_ids)[::-1]
        starts = [(key, box) for key in frames for box in self._boxes_of(key) if box.get("instance") and box.get("key")]
        if not starts:
            first = next((key for key in frames if any(box.get("instance") for box in self._boxes_of(key))), None)
            starts = [(first, box) for box in self._boxes_of(first) if box.get("instance")] if first is not None else []
        if not starts or len(frames) < 2:
            return self.status(self.tr("track_none"), 10000)
        reach, gap, accept = self.track_reach.value(), self.object_gap.value(), self.track_accept.value()
        least = max(3, self.min_points.value() // 4)
        cls, inst, pending = self.labels.cls, self.labels.inst, self.labels.pending
        keyed = {(key, box["instance"]) for key, box in starts}
        plans = []
        for key, box in starts:
            at = frames.index(key)
            ahead = next((n for n in range(at + 1, len(frames)) if (frames[n], box["instance"]) in keyed), len(frames))
            if ahead > at + 1:
                plans.append((key, box, frames[at:ahead]))
        depth, label_depth = len(self._order), self.labels.undo_depth()
        self._remember_boxes()
        followed = unsure = lost = 0
        total, done = sum(len(path) - 1 for _, _, path in plans), [0]
        title = self.tr("track" if direction > 0 else "track_back") + " …"
        with self.working(title) as report:
            def step():
                done[0] += 1
                report(done[0], total)

            for start, first, path in plans:
                number = first["instance"]
                origin = self._key_ids(start)
                members = origin[(inst[origin] == number) & (cls[origin] == first["class"])]
                if len(members) < 3:
                    done[0] += len(path) - 1
                    continue
                world = self._box_world(start, first)
                track = tracking.Track(world, self.cloud.xyz[members], rigid=not self.classes.soft(first["class"]),
                                       margin=gap / 2.0, gap=gap, aside=self._aside(start, world, members, reach + gap))

                def scene_of(frame, number=number):
                    above = self._above_ground(frame)
                    free = above[(cls[above] == UNLABELED) | pending[above] | (inst[above] == number)]
                    return free, self.cloud.xyz[free]

                before = done[0]
                track.run(path, start, scene_of, reach=reach, gap=gap, least=least, trust=accept, directions=(1,),
                          on_frame=step)
                done[0] = before + len(path) - 1
                for frame, found in track.results.items():
                    sure = found["score"] >= accept
                    ids = found["ids"]
                    ids = ids[~((cls[ids] == track.cls) & (inst[ids] == number) & ~pending[ids])]
                    self.labels.assign(ids, track.cls, number, pending=not sure)
                    stored = box_labels.moved(track.box_in(frame), np.linalg.inv(self._pose(frame)))
                    stored.update(points=int(len(found["ids"])), score=round(found["score"], 3), left=found["left"])
                    self.box_store[frame] = [box for box in self._boxes_of(frame) if box.get("instance") != number]
                    self.box_store[frame].append(stored)
                    followed += 1
                    unsure += not sure
                if track.results:
                    self._face_like(first, world, track.box_in(start))
                lost += len(track.results) < len(path) - 1
        if self.labels.undo_depth() > label_depth:
            self.labels.squash(label_depth)
            self._record_step("label")
            self.labels.touched = np.flatnonzero(self.cloud.alive)
            self._after_labels()
        self._group_since(depth)
        self._fill_instances()
        self._boxes_changed()
        self.status(self.tr("status_tracked", n=followed, u=unsure, l=lost), 12000)

    @staticmethod
    def _face_like(box, world, oriented):
        """Turn a box (in place) to the heading tracking chose, by quarter turns, without changing the space it covers.

        A box is the same box turned half round, or a quarter round with length and width swapped; tracking
        decides which way the object faces from where it went, and the start box should say the same.
        """
        quarter = int(round(((oriented["yaw"] - world["yaw"] + np.pi) % (2 * np.pi) - np.pi) / (np.pi / 2)))
        if quarter % 2:
            box["size"] = [box["size"][1], box["size"][0], box["size"][2]]
        box["yaw"] = float((box["yaw"] + quarter * np.pi / 2 + np.pi) % (2 * np.pi) - np.pi)

    def track_back(self):
        """Auto 3D box labeling backwards in time (see track_boxes)."""
        self.track_boxes(-1)

    def _aside(self, key, world, members, reach):
        """Points of a frame that stand around a box without belonging to its object (world coordinates).

        The frame a track starts from is the reference: what was not part of the object there is not taken later.
        """
        around = self._above_ground(key)
        around = around[box_labels.inside(dict(world, size=[v + 2 * reach for v in world["size"]]), self.cloud.xyz[around])]
        return self.cloud.xyz[np.setdiff1d(around, members)]

    def track_again(self):
        """Follow the chosen box's object again from its frame, keeping the box as it is now.

        Meant for a tracked box corrected by hand (moved, turned, resized or refitted) in the middle of a
        sequence: the correction is carried forwards and backwards through the frames on screen, up to the
        nearest box of the same object made or corrected by hand on either side, which stay as they are. In its
        own frame the box decides which points are the object. In the frames the object is found in again, it
        takes the points the new track gives it, and those it had before but no longer gets lose their label
        (they were a wrong track's). Frames where it is not found again keep what they had.
        """
        if self.sequence is None or self.sequence.poses is None:
            return self.status(self.tr("frames_need_poses"), 8000)
        world = self._active_box_world()
        if world is None or not world.get("instance"):
            return self.status(self.tr("track_again_none"), 10000)
        key, index = self.active_box
        chosen = self.box_store[key][index]
        number, cls, inst, pending = chosen["instance"], self.labels.cls, self.labels.inst, self.labels.pending
        frames = list(self.frame_ids)
        corrected = [frame for frame in frames if frame != key and any(
            box.get("key") and box.get("instance") == number for box in self._boxes_of(frame))]
        before = max((frame for frame in corrected if frame < key), default=-1)
        after = min((frame for frame in corrected if frame > key), default=len(self.sequence))
        segment = [frame for frame in frames if before < frame < after]
        gap, accept = self.object_gap.value(), self.track_accept.value()
        above = self._above_ground(key)
        free = above[(cls[above] == UNLABELED) | pending[above] | (inst[above] == number)]
        members = free[box_labels.inside(dict(world, size=[v + 0.05 for v in world["size"]]), self.cloud.xyz[free])]
        if len(members) < 3:
            return self.status(self.tr("track_again_empty"), 10000)
        depth, label_depth = len(self._order), self.labels.undo_depth()
        self._remember_boxes()
        released = followed = unsure = 0
        with self.working(self.tr("track_again") + " …") as report:
            track = tracking.Track(world, self.cloud.xyz[members], rigid=not self.classes.soft(chosen["class"]),
                                   margin=gap / 2.0, fixed=True, gap=gap,
                                   aside=self._aside(key, world, members, self.track_reach.value() + gap))

            def scene_of(frame):
                ids = self._above_ground(frame)
                ids = ids[(cls[ids] == UNLABELED) | pending[ids] | (inst[ids] == number)]
                return ids, self.cloud.xyz[ids]

            least = max(3, self.min_points.value() // 4)
            tried = [0]

            def step():
                tried[0] += 1
                report(tried[0], len(segment) - 1)

            track.run(segment, key, scene_of, reach=self.track_reach.value(), gap=gap, least=least, trust=accept,
                      on_frame=step)
            found_in = {frame: found["ids"] for frame, found in track.results.items() if frame != key}
            found_in[key] = members
            for frame, ids in found_in.items():
                sure = frame == key or track.results[frame]["score"] >= accept
                mine = self._key_ids(frame)
                old = mine[(inst[mine] == number) & ~np.isin(mine, ids)]
                released += self.labels.assign(old, UNLABELED, 0)
                ids = ids[~((cls[ids] == chosen["class"]) & (inst[ids] == number) & ~pending[ids])]
                self.labels.assign(ids, chosen["class"], number, pending=not sure)
                if frame == key:
                    continue
                found = track.results[frame]
                stored = box_labels.moved(track.box_in(frame), np.linalg.inv(self._pose(frame)))
                stored.update(points=int(len(found["ids"])), score=round(found["score"], 3), left=found["left"])
                self.box_store[frame] = [box for box in self._boxes_of(frame) if box.get("instance") != number] + [stored]
                followed += 1
                unsure += not sure
        chosen["key"] = True
        if self.labels.undo_depth() > label_depth:
            self.labels.squash(label_depth)
            self._record_step("label")
            self.labels.touched = np.flatnonzero(self.cloud.alive)
            self._after_labels()
        self._group_since(depth)
        self.active_box = (key, self.box_store[key].index(chosen))
        self._fill_instances()
        self._boxes_changed()
        names = self.sequence.names
        self.status(self.tr("status_tracked_again", n=followed, first=names[segment[0]], last=names[segment[-1]],
                            u=unsure, r=released), 12000)

    def _leftovers(self, key, box):
        """Unlabeled points of a frame that hang on to a boxed object but were left outside it."""
        number = box.get("instance", 0)
        mine = self._key_ids(key)
        owned = mine[self.labels.inst[mine] == number] if number else EMPTY
        if not len(owned):
            return EMPTY
        gap = self.object_gap.value()
        world = self._box_world(key, box)
        free = self._above_ground(key) if key is not None else mine
        free = free[self.labels.cls[free] == UNLABELED]
        free = free[box_labels.inside(dict(world, size=[v + 4 * gap for v in world["size"]]), self.cloud.xyz[free])]
        grown = labels.with_feet(self.cloud.xyz, owned, free, gap)
        return grown[len(owned):]

    def _strays(self):
        """Per box on screen, as {(frame, index): ids}: its object's points more than half an object gap outside it.

        These are the points a box was not fitted to (slips of the brush, bits of a neighbour), or that a box
        edited by hand no longer holds.
        """
        pairs = [(key, index, box) for key in self._box_keys() for index, box in enumerate(self._boxes_of(key))
                 if box.get("instance")]
        if not pairs:
            return {}
        gap, _ = self._box_settings()
        ids = self.cloud.ids()
        ids = ids[np.isin(self.labels.inst[ids], np.unique([box["instance"] for _, _, box in pairs]))]
        frame = self.cloud.table["frame"][ids].astype(np.int64) if self.sequence is not None else np.zeros(len(ids), np.int64)
        code = (frame << 32) | self.labels.inst[ids].astype(np.int64)
        order = np.argsort(code, kind="stable")
        ids, code = ids[order], code[order]
        found = {}
        for key, index, box in pairs:
            target = (int(key or 0) << 32) | int(box["instance"])
            mine = ids[np.searchsorted(code, target):np.searchsorted(code, target + 1)]
            mine = mine[self.labels.cls[mine] == box["class"]]
            if not len(mine):
                continue
            world = self._box_world(key, box)
            out = mine[~box_labels.inside(dict(world, size=[v + gap for v in world["size"]]), self.cloud.xyz[mine])]
            if len(out):
                found[(key, index)] = out
        return found

    def _refresh_strays(self):
        """Count the stray points of the boxes on screen again; True when a count changed."""
        counts = {where: int(len(ids)) for where, ids in self._strays().items()}
        changed = counts != self._stray_counts
        self._stray_counts = counts
        return changed

    def select_strays(self):
        """Select the points labeled as boxed objects on screen that their boxes leave out."""
        found = self._strays()
        self._stray_counts = {where: int(len(ids)) for where, ids in found.items()}
        self._fill_boxes()
        self.select(np.unique(np.concatenate(list(found.values()))) if found else EMPTY, "replace", review=True)
        self.status(self.tr("status_filter", n=int(self.selected.sum())), 10000)

    def select_leftovers(self):
        """Select the points that belong with the boxed objects on screen but are still unlabeled."""
        pairs = [(key, box) for key in self._box_keys() for box in self._boxes_of(key)]
        parts = []
        with self.working(self.tr("boxes_select_left") + " …") as report:
            for done, (key, box) in enumerate(pairs):
                report(done, len(pairs))
                parts.append(self._leftovers(key, box))
        found = np.unique(np.concatenate(parts)) if parts else EMPTY
        self.select(found, "replace", review=True)
        self.status(self.tr("status_filter", n=int(self.selected.sum())), 10000)

    def take_leftovers(self):
        """Give those points to their objects and widen each box, in its own frame, to hold them."""
        depth, label_depth = len(self._order), self.labels.undo_depth()
        growth, taken = {}, 0
        pairs = [(key, box) for key in self._box_keys() for box in self._boxes_of(key)]
        with self.working(self.tr("boxes_take_left") + " …") as report:
            for done, (key, box) in enumerate(pairs):
                report(done, len(pairs))
                ids = self._leftovers(key, box)
                if not len(ids):
                    continue
                taken += self.labels.assign(ids, box["class"], box.get("instance", 0))
                world = self._box_world(key, box)
                local = tracking.to_local(tracking.pose_of(world), self.cloud.xyz[ids])
                half = np.asarray(world["size"]) / 2.0
                wider = (np.minimum(local.min(axis=0) + half, 0.0), np.maximum(local.max(axis=0) - half, 0.0))
                scope = (box.get("instance", 0), key)
                low, high = growth.get(scope, (np.zeros(3), np.zeros(3)))
                growth[scope] = (np.minimum(low, wider[0]), np.maximum(high, wider[1]))
        if not taken:
            return self.status(self.tr("status_no_change", what=self.tr("boxes_take_left")))
        self.labels.squash(label_depth)
        self._record_step("label")
        self.labels.touched = np.flatnonzero(self.cloud.alive)
        self._after_labels()
        self._remember_boxes()
        for key in self._box_keys():
            for box in self._boxes_of(key):
                scope = (box.get("instance", 0), key)
                if scope not in growth:
                    continue
                low, high = growth[scope]
                c, s = np.cos(box["yaw"]), np.sin(box["yaw"])
                middle = (low + high) / 2.0
                box["center"] = [float(box["center"][0] + c * middle[0] - s * middle[1]),
                                 float(box["center"][1] + s * middle[0] + c * middle[1]), float(box["center"][2] + middle[2])]
                box["size"] = [float(v) for v in np.asarray(box["size"]) + (high - low)]
                box["left"] = 0
        self._group_since(depth)
        self._boxes_changed()
        self.status(self.tr("status_labeled", what=self.tr("boxes_take_left"), n=taken), 10000)

    def label_box_from_selection(self):
        """One box around the selected points of each frame, with their main class and instance."""
        if not self.selected.any():
            return
        self._remember_boxes()
        ids = self.selection
        for key in self._box_keys():
            mine = ids if key is None else ids[self.cloud.table["frame"][ids] == key]
            if len(mine) < 3:
                continue
            cls = int(np.bincount(self.labels.cls[mine]).argmax())
            inst = int(np.bincount(self.labels.inst[mine]).argmax())
            self._boxes_of(key).append(dict(self._fit(self._local(key, mine), cls, inst)[0], key=True))
            self.active_box = (key, len(self.box_store[key]) - 1)
        self._boxes_changed()

    def _box_world(self, key, box):
        return box_labels.moved(box, self._pose(key))

    def _boxes_changed(self):
        self._draw_boxes()
        if self.label_panel:
            self._refresh_strays()
            self._fill_boxes()
        self.changed()

    def _draw_boxes(self):
        import vtk
        if self._box_actor is None:
            self._box_actor, self._box_focus = vtk.vtkActor(), vtk.vtkActor()
            for actor, width in ((self._box_actor, 2.0), (self._box_focus, 4.0)):
                mapper = vtk.vtkPolyDataMapper()
                actor.SetMapper(mapper)
                actor.GetProperty().SetLineWidth(width)
                actor.GetProperty().LightingOff()
                actor.PickableOff()
                self.viewport.renderer.AddActor(actor)
            self._box_focus.GetProperty().SetColor(1.0, 1.0, 1.0)
        shown = self.label_mode and (self.show_boxes.isChecked() if self.label_panel else self.panel_values["show_boxes"])
        lines, colours, focus = [], [], []
        for key in self._box_keys() if shown else []:
            for index, box in enumerate(self._boxes_of(key)):
                corner = box_labels.corners(self._box_world(key, box))
                edges = [(corner[a], corner[b]) for a, b in box_labels.EDGES]
                lines += edges
                colours += [self.classes.rgb(box["class"])] * len(edges)
                if self.active_box == (key, index):
                    focus += edges
        for actor, segments, rgb in ((self._box_actor, lines, colours), (self._box_focus, focus, None)):
            data = vtk.vtkPolyData()
            points, cells = vtk.vtkPoints(), vtk.vtkCellArray()
            for a, b in segments:
                first = points.InsertNextPoint(*a)
                points.InsertNextPoint(*b)
                cells.InsertNextCell(2)
                cells.InsertCellPoint(first)
                cells.InsertCellPoint(first + 1)
            data.SetPoints(points)
            data.SetLines(cells)
            if rgb:
                array = vtk.vtkUnsignedCharArray()
                array.SetNumberOfComponents(3)
                for colour in rgb:
                    array.InsertNextTuple3(*colour)
                data.GetCellData().SetScalars(array)
            actor.GetMapper().SetInputData(data)
            actor.SetVisibility(bool(segments))
        self.viewport.render()

    def _fill_boxes(self):
        tree = self.box_list
        tree.blockSignals(True)
        tree.clear()
        for key in self._box_keys():
            for index, box in enumerate(self._boxes_of(key)):
                frame = "" if key is None else f"{self.sequence.names[key]}  "
                item = QtWidgets.QTreeWidgetItem([f"{frame}{self.classes.name(box['class'])}", str(box.get("instance", 0)),
                                                  self._box_text(key, index)])
                item.setData(0, Qt.UserRole, (key, index))
                item.setIcon(0, swatch(self.classes.rgb(box["class"])))
                tree.addTopLevelItem(item)
                if self.active_box == (key, index):
                    tree.setCurrentItem(item)
        tree.blockSignals(False)
        self._show_box_fields()

    def _box_text(self, key, index):
        """What the box list says about a box: size, then score, points left beside it, strays, corrected."""
        box = self.box_store[key][index]
        text = "×".join(f"{v:.2f}" for v in box["size"])
        if "score" in box:
            unsure = box["score"] < self.track_accept.value() and not box.get("accepted")
            text += f"  ·  {box['score']:.2f}" + ("  ?" if unsure else "")
        if box.get("left"):
            text += "  ·  " + self.tr("boxes_left", n=box["left"])
        if self._stray_counts.get((key, index)):
            text += "  ·  " + self.tr("boxes_stray", n=self._stray_counts[(key, index)])
        if box.get("key") and self.sequence is not None:
            text += "  ·  " + self.tr("boxes_key")
        return text

    def _hint_track_again(self, before):
        """After a tracked box was corrected, say how to carry the correction to the other frames."""
        if self.sequence is not None and "score" in before and before.get("instance"):
            self.status(self.tr("status_corrected"), 12000)

    def _box_chosen(self, item, *_):
        self.active_box = None if item is None else tuple(item.data(0, Qt.UserRole))
        self._delete_target = "box" if self.active_box is not None else None
        if self.sequence is not None:
            self._anchor_changed()
        self._show_box_fields()
        self._draw_boxes()
        if self.active_box is not None:
            key, index = self.active_box
            world = self._box_world(key, self.box_store[key][index])
            self.focus(box_labels.corners(world))

    def _show_box_fields(self):
        box = self._active_box_world()
        for spin_box in self.box_fields:
            spin_box.setEnabled(box is not None)
        if box is None:
            return
        values = list(box["center"]) + list(box["size"]) + [np.degrees(box["yaw"])]
        for spin_box, value in zip(self.box_fields, values):
            spin_box.blockSignals(True)
            spin_box.setValue(value)
            spin_box.blockSignals(False)

    def _active_box_world(self):
        if self.active_box is None:
            return None
        key, index = self.active_box
        found = self._boxes_of(key)
        return self._box_world(key, found[index]) if index < len(found) else None

    def _box_field_changed(self, *_):
        world = self._active_box_world()
        if world is None:
            return
        values = [spin_box.value() for spin_box in self.box_fields]
        world.update(center=values[:3], size=[max(v, 1e-3) for v in values[3:6]], yaw=float(np.radians(values[6])))
        key, index = self.active_box
        self._remember_boxes()
        old = self.box_store[key][index]
        corrected = box_labels.moved(world, np.linalg.inv(self._pose(key)))
        for name in ("score", "left"):
            corrected.pop(name, None)
        corrected["key"] = True
        self.box_store[key][index] = corrected
        self._draw_boxes()
        item = self.box_list.currentItem()
        if item is not None:
            item.setText(2, self._box_text(key, index))
        self.changed()
        self._stats_timer.start()
        self._hint_track_again(old)

    def refit_box(self):
        """Fit the chosen box again: to its object's points as labeled now, or else to the points it holds."""
        world = self._active_box_world()
        if world is None:
            return
        key, index = self.active_box
        old = self.box_store[key][index]
        mine = self._key_ids(key)
        ids = mine[(self.labels.inst[mine] == old.get("instance", 0)) & (self.labels.cls[mine] == old["class"])] \
            if old.get("instance") else EMPTY
        if len(ids) < 3:
            ids = mine[box_labels.inside(world, self.cloud.xyz[mine])]
        if len(ids) < 3:
            return
        self._remember_boxes()
        self.box_store[key][index] = dict(self._fit(self._local(key, ids), old["class"], old.get("instance", 0))[0], key=True)
        self._boxes_changed()
        self._hint_track_again(old)

    def delete_box(self):
        if self.active_box is None:
            return
        key, index = self.active_box
        self._remember_boxes()
        del self.box_store[key][index]
        self.active_box = None
        self._boxes_changed()

    def select_in_box(self):
        world = self._active_box_world()
        if world is not None:
            ids = self._key_ids(self.active_box[0])
            self.select(ids[box_labels.inside(world, self.cloud.xyz[ids])], "replace", review=True)

    def export_boxes(self):
        """Write the boxes on screen as JSON, in the coordinates shown (fitting them to the instances if there are none)."""
        if not any(self._boxes_of(key) for key in self._box_keys()):
            self.fit_boxes()
        rows_world = [self._box_world(key, box) for key in self._box_keys() for box in self._boxes_of(key)]
        if not rows_world:
            return self.status(self.tr("boxes_none"), 8000)
        start = (os.path.splitext(self.path)[0] if self.path and self.sequence is None else
                 os.path.join(self.path or os.getcwd(), "frame")) + ".boxes.json"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self.window, self.tr("boxes_export"), start, "JSON (*.json)")
        if not path:
            return
        rows = [{"class": box["class"], "name": self.classes.name(box["class"]), "instance": box.get("instance", 0),
                 "center": [round(float(v), 6) for v in box["center"]], "size": [round(float(v), 6) for v in box["size"]],
                 "yaw": round(float(box["yaw"]), 6), "points": box.get("points", 0)} for box in rows_world]
        from .safeio import replacing
        with replacing(path) as part, open(part, "w", encoding="utf-8") as f:
            json.dump({"boxes": rows}, f, indent=1, ensure_ascii=False)
        self.status(self.tr("boxes_saved", n=len(rows), name=os.path.basename(path)), 8000)

    # ---- classes

    def _fill_rule_classes(self):
        chosen = self.rule_class.currentData() if self.rule_class.count() else self.panel_values["rule_class"]
        self.rule_class.blockSignals(True)
        self.rule_class.clear()
        for number in [UNLABELED] + self.classes.numbers():
            name = self.tr("class_unlabeled") if number == UNLABELED else self.classes.name(number)
            self.rule_class.addItem(swatch(self.classes.rgb(number)), f"{number}  {name}", number)
        self.rule_class.setCurrentIndex(max(self.rule_class.findData(chosen), 0))
        self.rule_class.setEnabled(self._rule() == "only")
        self.rule_class.blockSignals(False)

    def _fill_classes(self):
        self._fill_rule_classes()
        tree = self.class_list
        tree.blockSignals(True)
        tree.clear()
        for position, number in enumerate([UNLABELED] + self.classes.numbers()):
            key = f"Ctrl+{position}" if 0 <= position <= 9 else ""
            name = self.tr("class_unlabeled") if number == UNLABELED else self.classes.name(number)
            item = QtWidgets.QTreeWidgetItem([f"{number}  {name}", "", "", ""])
            item.setData(NAME, Qt.UserRole, number)
            item.setIcon(NAME, swatch(self.classes.rgb(number)))
            item.setToolTip(NAME, f"{name}   {key}".strip() + ("" if number == UNLABELED else
                                                               f"\n{self.tr('role_' + self.classes.role(number))}"))
            item.setCheckState(SHOWN, Qt.Unchecked if number in self.hidden_classes else Qt.Checked)
            item.setCheckState(LOCKED, Qt.Checked if number in self.locked_classes else Qt.Unchecked)
            tree.addTopLevelItem(item)
        tree.blockSignals(False)
        self._mark_active()
        self._stats_timer.start()

    def _mark_active(self):
        tree = self.class_list
        tree.blockSignals(True)
        for row in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(row)
            if item.data(NAME, Qt.UserRole) == self.active_class:
                tree.setCurrentItem(item)
        tree.blockSignals(False)
        self.active_label.setText(self.tr("class_active", name=self.classes.name(self.active_class)))
        self.active_label.setStyleSheet("font-weight: 700; border-left: 12px solid rgb({}, {}, {}); padding-left: 6px;"
                                        .format(*self.classes.rgb(self.active_class)))
        self.apply_button.setText(self.tr("label_apply", name=self.classes.name(self.active_class)))
        tint(self.apply_button, self.classes.rgb(self.active_class), "labels")
        if hasattr(self, "class_boxes"):
            self.class_boxes.setText(self.tr("boxes_class", name=self.classes.name(self.active_class)))

    def _class_toggled(self, item, column):
        number = item.data(NAME, Qt.UserRole)
        if column == SHOWN:
            (self.hidden_classes.discard if item.checkState(SHOWN) == Qt.Checked else self.hidden_classes.add)(number)
            hidden = self.selection
            self.selected[hidden[np.isin(self.labels.cls[hidden], list(self.hidden_classes))]] = False
            self.refresh()
        elif column == LOCKED:
            (self.locked_classes.add if item.checkState(LOCKED) == Qt.Checked else self.locked_classes.discard)(number)

    def toggle_all_classes(self, column):
        """Click on the eye or the lock in the header: switch it for every class at once."""
        everything = set([UNLABELED] + self.classes.numbers())
        if column == SHOWN:
            self.hidden_classes = set() if self.hidden_classes else everything
            if self.hidden_classes:
                self.selected[:] = False
            self._fill_classes()
            self.refresh()
        elif column == LOCKED:
            self.locked_classes = set() if self.locked_classes else everything
            self._fill_classes()

    def _class_chosen(self, item, _previous=None):
        if item is not None and item.data(NAME, Qt.UserRole) != UNLABELED:
            self.set_active(item.data(NAME, Qt.UserRole))

    def solo_class(self):
        """Show only the active class, or everything again when it already is the only one shown."""
        others = set([UNLABELED] + self.classes.numbers()) - {self.active_class}
        self.hidden_classes = set() if self.hidden_classes == others else others
        self.selected[:] = False
        self._fill_classes()
        self.refresh()

    def add_class(self):
        answer = ask_class(self.window, self.tr, self.classes)
        if answer:
            self._remember_classes()
            self.classes.set(*answer)
            self.active_class = answer[0]
            self._classes_changed()

    def edit_class(self, *_):
        if self.active_class in self.classes:
            answer = ask_class(self.window, self.tr, self.classes, self.active_class)
            if answer:
                self._remember_classes()
                self.classes.set(*answer)
                self._classes_changed()

    def remove_class(self):
        """Take a class off the list (Ctrl+Z brings it back); points that carry it keep their number."""
        if self.active_class not in self.classes:
            return
        self._remember_classes()
        self.status(self.tr("class_removed", name=self.classes.name(self.active_class)), 8000)
        self.classes.remove(self.active_class)
        self.active_class = (self.classes.numbers() or [UNLABELED])[0]
        self._classes_changed()

    def load_preset(self, index):
        name = self.preset_box.itemData(index)
        if name == "file":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self.window, self.tr("classes_load"),
                                                            os.path.dirname(self.path or ""), "YAML (*.yaml *.yml);;* (*)")
            replacement = None
            if path:
                try:
                    replacement = ClassList.load(path)
                except (OSError, ValueError) as error:
                    QtWidgets.QMessageBox.critical(self.window, self.tr("classes_load"), str(error))
        else:
            replacement = ClassList(name) if name else None
        if replacement is not None:
            self._remember_classes()
            self.classes.items = replacement.items
        self.preset_box.blockSignals(True)
        self.preset_box.setCurrentIndex(0)
        self.preset_box.blockSignals(False)
        if replacement is not None:
            self.classes.ensure(self.labels.cls)
            self.active_class = (self.classes.numbers() or [UNLABELED])[0]
            self._classes_changed()

    def save_classes(self):
        start = os.path.join(os.path.dirname(self.path or "") if self.sequence is None else self.path, "labels.yaml")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self.window, self.tr("classes_save"), start, "YAML (*.yaml)")
        if path:
            self.classes.save(path)

    # ---- frames

    def _frame_labels(self, index):
        if index not in self.frame_store:
            cls, inst = self.sequence.labels(index)
            self.frame_store[index] = (cls, inst, np.zeros(len(cls), bool))
        return self.frame_store[index]

    def _split_step(self, step):
        """A label-layer history step over the merged frames -> {frame: (local ids, cls, inst, pending)}."""
        ids, cls, inst, pending = step
        out = {}
        for index, start, end in zip(self.frame_ids, self.frame_starts[:-1], self.frame_starts[1:]):
            mine = (ids >= start) & (ids < end)
            if mine.any():
                out[index] = (ids[mine] - start, cls[mine], inst[mine], pending[mine])
        return out

    def _keep_history(self):
        """Before the frames on screen change: keep their undo history as per-frame steps, in the same order."""
        for stack, frame_steps, order in ((self.labels._undo, self._frame_undo, self._order),
                                          (self.labels._redo, self._frame_redo, self._redo_order)):
            kinds = [kind for entry in order for kind in (entry if isinstance(entry, tuple) else (entry,))]
            old, new = iter(frame_steps[-kinds.count("frames"):] if kinds.count("frames") else []), \
                iter([self._split_step(step) for step in stack][-kinds.count("label"):] if kinds.count("label") else [])
            merged = []
            for kind in kinds:
                if kind in ("frames", "label"):
                    step = next(old if kind == "frames" else new, None)
                    if step is not None:
                        merged.append(step)
            frame_steps[:] = merged
            order[:] = [tuple("frames" if kind == "label" else kind for kind in entry) if isinstance(entry, tuple)
                        else "frames" if entry == "label" else entry for entry in order]
        self.labels._undo, self.labels._redo = [], []

    def _frame_values(self, index, local):
        cls, inst, pending = self._frame_labels(index)
        return cls[local].copy(), inst[local].copy(), pending[local].copy()

    def _write_frame(self, index, local, cls, inst, pending):
        """Write labels of one frame, on screen or not."""
        stored = [part.copy() for part in self._frame_labels(index)]
        stored[0][local], stored[1][local], stored[2][local] = cls, inst, pending
        self.frame_store[index] = tuple(stored)
        self.frame_dirty.add(index)
        if index in self.frame_ids:
            start = int(self.frame_starts[self.frame_ids.index(index)])
            ids = local + start
            self.labels.cls[ids], self.labels.inst[ids], self.labels.pending[ids] = cls, inst, pending
            return ids
        return EMPTY

    def _swap_frames(self, source, target):
        if not source:
            return False
        step = source.pop()
        back, shown = {}, []
        for index, (local, cls, inst, pending) in step.items():
            back[index] = (local,) + self._frame_values(index, local)
            shown.append(self._write_frame(index, local, cls, inst, pending))
        target.append(back)
        self.labels.touched = np.concatenate(shown) if shown else EMPTY
        if self.label_panel:
            self._fill_frames()
        return True

    def _frames_step(self, changes):
        """Record writes to frames as one undo step: changes is {frame: (local ids, cls, inst, pending)} of old values."""
        if changes:
            self._frame_undo.append(changes)
            self._frame_redo.clear()
            self._record_step("frames")

    def _store_frames(self):
        """Hand the labels of the frames on screen back to their per-frame stores."""
        if self.sequence is None or not self.frame_ids or len(self.labels) != self.frame_starts[-1]:
            return
        self._keep_history()
        saved_cls, saved_inst = self.labels._saved
        for index, start, end in zip(self.frame_ids, self.frame_starts[:-1], self.frame_starts[1:]):
            part = slice(int(start), int(end))
            if not (np.array_equal(self.labels.cls[part], saved_cls[part])
                    and np.array_equal(self.labels.inst[part], saved_inst[part])):
                self.frame_dirty.add(index)
            self.frame_store[index] = (self.labels.cls[part].copy(), self.labels.inst[part].copy(),
                                       self.labels.pending[part].copy())
        self.labels.mark_saved()

    def show_frames(self, indices, progress=None, store=True, fresh=False):
        """Put the chosen frames on screen as one cloud; their labels stay per frame."""
        indices = sorted(set(int(i) for i in indices))
        if not indices:
            return
        estimate = sum(self.sequence.estimate(index) for index in indices)
        if estimate > FRAME_POINT_LIMIT and not fresh:
            answer = QtWidgets.QMessageBox.question(self.window, self.tr("frames"),
                                                    self.tr("frames_many", n=len(indices), p=estimate))
            if answer != QtWidgets.QMessageBox.Yes:
                return
        if store:
            self._store_frames()
        before = None if fresh else self._anchor_pose()
        if progress is None:
            with self.working(self.tr("frames_loading", n=len(indices))) as report:
                xyz, table, starts = self.sequence.merge(indices, report)
        else:
            xyz, table, starts = self.sequence.merge(indices, progress)
        cls, inst = np.zeros(len(xyz), np.uint16), np.zeros(len(xyz), np.uint32)
        pending = np.zeros(len(xyz), bool)
        for index, start, end in zip(indices, starts[:-1], starts[1:]):
            cls[start:end], inst[start:end], pending[start:end] = self._frame_labels(index)
        self.classes.ensure(cls)
        self.frame_ids, self.frame_starts = indices, starts
        self._install(xyz, table, cls, inst, progress, fresh)
        self.labels.pending[:] = pending
        if pending.any():
            self.refresh()
        if self.label_panel:
            self._fill_frames()
            self._fill_instances()
            self._refresh_strays()
            self._fill_boxes()
        after = self._anchor_pose()
        if before is not None and after is not None:
            self.viewport.carry_camera(after @ np.linalg.inv(before))
        self._anchor_changed()
        self._draw_boxes()
        self._sync_timeline()
        if not fresh:
            self.status(self.tr("status_frames", n=len(indices), p=len(xyz)), 8000)

    def _fill_frames(self):
        self.frame_list.blockSignals(True)
        self.frame_list.clear()
        for index, name in enumerate(self.sequence.names):
            item = QtWidgets.QListWidgetItem(name + ("  *" if index in self.frame_dirty else ""))
            self.frame_list.addItem(item)
            item.setSelected(index in self.frame_ids)
        if self.frame_ids:
            self.frame_list.scrollToItem(self.frame_list.item(self.frame_ids[0]))
        self.frame_list.blockSignals(False)
        chosen = self.paint_frame.currentData()
        self.paint_frame.blockSignals(True)
        self.paint_frame.clear()
        self.paint_frame.addItem(self.tr("frames_paint_all"), -1)
        for index in self.frame_ids:
            self.paint_frame.addItem(self.sequence.names[index], index)
        self.paint_frame.setCurrentIndex(max(self.paint_frame.findData(chosen), 0))
        self.paint_frame.blockSignals(False)

    def _anchor_pose(self):
        """4x4 pose of what the view is fixed to while frames change, or None for the world (the view stays put).

        'lidar' is the sensor of the first frame on screen; 'object' is the box chosen in the box list, found
        again in the new frames by its object number.
        """
        if self.sequence is None or not self.frame_ids:
            return None
        mode = self.timeline.anchor.currentData()
        if mode == "lidar":
            return self._pose(self.frame_ids[0]) if self.sequence.poses is not None else None
        if mode == "object" and self._anchor_object:
            for key in self.frame_ids:
                for box in self._boxes_of(key):
                    if box.get("instance") == self._anchor_object:
                        return tracking.pose_of(self._box_world(key, box))
        return None

    def _anchor_changed(self):
        """Show the axes at what the view is fixed to (the world origin when it is fixed to the world)."""
        if self.timeline.anchor.currentData() == "object" and self.active_box is not None:
            key, index = self.active_box
            found = self._boxes_of(key)
            if index < len(found) and found[index].get("instance"):
                self._anchor_object = found[index]["instance"]
        pose = self._anchor_pose()
        self.viewport.place_axes(np.eye(4) if pose is None else pose)
        self.viewport.render()

    def _sync_timeline(self):
        if self.sequence is None:
            self.timeline.hide()
            return
        if not hasattr(self, "_labeled_frames"):
            self._labeled_frames = {index for index in range(len(self.sequence))
                                     if os.path.isfile(self.sequence.label_path(index))}
        labeled = self._labeled_frames | {index for index, item in self.frame_store.items() if item[0].any()}
        self.timeline.slider.set_marks(labeled, self.frame_dirty)
        self.timeline.show_range(self.sequence.names, self.frame_ids[0], self.frame_ids[-1])
        self.timeline.show()

    def _show_pose_source(self):
        if self.sequence is not None and hasattr(self, "pose_label"):
            source = self.sequence.pose_source
            self.pose_label.setText(self.tr("frames_poses", source=source or self.tr("frames_poses_none")))

    def choose_poses(self):
        """Take the frame poses from a file the user picks (any supported layout)."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self.window, self.tr("frames_choose_poses"), self.path,
                                                        "Poses (*.txt *.tum *.csv);;* (*)")
        if not path:
            return
        try:
            self.sequence.use_poses(path)
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.warning(self.window, self.tr("frames_choose_poses"), str(error))
            return
        self.show_frames(self.frame_ids)
        self._show_pose_source()

    def no_poses(self):
        self.sequence.drop_poses()
        self.show_frames(self.frame_ids)
        self._show_pose_source()

    def show_selected_frames(self):
        self.show_frames([self.frame_list.row(item) for item in self.frame_list.selectedItems()])

    def step_frame(self, step, whole=False):
        """Slide the frames on screen forward or back, keeping as many as now.

        By one frame, or with `whole` by the width of the range itself, so the next press shows the frames
        that follow the ones just seen (the last range stops at the last frame).
        """
        if self.sequence is None or not self.frame_ids:
            return
        span = self.frame_ids[-1] - self.frame_ids[0]
        step = step * (span + 1) if whole else step
        first = int(np.clip(self.frame_ids[0] + step, 0, len(self.sequence) - 1 - span))
        if first != self.frame_ids[0]:
            self.show_frames([first + (index - self.frame_ids[0]) for index in self.frame_ids])

    def propagate_frames(self):
        """Carry labels of static classes from the frames on screen to every other frame, as suggestions."""
        if self.sequence is None or self.sequence.poses is None:
            return self.status(self.tr("frames_need_poses"), 8000)
        from .frames import apply
        static = [number for number in self.classes.numbers() if self.classes.role(number) != labels.IGNORE]
        alive = self.cloud.ids()
        source = labels.Transfer(self.cloud.xyz[alive], np.where(self.labels.pending[alive], 0, self.labels.cls[alive]),
                                 static)
        targets = [index for index in range(len(self.sequence)) if index not in self.frame_ids]
        progress = QtWidgets.QProgressDialog(self.tr("frames_propagate"), self.tr("cancel"), 0, len(targets), self.window)
        progress.setWindowModality(Qt.WindowModal)
        filled, changes = 0, {}
        for done, index in enumerate(targets):
            progress.setValue(done)
            if progress.wasCanceled():
                break
            xyz, _ = self.sequence.load(index)
            cls, inst, pending = self._frame_labels(index)
            guess = source.to(apply(self.sequence.poses[index], xyz), self.frame_radius.value())
            take = (cls == UNLABELED) & (guess != UNLABELED)
            if take.any():
                local = np.flatnonzero(take)
                changes[index] = (local,) + self._frame_values(index, local)
                cls, pending = cls.copy(), pending.copy()
                cls[take], pending[take] = guess[take], True
                self.frame_store[index] = (cls, inst, pending)
                self.frame_dirty.add(index)
                filled += int(take.sum())
        progress.setValue(len(targets))
        self._frames_step(changes)
        self._fill_frames()
        self._sync_timeline()
        self.changed()
        self.status(self.tr("status_propagated", n=filled, f=len(targets)), 10000)

    def select_conflicts(self):
        """Select points whose label differs from a nearby point of another frame."""
        if self.sequence is None:
            return
        frames, radius = self.cloud.table["frame"], self.frame_radius.value()
        self._busy_select("frames_conflicts", lambda xyz, cls, ids: labels.conflicts(xyz, cls, frames[ids], radius))

    # ---- panel

    def build_label_sections(self, layout):
        t, values, W = self.tr, self.panel_values, QtWidgets
        if self.sequence is not None:
            group = Section(t("frames"), "frames")
            form = W.QFormLayout(group)
            self.frame_list = W.QListWidget()
            self.frame_list.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
            self.frame_list.setMaximumHeight(150)
            self.frame_list.setToolTip(t("frames_tip"))
            self.frame_list.itemDoubleClicked.connect(lambda item: self.show_frames([self.frame_list.row(item)]))
            form.addRow(self.frame_list)
            row = W.QHBoxLayout()
            row.addWidget(button("◀", lambda: self.step_frame(-1), t("frames_previous")))
            row.addWidget(select_button(t("frames_show"), self.show_selected_frames, t("frames_tip"), icon="frames_show"))
            row.addWidget(button("▶", lambda: self.step_frame(1), t("frames_next")))
            form.addRow(row)
            self.paint_frame = W.QComboBox()
            self.paint_frame.setToolTip(t("frames_paint_tip"))
            form.addRow(t("frames_paint"), self.paint_frame)
            self.pose_label = W.QLabel()
            self.pose_label.setWordWrap(True)
            form.addRow(self.pose_label)
            row = W.QHBoxLayout()
            row.addWidget(button(t("frames_choose_poses"), self.choose_poses, t("frames_poses_tip"), icon="poses"))
            row.addWidget(button(t("frames_no_poses"), self.no_poses, t("frames_no_poses_tip"), icon="poses_off"))
            form.addRow(row)
            self.frame_radius = spin(0.001, RANGE_LIMIT, values["frame_radius"], 0.01)
            form.addRow(t("frames_radius"), self.frame_radius)
            form.addRow(add_button(t("frames_propagate"), self.propagate_frames, t("frames_propagate_tip"), icon="propagate"))
            form.addRow(select_button(t("frames_conflicts"), self.select_conflicts, t("frames_conflicts_tip"), icon="conflict"))
            group.add_to(layout)
            self._fill_frames()
            self._show_pose_source()

        group = Section(t("labels"), "labels")
        form = W.QFormLayout(group)
        self.active_label = W.QLabel()
        form.addRow(self.active_label)
        self.class_list = W.QTreeWidget()
        self.class_list.setRootIsDecorated(False)
        self.class_list.setHeaderLabels([t("class_name"), t("class_points"), "👁", "🔒"])
        self.class_list.header().setSectionResizeMode(NAME, W.QHeaderView.Stretch)
        for column in (POINTS, SHOWN, LOCKED):
            self.class_list.header().setSectionResizeMode(column, W.QHeaderView.ResizeToContents)
        self.class_list.header().setStretchLastSection(False)
        self.class_list.setMinimumHeight(190)
        self.class_list.setToolTip(t("class_list_tip"))
        self.class_list.headerItem().setToolTip(SHOWN, t("class_all_tip"))
        self.class_list.headerItem().setToolTip(LOCKED, t("class_all_tip"))
        self.class_list.header().setSectionsClickable(True)
        self.class_list.header().sectionClicked.connect(self.toggle_all_classes)
        self.class_list.itemChanged.connect(self._class_toggled)
        self.class_list.currentItemChanged.connect(self._class_chosen)
        self.class_list.itemDoubleClicked.connect(self.edit_class)
        form.addRow(self.class_list)
        row = W.QHBoxLayout()
        row.addWidget(add_button(t("class_add"), self.add_class))
        row.addWidget(button(t("class_edit"), self.edit_class, icon="class_edit"))
        row.addWidget(danger_button(t("class_remove"), self.remove_class, t("class_remove_tip"), icon="class_remove"))
        form.addRow(row)
        self.preset_box = W.QComboBox()
        self.preset_box.addItem(t("classes_preset"), "")
        for name in labels.PRESETS:
            self.preset_box.addItem(t(f"preset_{name}"), name)
        self.preset_box.addItem(t("classes_load"), "file")
        self.preset_box.activated.connect(self.load_preset)
        row = W.QHBoxLayout()
        row.addWidget(self.preset_box, 1)
        row.addWidget(button(t("classes_save"), self.save_classes, icon="list_save"))
        form.addRow(row)
        self.rule_box = W.QComboBox()
        for rule in ("unlabeled", "all", "only"):
            self.rule_box.addItem(t(f"rule_{rule}"), rule)
        self.rule_box.setCurrentIndex(max(self.rule_box.findData(values["rule"]), 0))
        self.rule_box.setToolTip(t("rule_tip"))
        self.rule_class = W.QComboBox()
        self.rule_class.setToolTip(t("rule_tip"))
        self.rule_box.currentIndexChanged.connect(lambda *_: (self.rule_class.setEnabled(self._rule() == "only"),
                                                              self._sync_label_bar()))
        row = W.QHBoxLayout()
        row.addWidget(self.rule_box, 1)
        row.addWidget(self.rule_class, 1)
        form.addRow(t("rule"), row)
        self.apply_button = button(t("label_assign"), lambda: self.assign_selection(), t("label_assign_tip"))
        self.apply_button.setMinimumHeight(32)
        form.addRow(self.apply_button)
        row = W.QHBoxLayout()
        row.addWidget(button(t("label_clear"), lambda: self.assign_selection(UNLABELED), icon="tag_clear"))
        row.addWidget(button(t("label_solo"), self.solo_class, t("label_solo_tip"), icon="solo"))
        form.addRow(row)
        form.addRow(select_button(t("label_select_class"), self.select_class, icon="select_class"))
        form.addRow(button(t("labels_load"), self.load_labels, t("labels_load_tip"), icon="labels_open"))
        form.addRow(button(t("labels_only"), self.save_labels_only, t("labels_only_tip"), icon="labels_save"))
        form.addRow(button(t("label_export"), lambda: self.export_standard(), t("label_export_tip"), icon="export"))
        group.add_to(layout)

        group = Section(t("smart"), "smart")
        group.setToolTip(t("smart_tip"))
        form = W.QFormLayout(group)
        self.smart_box = W.QComboBox()
        for mode in SMART_MODES:
            self.smart_box.addItem(t(f"smart_{mode}"), mode)
        self.smart_box.setCurrentIndex(SMART_MODES.index(values["smart"]))
        form.addRow(t("smart_mode"), self.smart_box)
        self.reach = spin(0.01, RANGE_LIMIT, values["reach"], 0.5)
        self.gap = spin(0.001, RANGE_LIMIT, values["gap"], 0.01)
        self.flatness = spin(0.001, RANGE_LIMIT, values["flatness"], 0.005)
        self.bend = spin(1.0, 90.0, values["bend"], 1.0, decimals=1)
        form.addRow(t("smart_reach"), self.reach)
        form.addRow(t("smart_gap"), self.gap)
        form.addRow(t("smart_flatness"), self.flatness)
        form.addRow(t("smart_bend"), self.bend)
        self.stop_bends = W.QCheckBox(t("smart_stop_bends"))
        self.stop_bends.setChecked(values["stop_bends"])
        self.stop_bends.setToolTip(t("smart_stop_bends_tip"))
        form.addRow(self.stop_bends)
        self.clearance = spin(0.0, 10.0, values["clearance"], 0.05)
        self.clearance.setToolTip(t("smart_clearance_tip"))
        form.addRow(t("smart_clearance"), self.clearance)
        self.at_once = W.QCheckBox(t("smart_at_once"))
        self.at_once.setChecked(values["at_once"])
        form.addRow(self.at_once)
        group.add_to(layout)

        group = Section(t("review"), "review")
        form = W.QFormLayout(group)
        self.progress_bar = W.QProgressBar()
        form.addRow(self.progress_bar)
        form.addRow(select_button(t("review_next"), self.next_unlabeled, t("review_next_tip"), icon="next_area"))
        form.addRow(select_button(t("review_disagree"), self.select_disagreeing, t("review_disagree_tip"), icon="doubt"))
        self.island = int_spin(1, 1_000_000, values["island"])
        form.addRow(t("review_island_size"), self.island)
        form.addRow(select_button(t("review_islands"), self.select_label_islands, t("review_islands_tip"), icon="label_islands"))
        self.fill_radius = spin(0.001, RANGE_LIMIT, values["fill_radius"], 0.01)
        form.addRow(t("review_fill_radius"), self.fill_radius)
        form.addRow(add_button(t("review_fill"), self.fill_gaps, t("review_fill_tip"), icon="fill_gaps"))
        row = W.QHBoxLayout()
        row.addWidget(add_button(t("review_confirm"), self.confirm_pending, icon="accept_all"))
        row.addWidget(danger_button(t("review_reject"), self.reject_pending, icon="reject_all"))
        form.addRow(row)
        group.add_to(layout)

        group = Section(t("instances"), "instances")
        form = W.QFormLayout(group)
        self.own_instance = W.QCheckBox(t("instance_own"))
        self.own_instance.setChecked(values["own_instance"])
        self.own_instance.setToolTip(t("instance_own_tip"))
        form.addRow(self.own_instance)
        self.object_gap = spin(0.001, RANGE_LIMIT, values["object_gap"], 0.05)
        self.object_gap.setToolTip(t("instance_gap_tip"))
        form.addRow(t("instance_gap"), self.object_gap)
        self.min_points = int_spin(1, 1_000_000, values["min_points"])
        self.min_points.setToolTip(t("instance_min_tip"))
        form.addRow(t("instance_min"), self.min_points)
        form.addRow(button(t("instance_split"), self.split_instances, t("instance_split_tip"), icon="split"))
        form.addRow(button(t("instance_merge"), self.merge_instance, icon="merge"))
        form.addRow(button(t("instance_clear"), self.clear_instances, t("instance_clear_tip"), icon="unsplit"))
        self.instance_list = W.QTreeWidget()
        self.instance_list.setRootIsDecorated(False)
        self.instance_list.setHeaderLabels([t("instance_number"), t("class_name"), t("class_points")])
        self.instance_list.setMaximumHeight(150)
        self.instance_list.setToolTip(t("instance_list_tip"))
        self.instance_list.itemClicked.connect(self._instance_chosen)
        form.addRow(self.instance_list)
        group.add_to(layout)

        group = Section(t("boxes"), "bbox")
        group.setToolTip(t("boxes_tip"))
        form = W.QFormLayout(group)
        self.show_boxes = W.QCheckBox(t("boxes_show"))
        self.show_boxes.setChecked(values["show_boxes"])
        self.show_boxes.toggled.connect(lambda *_: self._draw_boxes())
        form.addRow(self.show_boxes)
        self.robust_boxes = W.QCheckBox(t("boxes_robust"))
        self.robust_boxes.setChecked(values["robust_boxes"])
        self.robust_boxes.setToolTip(t("boxes_robust_tip"))
        form.addRow(self.robust_boxes)
        self.class_boxes = add_button(t("boxes_class", name=""), self.boxes_for_class, t("boxes_class_tip"), icon="auto_box")
        form.addRow(self.class_boxes)
        form.addRow(button(t("boxes_from_selection"), self.label_box_from_selection, icon="box_around_selection"))
        form.addRow(button(t("boxes_fit"), self.fit_boxes, t("boxes_fit_tip"), icon="boxes_all"))
        self.box_list = W.QTreeWidget()
        self.box_list.setRootIsDecorated(False)
        self.box_list.setHeaderLabels([t("class_name"), t("instance_number"), t("boxes_size_short")])
        self.box_list.setMaximumHeight(150)
        self.box_list.currentItemChanged.connect(self._box_chosen)
        form.addRow(self.box_list)
        grid = W.QGridLayout()
        self.box_fields = [spin(-RANGE_LIMIT * 100, RANGE_LIMIT * 100, 0.0, 0.05) for _ in range(6)] + \
            [spin(-180.0, 180.0, 0.0, 1.0, decimals=1)]
        for row_index, (label, first) in enumerate(((t("boxes_centre"), 0), (t("boxes_size"), 3))):
            grid.addWidget(W.QLabel(label), 2 * row_index, 0, 1, 3)
            for column in range(3):
                self.box_fields[first + column].setMinimumWidth(70)
                grid.addWidget(self.box_fields[first + column], 2 * row_index + 1, column)
        grid.addWidget(W.QLabel(t("boxes_yaw")), 4, 0)
        grid.addWidget(self.box_fields[6], 4, 1)
        for spin_box in self.box_fields:
            spin_box.valueChanged.connect(self._box_field_changed)
        form.addRow(grid)
        row = W.QHBoxLayout()
        row.addWidget(button(t("boxes_refit"), self.refit_box, t("boxes_refit_tip"), icon="refit"))
        row.addWidget(danger_button(t("boxes_delete"), self.delete_box, icon="box_delete"))
        form.addRow(row)
        form.addRow(select_button(t("boxes_select_points"), self.select_in_box, icon="box_select"))
        form.addRow(button(t("boxes_export"), self.export_boxes, icon="export_boxes"))
        self.track_reach = spin(0.1, 50.0, values["track_reach"], 0.1)
        self.track_reach.setToolTip(t("track_reach_tip"))
        self.track_accept = spin(0.0, 1.0, values["track_accept"], 0.05, decimals=2)
        self.track_accept.setToolTip(t("track_accept_tip"))
        if self.sequence is not None:
            form.addRow(t("track_reach"), self.track_reach)
            form.addRow(t("track_accept"), self.track_accept)
            form.addRow(add_button(t("track"), lambda: self.track_boxes(1), t("track_tip"), icon="track_forward"))
            form.addRow(add_button(t("track_back"), self.track_back, t("track_tip"), icon="track_backward"))
            form.addRow(button(t("track_again"), self.track_again, t("track_again_tip"), icon="retrack"))
        form.addRow(select_button(t("boxes_select_stray"), self.select_strays, t("boxes_stray_tip"), icon="strays"))
        form.addRow(select_button(t("boxes_select_left"), self.select_leftovers, t("boxes_left_tip"), icon="leftovers"))
        form.addRow(add_button(t("boxes_take_left"), self.take_leftovers, t("boxes_left_tip"), icon="absorb"))
        group.add_to(layout)
        self._fill_classes()
        self._fill_instances()
        self._refresh_strays()
        self._fill_boxes()
        self._draw_boxes()

    def label_panel_values(self):
        return {"track_reach": self.track_reach.value(), "track_accept": self.track_accept.value(),
                "object_gap": self.object_gap.value(), "min_points": self.min_points.value(), "show_boxes": self.show_boxes.isChecked(), "robust_boxes": self.robust_boxes.isChecked(),
                "clearance": self.clearance.value(), "stop_bends": self.stop_bends.isChecked(), "rule": self.rule_box.currentData(), "rule_class": self.rule_class.currentData(), "smart": self.smart_box.currentData(), "reach": self.reach.value(),
                "flatness": self.flatness.value(), "bend": self.bend.value(), "gap": self.gap.value(),
                "at_once": self.at_once.isChecked(), "own_instance": self.own_instance.isChecked(),
                "fill_radius": self.fill_radius.value(), "island": self.island.value(),
                "frame_radius": self.frame_radius.value() if self.sequence is not None else self.panel_values["frame_radius"],
                "paint_frame": -1}

    def label_actions(self):
        t = self.tr
        keys = [(f"{t('label_assign')}: {position}", f"Ctrl+{position}", lambda p=position: self.class_key(p))
                for position in range(1, 10)]
        extra = [(t("label_assign"), ["Return", "Enter"], lambda: typing() or self.assign_selection()),
                 (t("label_protect"), "P", self.toggle_protect),
                 (t("label_clear"), "Ctrl+0", lambda: self.assign_selection(UNLABELED)),
                 (t("review_next"), "N", self.next_unlabeled),
                 (t("labels_only"), "Ctrl+Alt+S", self.save_labels_only)]
        if self.sequence is not None:
            extra += [(t("frames_previous"), ",", lambda: self.step_frame(-1)), (t("frames_next"), ".", lambda: self.step_frame(1))]
        return keys + extra


class VoxelLabeling(ClassHistory):
    """Mixed into the voxel editor: voxel classes voted from points, relabeling, and their way back to points."""

    @property
    def label_panel(self):
        return self.panel_alive and self.label_mode

    def switch_label_mode(self, on):
        if on == self.label_mode:
            return
        self.label_mode = on
        if on:
            self._edit_tool = self.tool
            self.tool = "label" if self.tool in ("delete", "add") else self.tool if self.tool in dict(self.tools) else "view"
        else:
            self.tool = self._edit_tool if self._edit_tool in dict(self.tools) else "view"
        self.hover_actor.VisibilityOff()
        self._sync_label_bar()

    def _sync_label_bar(self):
        self.label_bar.setVisible(self.label_mode)
        if self.label_mode:
            self.label_bar.update_state(self.classes.name(self.active_class), self.classes.rgb(self.active_class),
                                        self.protecting())
        self.overlay.place()

    def _protect_from_bar(self, on):
        if self.label_panel:
            self.protect.setChecked(on)
        else:
            self.panel_values["protect"] = on
        self._sync_label_bar()
        self.status(self.tr("label_protect") + ("  ON" if on else "  OFF"), 4000)

    def _init_voxel_labels(self):
        self.label_mode = False
        self._edit_tool = "view"
        self.vlabels = labels.VoxelLabels()
        self._class_undo, self._class_redo = [], []
        self.classes = ClassList("indoor")
        self.active_class = self.classes.numbers()[0]
        self._order, self._redo_order = [], []
        self._palette = self.classes.palette(1)
        self.panel_values.update({"by_class": True, "purity": 0.6, "protect": True, "smart": "object", "reach": 5.0,
                                  "flatness": None, "bend": 30.0, "clearance": 0.15, "stop_bends": True,
                                  "at_once": False})

    def _voxel_labels_from(self, payload, source, path):
        """Labels a new voxel document starts with: voted from a labeled cloud, or read from beside the file."""
        self.vlabels = labels.VoxelLabels()
        if source is not None and source.get("voxel") is not None:
            self.vlabels = labels.VoxelLabels(*source["voxel"])
            self.classes = source.get("classes") or self.classes
        elif getattr(payload, "voxel_labels", None) is not None:
            self.vlabels = payload.voxel_labels
            self.classes = getattr(payload, "classes", None) or self.classes
        self.classes.ensure(self.vlabels.base_values)
        self._order, self._redo_order = [], []
        if self.active_class not in self.classes and len(self.classes):
            self.active_class = self.classes.numbers()[0]
        self._palette = self.classes.palette(max([1] + self.classes.numbers() + [int(self.vlabels.base_values.max(initial=0))]))
        if self.label_panel:
            self._fill_voxel_classes()

    @staticmethod
    def read_voxel_label_files(document, path):
        sidecar = formats.label_sidecar(path)
        if os.path.isfile(sidecar):
            found = formats.read_voxel_labels(sidecar)
            if found is not None:
                document.voxel_labels = labels.VoxelLabels(*found)
        for candidate in (path + ".labels.yaml", os.path.join(os.path.dirname(path), "labels.yaml")):
            if os.path.isfile(candidate):
                document.classes = ClassList.load(candidate)
                break

    def by_class_on(self):
        return self.label_mode and (self.by_class.isChecked() if self.label_panel else self.panel_values["by_class"])

    def protecting(self):
        return self.label_mode and (self.protect.isChecked() if self.label_panel else self.panel_values["protect"])

    def toggle_protect(self):
        self._protect_from_bar(not self.protecting())

    def voxel_colours(self, keys):
        cls = self.vlabels.get(keys)
        if int(cls.max(initial=0)) >= len(self._palette):
            self._palette = self.classes.palette(int(cls.max()))
        return self._palette[cls]

    def voxel_label_dirty(self):
        return self.vlabels.dirty

    def _write_voxel_labels(self, path, fmt):
        """Keep the voxel classes beside an octree or archive (point formats carry them inside)."""
        if not self.vlabels.any:
            return
        keys = self.map.occupied
        cls = self.vlabels.get(keys)
        keep = cls != UNLABELED
        formats.write_voxel_labels(formats.label_sidecar(path), keys[keep], cls[keep])
        self.classes.save(path + ".labels.yaml")

    def _voxel_point_table(self, centres):
        cls = self.vlabels.get(self.map.occupied)
        return formats.with_labels(centres, None, cls, None)

    # ---- editing

    def _record(self, *kinds):
        self._order.append(kinds)
        self._redo_order.clear()

    def _record_step(self, kind):
        self._record(kind)

    def _after_classes(self):
        self._voxel_classes_changed()

    def _after_voxel_labels(self):
        from .voxels import KeySet
        if self.by_class_on():
            self.refresh(set(KeySet.split(self.vlabels.touched)[0].tolist()))
        self._voxel_stats()

    def label_voxels(self, keys, number, what="label_assign"):
        keys = np.unique(np.asarray(keys, np.int64))
        kept = 0
        if self.protecting() and number != UNLABELED:
            free = self.vlabels.get(keys) == UNLABELED
            kept, keys = int((~free).sum()), keys[free]
        changed = self.vlabels.set(keys, number)
        if not changed:
            return self.status(self.tr("status_no_change", what=self.tr(what))
                               + (f"  ·  {self.tr('status_protected', n=kept)}" if kept else ""))
        self._record("label")
        self._after_voxel_labels()
        self.status(self.tr("status_labeled", what=self.tr(what), n=changed)
                    + (f"  ·  {self.tr('status_protected', n=kept)}" if kept else ""))

    def assign_selection(self, number=None):
        number = self.active_class if number is None else number
        if number != UNLABELED and number in self.classes:
            self.set_active(number)
        if len(self.selected):
            keys = self.selection
            self.clear_selection()
            self.label_voxels(keys, number)

    def class_key(self, position):
        numbers = self.classes.numbers()
        if position <= len(numbers):
            self.assign_selection(numbers[position - 1])

    def set_active(self, number):
        self.active_class = number
        if self.label_panel:
            self._mark_voxel_active()
        self._sync_label_bar()

    # ---- assisted picking

    def smart_keys(self, cell, mode=None):
        """Keys of the voxels the assisted pick finds from a clicked cell, searched within `reach` of it."""
        size = self.map.resolution
        centre = (np.asarray(cell, np.float64) + 0.5) * size
        reach = self.reach.value()
        filters = self._filters()
        hit = np.flatnonzero(np.all((self._chunk_high >= centre - reach) & (self._chunk_low <= centre + reach), axis=1))
        parts = [self._shown_cells(int(self._chunk_ids[index]), filters) for index in hit]
        cells = np.concatenate(parts) if parts else np.zeros((0, 3), np.int64)
        points = (cells + 0.5) * size
        inside = np.einsum("ij,ij->i", points - centre, points - centre) <= reach * reach
        cells, points = cells[inside], points[inside]
        if not len(cells):
            return EMPTY
        usable = self.vlabels.get(pack(cells)) == UNLABELED if self.protecting() else np.ones(len(cells), bool)
        if len(cells) > WORK_LIMIT:
            self.status(self.tr("smart_too_many", n=len(cells)), 8000)
            return EMPTY
        seed = int(np.argmin(np.einsum("ij,ij->i", points - centre, points - centre)))
        if not usable[seed]:
            self.status(self.tr("status_protected", n=1), 6000)
            return EMPTY
        mode = mode or self.smart_box.currentData()
        flatness, bend, clearance = self.flatness.value(), self.bend.value(), self.clearance.value()
        stop_bends = self.stop_bends.isChecked()
        return self.compute(self.tr("smart") + " …", lambda: self._smart_cells(cells, points, usable, seed, mode, flatness,
                                                                               bend, stop_bends, clearance, reach))

    def _smart_cells(self, cells, points, usable, seed, mode, flatness, bend, stop_bends, clearance, reach):
        size = self.map.resolution
        step = 1.8 * size
        open_ids = np.flatnonzero(usable)
        start = int(np.searchsorted(open_ids, seed))
        if mode == "plane":
            found = open_ids[labels.plane_at(points[open_ids], start, 4 * size, flatness)]
        elif mode == "surface":
            found = open_ids[labels.grow(points[open_ids], start, step, bend)]
        else:
            part, low = open_ids, EMPTY
            if clearance > 0:
                try:
                    height = labels.height_above_ground(points, max(4 * size, 0.5), 15.0, clearance)
                    flat = np.isfinite(height) & (height <= clearance)
                    part = np.flatnonzero((flat == flat[seed]) & usable)
                    if not flat[seed]:
                        low = np.flatnonzero(flat & usable & (height > min(clearance / 3.0, size / 2.0)))
                except ValueError:
                    pass
            found = part[labels.connected(points[part], int(np.searchsorted(part, seed)), step,
                                          bend if stop_bends else None, reach / 3.0, cells=cells[part])]
            found = labels.with_feet(points, found, low, step)
        return pack(cells[found])

    def _smart_click(self, x, y, ctrl):
        hit = self.pick(*self.viewport.ray(x, y))
        if hit is None:
            return
        keys = self.smart_keys(hit[0])
        if not len(keys):
            return
        if self.at_once.isChecked() and not ctrl:
            self.label_voxels(keys, self.active_class, "tool_smart")
        else:
            self.select(keys, "remove" if ctrl else "add", trusted=True)
            self.status(self.tr("status_smart", n=len(keys)), 0)

    def build_voxel_smart_section(self, layout):
        t, values, W = self.tr, self.panel_values, QtWidgets
        group = Section(t("smart"), "smart")
        group.setToolTip(t("smart_tip"))
        form = W.QFormLayout(group)
        self.smart_box = W.QComboBox()
        for mode in SMART_MODES:
            self.smart_box.addItem(t(f"smart_{mode}"), mode)
        self.smart_box.setCurrentIndex(SMART_MODES.index(values["smart"]))
        form.addRow(t("smart_mode"), self.smart_box)
        size = self.map.resolution
        self.reach = spin(size, RANGE_LIMIT, values["reach"], 0.5)
        self.flatness = spin(size / 10, RANGE_LIMIT, values["flatness"] or size / 2, size / 2)
        self.bend = spin(1.0, 90.0, values["bend"], 1.0, decimals=1)
        form.addRow(t("smart_reach"), self.reach)
        form.addRow(t("smart_flatness"), self.flatness)
        form.addRow(t("smart_bend"), self.bend)
        self.stop_bends = W.QCheckBox(t("smart_stop_bends"))
        self.stop_bends.setChecked(values["stop_bends"])
        self.stop_bends.setToolTip(t("smart_stop_bends_tip"))
        form.addRow(self.stop_bends)
        self.clearance = spin(0.0, 10.0, values["clearance"], size)
        self.clearance.setToolTip(t("smart_clearance_tip"))
        form.addRow(t("smart_clearance"), self.clearance)
        self.at_once = W.QCheckBox(t("smart_at_once"))
        self.at_once.setChecked(values["at_once"])
        form.addRow(self.at_once)
        group.add_to(layout)

    def select_voxel_class(self):
        keys = self.map.occupied
        self.select(keys[self.vlabels.get(keys) == self.active_class], "replace", review=True)

    def select_mixed(self):
        """Select voxels whose points did not agree on one class: borders, or voxels too coarse for the detail."""
        found = self.vlabels.mixed(self.map.occupied, self.purity.value())
        self.select(found, "replace", review=True)
        self.status(self.tr("status_filter", n=len(self.selected)), 10000)

    def step_back(self, source, target, undo):
        if not source:
            return
        kinds = source.pop()
        done = []
        for kind in (reversed(kinds) if undo else kinds):
            if kind == "classes":
                if self._swap_classes(*((self._class_undo, self._class_redo) if undo else
                                        (self._class_redo, self._class_undo))):
                    done.append(kind)
                continue
            stack = self.map if kind == "map" else self.vlabels
            if (stack.undo if undo else stack.redo)():
                done.append(kind)
        if done:
            target.append(kinds)
            if "map" in kinds:
                self._after_change()
            if "label" in kinds:
                self._after_voxel_labels()

    # ---- conversions

    def ask_relabel_back(self):
        """Before points come back: say how many voxels were relabeled; their points will take the new class."""
        keys, _ = self.vlabels.edited()
        if self.source is None or not len(keys):
            return True
        answer = QtWidgets.QMessageBox.question(self.window, self.tr("to_cloud"),
                                                self.tr("relabel_back", n=len(keys)))
        return answer == QtWidgets.QMessageBox.Yes

    # ---- panel

    def build_voxel_label_section(self, layout):
        t, values, W = self.tr, self.panel_values, QtWidgets
        group = Section(t("labels"), "labels")
        group.setToolTip(t("voxel_labels_tip"))
        form = W.QFormLayout(group)
        self.by_class = W.QCheckBox(t("colour_by_class"))
        self.by_class.setChecked(values["by_class"])
        self.by_class.toggled.connect(lambda *_: self.refresh())
        form.addRow(self.by_class)
        self.protect = W.QCheckBox(t("label_protect"))
        self.protect.setChecked(values["protect"])
        self.protect.setToolTip(t("label_protect_tip"))
        self.protect.toggled.connect(lambda *_: self._sync_label_bar())
        form.addRow(self.protect)
        self.active_label = W.QLabel()
        form.addRow(self.active_label)
        self.class_list = W.QTreeWidget()
        self.class_list.setRootIsDecorated(False)
        self.class_list.setHeaderLabels([t("class_name"), t("class_voxels")])
        self.class_list.header().setSectionResizeMode(0, W.QHeaderView.Stretch)
        self.class_list.header().setSectionResizeMode(1, W.QHeaderView.ResizeToContents)
        self.class_list.header().setStretchLastSection(False)
        self.class_list.setMinimumHeight(150)
        self.class_list.currentItemChanged.connect(
            lambda item, *_: item is not None and item.data(0, Qt.UserRole) != UNLABELED
            and self.set_active(item.data(0, Qt.UserRole)))
        self.class_list.itemDoubleClicked.connect(self.edit_voxel_class)
        form.addRow(self.class_list)
        row = W.QHBoxLayout()
        row.addWidget(add_button(t("class_add"), self.add_voxel_class))
        row.addWidget(button(t("class_edit"), self.edit_voxel_class, icon="class_edit"))
        form.addRow(row)
        self.apply_button = button(t("label_assign"), lambda: self.assign_selection(), t("label_assign_tip"))
        self.apply_button.setMinimumHeight(32)
        form.addRow(self.apply_button)
        row = W.QHBoxLayout()
        row.addWidget(button(t("label_clear"), lambda: self.assign_selection(UNLABELED), icon="tag_clear"))
        row.addWidget(select_button(t("label_select_class"), self.select_voxel_class, icon="select_class"))
        form.addRow(row)
        self.purity = spin(0.05, 1.0, values["purity"], 0.05, decimals=2)
        self.purity.setToolTip(t("purity_tip"))
        form.addRow(t("purity"), self.purity)
        form.addRow(select_button(t("select_mixed"), self.select_mixed, t("purity_tip"), icon="mixed"))
        group.add_to(layout)
        self._fill_voxel_classes()

    def voxel_label_values(self):
        return {"by_class": self.by_class.isChecked(), "purity": self.purity.value(), "protect": self.protect.isChecked(),
                "smart": self.smart_box.currentData(), "reach": self.reach.value(), "flatness": self.flatness.value(),
                "bend": self.bend.value(), "clearance": self.clearance.value(),
                "stop_bends": self.stop_bends.isChecked(), "at_once": self.at_once.isChecked()}

    def _fill_voxel_classes(self):
        tree = self.class_list
        tree.blockSignals(True)
        tree.clear()
        for number in [UNLABELED] + self.classes.numbers():
            name = self.tr("class_unlabeled") if number == UNLABELED else self.classes.name(number)
            item = QtWidgets.QTreeWidgetItem([f"{number}  {name}", ""])
            item.setData(0, Qt.UserRole, number)
            item.setIcon(0, swatch(self.classes.rgb(number)))
            tree.addTopLevelItem(item)
        tree.blockSignals(False)
        self._mark_voxel_active()
        QtCore.QTimer.singleShot(0, self._voxel_stats)

    def _mark_voxel_active(self):
        for row in range(self.class_list.topLevelItemCount()):
            item = self.class_list.topLevelItem(row)
            if item.data(0, Qt.UserRole) == self.active_class:
                self.class_list.blockSignals(True)
                self.class_list.setCurrentItem(item)
                self.class_list.blockSignals(False)
        self.active_label.setText(self.tr("class_active", name=self.classes.name(self.active_class)))
        self.active_label.setStyleSheet("font-weight: 700; border-left: 12px solid rgb({}, {}, {}); padding-left: 6px;"
                                        .format(*self.classes.rgb(self.active_class)))
        self.apply_button.setText(self.tr("label_apply", name=self.classes.name(self.active_class)))
        tint(self.apply_button, self.classes.rgb(self.active_class), "labels")

    def _voxel_stats(self):
        if self._closed or not self.label_panel:
            return
        counts = self.vlabels.counts(self.map.occupied)
        for row in range(self.class_list.topLevelItemCount()):
            item = self.class_list.topLevelItem(row)
            item.setText(1, f"{counts.get(item.data(0, Qt.UserRole), 0):,}")

    def _voxel_classes_changed(self):
        self._palette = self.classes.palette(max([1] + self.classes.numbers()))
        self._sync_label_bar()
        if self.label_panel:
            self._fill_voxel_classes()
        self.refresh()

    def add_voxel_class(self):
        answer = ask_class(self.window, self.tr, self.classes)
        if answer:
            self._remember_classes()
            self.classes.set(*answer)
            self.active_class = answer[0]
            self._voxel_classes_changed()

    def edit_voxel_class(self, *_):
        if self.active_class in self.classes:
            answer = ask_class(self.window, self.tr, self.classes, self.active_class)
            if answer:
                self._remember_classes()
                self.classes.set(*answer)
                self._voxel_classes_changed()

    def voxel_label_actions(self):
        t = self.tr
        return ([(f"{t('label_assign')}: {position}", f"Ctrl+{position}", lambda p=position: self.class_key(p))
                 for position in range(1, 10)] +
                [(t("label_assign"), ["Return", "Enter"], lambda: typing() or self.assign_selection()),
                 (t("label_protect"), "P", self.toggle_protect),
                 (t("label_clear"), "Ctrl+0", lambda: self.assign_selection(UNLABELED))])


def typing():
    """True while a text or number field has the keyboard, so Enter belongs to it."""
    focus = QtWidgets.QApplication.focusWidget()
    return isinstance(focus, (QtWidgets.QAbstractSpinBox, QtWidgets.QLineEdit, QtWidgets.QAbstractItemView))
