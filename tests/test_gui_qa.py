"""Whole labeling sessions driven through the same paths a user takes, with the editor's state checked after every step.

After each step the lists, the corner bar, the toolbar and the dirty flag must agree with the data; at the end
every step is undone one by one back to the start and redone to the end, comparing full snapshots.
Needs a display: MAPBARBER_GUI_TESTS=1 pytest.
"""
import copy
import json
import os
import sys
import time
import traceback

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("MAPBARBER_GUI_TESTS") != "1", reason="set MAPBARBER_GUI_TESTS=1")


@pytest.fixture()
def session(tmp_path):
    from mapbarber.qt import QtWidgets
    from mapbarber.app import launch
    errors = []
    previous_hook = sys.excepthook
    sys.excepthook = lambda kind, value, tb: errors.append("".join(traceback.format_exception(kind, value, tb)))
    asked = []
    for name in ("critical", "warning", "information", "question"):
        setattr(QtWidgets.QMessageBox, name,
                staticmethod(lambda *args, _n=name, **kw: asked.append((_n, args[1:3])) or QtWidgets.QMessageBox.Yes))
    app, window = launch(None, "en")
    window.ask_losses = lambda fmt, lines: True

    def pump(seconds=0.15):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()

    pump(0.3)
    yield Session(window, pump, errors, asked, tmp_path)
    sys.excepthook = previous_hook
    for editor in window.documents:
        editor.mark_saved()
    window.close_all(ask=False)
    window.close()
    assert not errors, errors[0]


class Session:
    def __init__(self, window, pump, errors, asked, folder):
        self.window, self.pump, self.errors, self.asked, self.folder = window, pump, errors, asked, folder
        self.history = []

    @property
    def editor(self):
        return self.window.editor

    def trigger(self, shortcut):
        """Fire the window action bound to a key, as pressing it would."""
        from mapbarber.qt import QtGui
        wanted = QtGui.QKeySequence(shortcut)
        found = [action for action in self.window.actions() if wanted in action.shortcuts()]
        assert len(found) == 1, (shortcut, [action.text() for action in found])
        assert found[0].isEnabled(), shortcut
        found[0].trigger()
        self.pump()

    def click(self, world, ctrl=False):
        """A real left click in the 3D view on a world position."""
        viewport = self.editor.viewport
        x, y = (int(v) for v in viewport.to_display(world))
        for name in ("MouseMoveEvent", "LeftButtonPressEvent", "LeftButtonReleaseEvent"):
            viewport.interactor.SetEventInformation(x, y, int(ctrl), 0)
            getattr(viewport.interactor, name)()
        self.pump()

    def snapshot(self):
        editor = self.editor
        if hasattr(editor, "cloud") and editor.sequence is not None:
            editor._store_frames()
            frames = {key: tuple(part.copy() for part in value) for key, value in editor.frame_store.items()}
            return {"frames": frames, "boxes": copy.deepcopy(editor.box_store),
                    "classes": copy.deepcopy(editor.classes.items)}
        if hasattr(editor, "cloud"):
            return {"cls": editor.labels.cls.copy(), "inst": editor.labels.inst.copy(),
                    "pending": editor.labels.pending.copy(), "alive": editor.cloud.alive.copy(),
                    "boxes": copy.deepcopy(editor.box_store), "classes": copy.deepcopy(editor.classes.items)}
        return {"keys": editor.map.occupied.copy(), "labels": editor.vlabels.get(editor.map.occupied).copy(),
                "classes": copy.deepcopy(editor.classes.items)}

    @staticmethod
    def same(a, b):
        for key in a:
            if key == "frames":
                for frame in set(a[key]) | set(b[key]):
                    one, other = a[key].get(frame), b[key].get(frame)
                    if one is None or other is None:
                        if any(part.any() for part in (one or other)):
                            return f"frame {frame}"
                    elif not all(np.array_equal(x, y) for x, y in zip(one, other)):
                        return f"frame {frame}"
            elif key == "boxes":
                if {k: v for k, v in a[key].items() if v} != {k: v for k, v in b[key].items() if v}:
                    return key
            elif isinstance(a[key], np.ndarray):
                if not np.array_equal(a[key], b[key]):
                    return key
            elif a[key] != b[key]:
                return key
        return None

    def step(self, tag, action=None, undoable=True):
        """Run one user step, check every invariant, and remember the state for the undo walk."""
        if not self.history:
            self.history.append(("start", self.snapshot()))
        if action is not None:
            action()
        self.pump()
        assert not self.errors, (tag, self.errors[0])
        self.check(tag)
        if undoable:
            now = self.snapshot()
            assert self.same(self.history[-1][1], now) is not None, f"{tag}: the step changed nothing"
            self.history.append((tag, now))

    def check(self, tag):
        from mapbarber.qt import QtCore
        window, editor = self.window, self.editor
        assert window.dock is not None and window.dock.isVisible(), f"{tag}: side panel missing"
        assert editor.tool in dict(editor.tools), (tag, editor.tool)
        assert window.tool_actions[editor.tool].isChecked(), (tag, editor.tool)
        assert window.label_action.isChecked() == editor.label_mode, tag
        assert editor.label_bar.isVisible() == editor.label_mode, tag
        if not hasattr(editor, "cloud"):
            if editor.label_mode:
                assert editor.label_bar.protect.isChecked() == editor.protecting() == editor.protect.isChecked(), tag
                counts = editor.vlabels.counts(editor.map.occupied)
                for row in range(editor.class_list.topLevelItemCount()):
                    item = editor.class_list.topLevelItem(row)
                    assert item.text(1) == f"{counts.get(item.data(0, QtCore.Qt.UserRole), 0):,}", (tag, item.text(0))
            assert editor.dirty == (editor.map.dirty or editor.vlabels.dirty), tag
            return
        alive = editor.cloud.alive
        assert not editor.selected[~alive].any(), f"{tag}: removed points still selected"
        assert editor.dirty == (editor.cloud.dirty or editor.labels.dirty or bool(editor.frame_dirty)
                                or bool(editor.box_dirty)), tag
        assert editor.colour_box.currentData() in editor.colour_modes(), tag
        if not editor.label_mode:
            assert not hasattr(editor, "class_list") or not editor.label_panel
            return
        editor._update_stats()
        assert editor.colour_box.currentData() == "label", f"{tag}: colour mode changed to {editor.colour_box.currentData()}"
        assert editor.label_bar.protect.isChecked() == editor.protecting(), tag
        assert editor.classes.name(editor.active_class) in editor.label_bar.active.text(), tag
        assert editor.classes.name(editor.active_class) in editor.apply_button.text(), tag
        counts = editor.labels.counts(alive)
        for row in range(editor.class_list.topLevelItemCount()):
            item = editor.class_list.topLevelItem(row)
            assert item.text(1) == f"{counts.get(item.data(0, QtCore.Qt.UserRole), 0):,}", (tag, item.text(0))
        numbers = np.unique(editor.labels.inst[alive])
        listed = [editor.instance_list.topLevelItem(row).data(0, QtCore.Qt.UserRole)
                  for row in range(editor.instance_list.topLevelItemCount())]
        assert listed == numbers[numbers > 0].tolist(), f"{tag}: object list {listed} but objects {numbers.tolist()}"
        boxes = sum(len(editor._boxes_of(key)) for key in editor._box_keys())
        assert editor.box_list.topLevelItemCount() == boxes, f"{tag}: box list out of step"
        for key in editor._box_keys():
            for box in editor._boxes_of(key):
                if box.get("instance"):
                    mine = editor._key_ids(key)
                    assert (editor.labels.inst[mine] == box["instance"]).any(), f"{tag}: a box outlived its object"
        if editor.sequence is not None:
            assert editor.timeline.isVisible(), tag
            assert (editor.timeline.slider.first, editor.timeline.slider.last) == (editor.frame_ids[0], editor.frame_ids[-1])
            assert [editor.frame_list.row(i) for i in editor.frame_list.selectedItems()] == editor.frame_ids, tag

    def walk_history(self):
        """Undo every step back to the start, then redo them all, comparing whole snapshots each time."""
        for index in range(len(self.history) - 1, 0, -1):
            self.trigger("Ctrl+Z")
            wrong = self.same(self.history[index - 1][1], self.snapshot())
            assert wrong is None, f"undo of '{self.history[index][0]}' left '{wrong}' different"
            self.check(f"after undoing {self.history[index][0]}")
        for index in range(1, len(self.history)):
            self.trigger("Ctrl+Shift+Z")
            wrong = self.same(self.history[index][1], self.snapshot())
            assert wrong is None, f"redo of '{self.history[index][0]}' left '{wrong}' different"
            self.check(f"after redoing {self.history[index][0]}")


def workshop(seed=0):
    """A floor with three crates and a column of points standing on it."""
    rng = np.random.default_rng(seed)
    floor = np.column_stack([rng.uniform(-5, 5, 30000), rng.uniform(-5, 5, 30000), rng.normal(0, 0.004, 30000)])
    crates = [rng.uniform([x - 0.3, 1.6, 0.03], [x + 0.3, 2.4, 0.9], (1500, 3)) for x in (-3.0, 0.0, 3.0)]
    angle = rng.uniform(0, 2 * np.pi, 1500)
    column = np.column_stack([0.2 * np.cos(angle), -2.0 + 0.2 * np.sin(angle), rng.uniform(0.03, 1.7, 1500)])
    parts = [floor] + crates + [column]
    return np.vstack(parts), np.repeat(np.arange(len(parts)), [len(part) for part in parts])


def test_label_objects_boxes_session(session):
    from mapbarber import formats
    from mapbarber.qt import QtCore
    points, part = workshop()
    path = str(session.folder / "workshop.pcd")
    formats.save_cloud(path, points)
    assert session.window.open(path)
    session.pump(0.3)
    editor = session.editor
    session.step("open", undoable=False)
    session.step("labeling mode", lambda: session.trigger("Ctrl+L"), undoable=False)
    assert editor.label_mode and editor.protecting()

    session.step("smart tool", lambda: session.trigger("W"), undoable=False)
    editor.smart_box.setCurrentIndex(editor.smart_box.findData("plane"))
    editor.reach.setValue(20.0)
    session.step("pick the floor", lambda: session.click((2.0, -3.0, 0.0)), undoable=False)
    assert editor.selected[part == 0].mean() > 0.97 and not editor.selected[points[:, 2] > 0.2].any()
    session.step("label it floor", lambda: session.trigger("Ctrl+1"))
    assert (editor.labels.cls[part == 0] == 1).mean() > 0.97 and not editor.selected.any()

    editor.smart_box.setCurrentIndex(editor.smart_box.findData("object"))
    editor.look_from((0.3, -1, 0.9), (0, 0, 1))
    session.pump()
    editor.class_list.setCurrentItem(editor.class_list.topLevelItem(5))
    assert editor.active_class == 5
    session.step("pick a crate", lambda: session.click(points[part == 2][np.argmax(points[part == 2][:, 2])]), undoable=False)
    assert editor.selected[part == 2].mean() > 0.9 and not editor.selected[part == 0].any()
    session.step("label it with Enter", lambda: session.trigger("Return"))
    assert (editor.labels.cls[part == 2] == 5).mean() > 0.9

    session.step("select tool", lambda: session.trigger("V"), undoable=False)
    width, height = editor.viewport.renderer.GetSize()
    session.step("rectangle over everything", lambda: editor._rectangle((0, 0), (width, height), False), undoable=False)
    assert editor.selected.any() and not editor.selected[editor.labels.cls > 0].any(), "protection let labeled points in"
    crates_left = (part == 1) | (part == 3)
    editor.select(np.flatnonzero(crates_left), "replace")
    session.step("label the other crates", lambda: session.trigger("Ctrl+5"))
    floor_before = editor.labels.cls.copy()

    session.step("boxes for the class", lambda: editor.class_boxes.click())
    assert np.array_equal(editor.labels.cls, floor_before), "making boxes changed class labels"
    assert len(editor.box_store[None]) == 3 and len(np.unique(editor.labels.inst[editor.labels.cls == 5])) >= 3
    assert all(box["class"] == 5 for box in editor.box_store[None])

    editor.box_list.setCurrentItem(editor.box_list.topLevelItem(0))
    session.step("turn a box", lambda: editor.box_fields[6].setValue(25.0))
    assert np.isclose(np.degrees(editor.box_store[None][0]["yaw"]), 25.0)
    editor.box_list.setCurrentItem(editor.box_list.topLevelItem(2))
    session.step("delete the chosen box with Delete", lambda: session.trigger("Delete"))
    assert len(editor.box_store[None]) == 2 and editor.cloud.alive.all()

    editor.instance_list.setCurrentItem(editor.instance_list.topLevelItem(0))
    editor._instance_chosen(editor.instance_list.topLevelItem(0))
    gone = editor.instance_list.topLevelItem(0).data(0, QtCore.Qt.UserRole)
    members = np.flatnonzero(editor.labels.inst == gone)
    session.step("delete the chosen object with Delete", lambda: session.trigger("Delete"))
    assert editor.cloud.alive.all() and not (editor.labels.inst == gone).any()
    assert (editor.labels.cls[members] == 5).all(), "deleting an object must keep its class"
    assert all(box.get("instance") != gone for box in editor.box_store[None])

    session.step("select the column", lambda: editor.select(np.flatnonzero(part == 4), "replace"), undoable=False)
    session.step("label it person", lambda: session.trigger("Ctrl+7"))
    people = editor.labels.cls == 7
    assert people[part == 4].mean() > 0.9
    session.step("select class person", lambda: editor.select_class(), undoable=False)
    assert np.array_equal(editor.selected, people), "protection must not keep 'select class' from its own points"
    session.step("clear its label with Delete", lambda: session.trigger("Delete"))
    assert editor.cloud.alive.all() and not (editor.labels.cls == 7).any()

    session.step("protection off from the corner bar", lambda: editor.label_bar.protect.click(), undoable=False)
    assert not editor.protecting() and editor.rule_box.currentData() == "all"
    session.step("label brush", lambda: session.trigger("B"), undoable=False)
    editor.radius.setValue(0.3)
    target = points[part == 3][np.argmax(points[part == 3][:, 2])]
    session.step("brush over a labeled crate", lambda: session.click(target))
    assert (editor.labels.cls[np.linalg.norm(points - target, axis=1) < 0.25] == 7).all()
    session.step("protection back on with P", lambda: session.trigger("P"), undoable=False)
    assert editor.protecting() and editor.label_bar.protect.isChecked()

    count = len(editor.classes)
    editor.class_list.setCurrentItem(editor.class_list.topLevelItem(3))
    session.step("remove a class", lambda: editor.remove_class())
    assert len(editor.classes) == count - 1

    final = session.snapshot()
    session.walk_history()
    assert session.same(final, session.snapshot()) is None

    session.step("language", lambda: session.window.set_language("ko"), undoable=False)
    assert session.same(final, session.snapshot()) is None and editor.label_mode
    session.window.set_language("en")
    session.pump()

    assert session.window.save() and not editor.dirty
    session.check("after saving")
    stored = formats.table_labels(formats.read_cloud(path)[1])
    assert stored[0].tolist() == final["cls"].tolist() and stored[1].tolist() == final["inst"].tolist()
    assert len(json.load(open(path + ".boxes.json"))["boxes"]) == len(final["boxes"][None])

    session.step("back to editing", lambda: session.trigger("Ctrl+L"), undoable=False)
    session.window.set_tool("select")
    editor.select(np.flatnonzero(part == 1), "replace")
    session.trigger("Delete")
    assert not editor.cloud.alive[part == 1].any(), "Delete removes points in editing mode"
    session.step("labeling again", lambda: session.trigger("Ctrl+L"), undoable=False)
    session.trigger("Ctrl+L")
    session.trigger("Ctrl+Z")
    assert editor.cloud.alive.all()

    session.window.close_document(editor, ask=False)
    assert session.window.open(path)
    session.pump(0.3)
    session.trigger("Ctrl+L")
    again = session.editor
    assert again.labels.cls.tolist() == final["cls"].tolist() and again.labels.inst.tolist() == final["inst"].tolist()
    assert again.box_store[None] == [{k: v for k, v in box.items() if k != "name"} for box in final["boxes"][None]]
    session.history = []
    session.check("reopened")


def test_frames_session(session):
    from mapbarber import formats
    folder = session.folder / "drive"
    (folder / "velodyne").mkdir(parents=True)
    rng = np.random.default_rng(3)
    road = np.column_stack([rng.uniform(-5, 25, 4000), rng.uniform(-4, 4, 4000), np.zeros(4000)])
    car = rng.uniform([8.0, 2.0, 0.05], [12.0, 3.6, 1.5], (600, 3))
    count = len(road) + len(car) + 60
    for index in range(6):
        walker = rng.uniform([2.0 + index, -3.0, 0.3], [2.4 + index, -2.6, 1.7], (60, 3))
        scan = np.vstack([road, car, walker]) - [index, 0, 0]
        np.column_stack([scan, np.zeros(count)]).astype("<f4").tofile(str(folder / "velodyne" / f"{index:06d}.bin"))
    (folder / "poses.txt").write_text("".join(f"1 0 0 {i} 0 1 0 0 0 0 1 0\n" for i in range(6)))
    assert session.window.open(str(folder))
    session.pump(0.3)
    editor = session.editor
    session.step("open frames", undoable=False)
    assert editor.label_mode and not session.window.label_action.isEnabled()

    session.step("frames 0 to 2 from the timeline", lambda: editor.timeline.slider.on_range(0, 2), undoable=False)
    assert editor.frame_ids == [0, 1, 2] and len(editor.cloud.xyz) == 3 * count
    road_ids = np.concatenate([np.arange(4000) + k * count for k in range(3)])
    car_ids = np.concatenate([np.arange(4000, 4600) + k * count for k in range(3)])
    editor.select(road_ids, "replace")
    editor.set_active(40)
    session.step("label the road", lambda: session.trigger("Return"))
    road_class = editor.active_class
    assert editor.classes.name(road_class) == "road"
    editor.select(car_ids, "replace")
    session.step("label the car", lambda: session.trigger("Ctrl+2"))
    car_class = editor.active_class

    editor.paint_frame.setCurrentIndex(editor.paint_frame.findData(1))
    editor.select(np.arange(3 * count), "replace")
    editor.set_active(30)
    session.step("label what is left of frame 1 only", lambda: session.trigger("Return"))
    assert (editor.labels.cls[count + 4600:2 * count] == 30).all() and not editor.labels.cls[4600:count].any()
    editor.paint_frame.setCurrentIndex(0)

    editor.set_active(car_class)
    assert editor.object_gap.value() == 0.5, "frame folders start with a gap that suits sparse scans"
    editor.object_gap.setValue(0.8)
    session.step("boxes for the car class", lambda: editor.class_boxes.click())
    assert [len(editor.box_store[k]) for k in (0, 1, 2)] == [1, 1, 1]
    assert np.isclose(editor.box_store[2][0]["center"][0], 8.0, atol=0.1), "boxes are kept in the sensor frame"

    session.step("carry labels to the other frames", lambda: editor.propagate_frames())
    assert (editor.frame_store[4][0][:4000] == road_class).all() and editor.frame_store[4][2][:4000].all()
    assert not editor.frame_store[4][0][4600:].any(), "a moving object must not be carried over"

    session.step("next frames", lambda: session.trigger("."), undoable=False)
    assert editor.frame_ids == [1, 2, 3]
    session.step("confirm the suggestions", lambda: editor.confirm_pending())
    final = session.snapshot()
    session.walk_history()
    assert session.same(final, session.snapshot()) is None

    assert session.window.save() and not editor.dirty
    session.check("after saving frames")
    for index in range(6):
        cls, _ = formats.read_label_file(str(folder / "labels" / f"{index:06d}.label"), count)
        assert (cls[:4000] == road_class).all()
    assert len(json.load(open(folder / "boxes" / "000001.json"))["boxes"]) == 1

    out = session.folder / "export"
    out.mkdir()
    editor.export_standard(str(out), [True, True, True, True])
    assert sorted(os.listdir(out / "velodyne")) == [f"{i:06d}.bin" for i in range(6)]
    assert sorted(os.listdir(out / "label_2")) == sorted(os.listdir(out / "calib")) == [f"{i:06d}.txt" for i in range(6)], \
        "KITTI object needs a label and a calibration file for every frame"
    assert (out / "label_2" / "000005.txt").read_text() == "" and (out / "ImageSets" / "train.txt").read_text().split()[0] == "000000"
    tracks = [line.split() for line in (out / "tracking" / "label_02" / "0000.txt").read_text().splitlines()]
    assert tracks and all(len(row) == 17 for row in tracks) and tracks[0][2] == editor.classes.name(car_class)
    assert sorted(os.listdir(out / "openpcdet" / "labels")) == [f"{i:06d}.txt" for i in range(6)]
    assert (np.fromfile(str(out / "labels" / "000002.label"), "<u4")[4000:4600] & 0xFFFF == car_class).all()
    assert (out / "label_2" / "000001.txt").read_text().split()[0] == editor.classes.name(car_class)
    assert len((out / "poses.txt").read_text().splitlines()) == 6

    session.window.close_document(editor, ask=False)
    assert session.window.open(str(folder))
    session.pump(0.3)
    again = session.editor
    again.show_frames([0, 1, 2])
    assert (again.labels.cls[road_ids] == road_class).all() and (again.labels.cls[car_ids] == car_class).all()
    assert [len(again._boxes_of(k)) for k in (0, 1, 2)] == [1, 1, 1] and not again.dirty
    session.history = []
    session.check("frames reopened")


def test_voxel_session(session):
    from mapbarber.formats import VOXEL
    from mapbarber.voxels import pack
    floor = np.stack(np.meshgrid(np.arange(40), np.arange(40), [0], indexing="ij"), -1).reshape(-1, 3)
    crate = np.stack(np.meshgrid(np.arange(10, 16), np.arange(10, 16), np.arange(1, 8), indexing="ij"), -1).reshape(-1, 3)
    editor = session.window.show_document(VOXEL, (pack(np.vstack([floor, crate])), 0.05))
    session.pump(0.3)
    session.step("voxels open", undoable=False)
    session.step("labeling mode", lambda: session.trigger("Ctrl+L"), undoable=False)
    session.step("smart tool", lambda: session.trigger("W"), undoable=False)
    editor.look_from((1, -1, 0.8), (0, 0, 1))
    session.pump()
    session.step("pick the crate", lambda: session.click((0.65, 0.65, 0.4)), undoable=False)
    assert set(editor.selection.tolist()) == set(pack(crate).tolist())
    session.step("label it", lambda: session.trigger("Ctrl+5"))
    editor.smart_box.setCurrentIndex(editor.smart_box.findData("plane"))
    session.step("pick the floor", lambda: session.click((1.5, 0.3, 0.05)), undoable=False)
    assert set(editor.selection.tolist()) == set(pack(floor).tolist()), "protection keeps the labeled crate out"
    session.step("label it", lambda: session.trigger("Ctrl+1"))
    session.step("select class", lambda: editor.select_voxel_class(), undoable=False)
    total = len(editor.map)
    session.step("Delete clears labels, not voxels", lambda: session.trigger("Delete"))
    assert len(editor.map) == total and not editor.vlabels.get(pack(floor)).any()
    session.step("label brush", lambda: session.trigger("B"), undoable=False)
    session.step("brush a voxel", lambda: session.click((1.5, 0.3, 0.05)))
    final = session.snapshot()
    session.walk_history()
    assert session.same(final, session.snapshot()) is None
    session.step("back to editing", lambda: session.trigger("Ctrl+L"), undoable=False)
    session.window.set_tool("select")
    editor.select(pack(crate), "replace")
    session.trigger("Delete")
    assert len(editor.map) == total - len(crate), "Delete removes voxels in editing mode"


def test_undo_keys_reach_the_editor_from_a_number_field(session):
    from mapbarber.formats import CLOUD
    from mapbarber.qt import QtCore, QtGui, QtWidgets
    points, part = workshop(1)
    editor = session.window.show_document(CLOUD, (points, None))
    session.pump(0.3)
    session.trigger("Ctrl+L")
    editor.select(np.flatnonzero(part == 1), "replace")
    session.trigger("Ctrl+5")
    assert editor.labels.cls.any()
    field = editor.radius
    guard = QtWidgets.QApplication.instance().undo_guard
    real_focus = QtWidgets.QApplication.focusWidget
    QtWidgets.QApplication.focusWidget = staticmethod(lambda: field.findChild(QtWidgets.QLineEdit))
    try:
        press = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        assert guard.eventFilter(field, press), "the undo key was left to the number field"
        plain = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_5, QtCore.Qt.NoModifier)
        assert not guard.eventFilter(field, plain), "typing digits must still reach the number field"
    finally:
        QtWidgets.QApplication.focusWidget = real_focus
    session.pump()
    assert not editor.labels.cls.any(), "Ctrl+Z typed in a number field did not undo the editor"


def drag(session, start, end, button, ctrl=True, steps=6):
    """A real drag in the 3D view between two world positions with a mouse button held."""
    viewport = session.editor.viewport
    a, b = np.array(viewport.to_display(start), float), np.array(viewport.to_display(end), float)
    press, release = (("LeftButtonPressEvent", "LeftButtonReleaseEvent") if button == "left" else
                      ("RightButtonPressEvent", "RightButtonReleaseEvent"))
    for index in range(steps + 1):
        x, y = (int(v) for v in a + (b - a) * index / steps)
        viewport.interactor.SetEventInformation(x, y, int(ctrl), 0)
        getattr(viewport.interactor, press if index == 0 else "MouseMoveEvent")()
    getattr(viewport.interactor, release)()
    session.pump()


def camera_state(editor):
    camera = editor.viewport.renderer.GetActiveCamera()
    return camera.GetPosition() + camera.GetFocalPoint() + camera.GetViewUp() + (camera.GetParallelScale(),)


def test_ctrl_drag_paints_and_takes_back_with_the_view_fixed(session):
    from mapbarber.formats import CLOUD
    rng = np.random.default_rng(7)
    points = np.column_stack([rng.uniform(-2, 2, 20000), rng.uniform(-2, 2, 20000), np.zeros(20000)])
    editor = session.window.show_document(CLOUD, (points, None))
    session.pump(0.3)
    editor.look_from((0, 0, 1), (0, 1, 0))
    session.pump()
    strip = lambda: np.abs(points[:, 1]) < 0.05

    for mode, tool in ((False, "V"), (True, "V"), (True, "W"), (True, "B")):
        if mode != editor.label_mode:
            session.trigger("Ctrl+L")
        session.trigger(tool)
        editor.radius.setValue(0.1)
        before = camera_state(editor)
        drag(session, (-1.5, 0, 0), (1.5, 0, 0), "left")
        assert camera_state(editor) == before, f"{editor.tool}: Ctrl + left drag moved the view"
        along = strip() & (np.abs(points[:, 0]) < 1.4)
        if editor.tool == "label":
            assert (editor.labels.cls[along] == editor.active_class).mean() > 0.9
            drag(session, (-1.5, 0, 0), (0.0, 0, 0), "right")
            assert camera_state(editor) == before, "Ctrl + right drag moved the view"
            assert not editor.labels.cls[along & (points[:, 0] < -0.2)].any()
            assert (editor.labels.cls[along & (points[:, 0] > 0.3)] == editor.active_class).mean() > 0.9
            editor.undo()
            assert (editor.labels.cls[along] == editor.active_class).mean() > 0.9, "one stroke is one undo step"
            editor.undo()
            assert not editor.labels.cls.any()
        else:
            assert editor.selected[along].mean() > 0.9, f"{editor.tool}: Ctrl + left drag did not select"
            drag(session, (-1.5, 0, 0), (0.0, 0, 0), "right")
            assert camera_state(editor) == before, f"{editor.tool}: Ctrl + right drag moved the view"
            assert not editor.selected[along & (points[:, 0] < -0.2)].any()
            assert editor.selected[along & (points[:, 0] > 0.3)].mean() > 0.9
            editor.clear_selection()
        session.check(f"ctrl drag with {editor.tool}")
    drag(session, (0.5, -1.5, 0), (0.5, 1.5, 0), "right", ctrl=False)
    assert camera_state(editor) != before, "a plain right drag still zooms"


def test_wheel_reaches_inner_lists_only_after_a_click(session):
    from mapbarber.formats import CLOUD
    from mapbarber.qt import QtCore, QtGui, QtTest, QtWidgets
    points, part = workshop(2)
    editor = session.window.show_document(CLOUD, (points, None))
    session.pump(0.3)
    session.trigger("Ctrl+L")
    for number in range(20, 60):
        editor.classes.set(number, f"extra {number}")
    editor._classes_changed()
    editor.labels.assign(np.arange(3000), inst=np.arange(3000) // 20 + 1)
    editor._update_stats()
    session.pump()
    panel = session.window.dock.widget()

    def wheel(widget, delta=-120):
        target = widget.viewport()
        centre = target.rect().center()
        event = QtGui.QWheelEvent(QtCore.QPointF(centre), QtCore.QPointF(target.mapToGlobal(centre)), QtCore.QPoint(0, 0),
                                  QtCore.QPoint(0, delta), QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
                                  QtCore.Qt.NoScrollPhase, False)
        QtWidgets.QApplication.sendEvent(target, event)
        session.pump(0.05)

    for name in ("class_list", "instance_list"):
        box = getattr(editor, name)
        panel.ensureWidgetVisible(box)
        session.pump()
        assert box.verticalScrollBar().maximum() > 0, name
        box.verticalScrollBar().setValue(0)
        outer = panel.verticalScrollBar().value()
        wheel(box)
        assert box.verticalScrollBar().value() == 0, f"{name}: scrolled without being clicked"
        assert panel.verticalScrollBar().value() != outer, f"{name}: the panel should have scrolled instead"
        panel.ensureWidgetVisible(box)
        session.pump()
        outer = panel.verticalScrollBar().value()
        QtTest.QTest.mouseClick(box.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, QtCore.QPoint(40, 10))
        session.pump()
        wheel(box)
        assert box.verticalScrollBar().value() > 0, f"{name}: did not scroll after being clicked"
        assert panel.verticalScrollBar().value() == outer, f"{name}: the panel moved although the list was clicked"
        QtWidgets.QApplication.sendEvent(box, QtCore.QEvent(QtCore.QEvent.Leave))
        box.verticalScrollBar().setValue(0)
        wheel(box)
        assert box.verticalScrollBar().value() == 0, f"{name}: still scrolls after the pointer left"


def test_tracking_session(session):
    from mapbarber import formats
    folder = session.folder / "moving"
    (folder / "velodyne").mkdir(parents=True)
    rng = np.random.default_rng(5)
    road = np.column_stack([rng.uniform(-10, 40, 6000), rng.uniform(-6, 6, 6000), np.zeros(6000)])

    def body(centre, count=700):
        side = rng.integers(0, 3, count)
        local = rng.uniform([-2, -0.9, -0.7], [2, 0.9, 0.7], (count, 3))
        for axis, half in enumerate((2.0, 0.9, 0.7)):
            local[side == axis, axis] = half * rng.choice([-1, 1], int((side == axis).sum()))
        return local + centre

    shape, parked = body([0, 0, 0]), body([20.0, -3.5, 0.95])
    count = len(road) + len(shape) + len(parked)
    for index in range(6):
        mover = shape + [5.0 + 1.2 * index, 2.5, 0.95]
        scan = np.vstack([road, mover, parked]) - [0.5 * index, 0, 0]
        np.column_stack([scan, np.zeros(count)]).astype("<f4").tofile(str(folder / "velodyne" / f"{index:06d}.bin"))
    (folder / "poses.txt").write_text("".join(f"1 0 0 {0.5 * i} 0 1 0 0 0 0 1 0\n" for i in range(6)))
    assert session.window.open(str(folder))
    session.pump(0.3)
    editor = session.editor
    session.step("open", undoable=False)
    mover_ids, parked_ids = np.arange(6000, 6700), np.arange(6700, 7400)
    editor.select(np.concatenate([mover_ids, parked_ids]), "replace")
    editor.set_active(10)
    session.step("label both cars in frame 0", lambda: session.trigger("Return"))
    session.step("box them", lambda: editor.class_boxes.click())
    assert len(editor.box_store[0]) == 2
    numbers = {int(editor.labels.inst[mover_ids[0]]): "mover", int(editor.labels.inst[parked_ids[0]]): "parked"}
    assert len(numbers) == 2

    session.step("track with one frame on screen", lambda: editor.track_boxes(), undoable=False)
    session.step("frames 0 to 5", lambda: editor.timeline.slider.on_range(0, 5), undoable=False)
    session.step("track", lambda: editor.track_boxes())
    for index in range(1, 6):
        found = {box["instance"]: box for box in editor.box_store[index]}
        assert set(found) == set(numbers), f"frame {index}: tracks {set(found)}"
        for number, name in numbers.items():
            box = found[number]
            truth = [5.0 + 1.2 * index - 0.5 * index, 2.5] if name == "mover" else [20.0 - 0.5 * index, -3.5]
            assert np.allclose(box["center"][:2], truth, atol=0.15), (index, name, box["center"])
            assert box["class"] == 10 and box["score"] > 0.6 and np.allclose(box["size"], editor.box_store[0][0]["size"], atol=1.0)
        start = int(editor.frame_starts[index])
        cls, inst = editor.labels.cls[start:start + count], editor.labels.inst[start:start + count]
        assert (cls[6000:] == 10).mean() > 0.97 and not cls[:6000].any(), f"frame {index}: wrong points labeled"
        assert (inst[6000:6700] == editor.labels.inst[mover_ids[0]]).mean() > 0.97, "the object keeps its number"
        assert (inst[6700:] == editor.labels.inst[parked_ids[0]]).mean() > 0.97
    assert editor.box_list.topLevelItemCount() == 12 and not editor.labels.pending.any()
    final = session.snapshot()
    session.walk_history()
    assert session.same(final, session.snapshot()) is None

    assert session.window.save() and not editor.dirty
    stored = json.load(open(folder / "boxes" / "000004.json"))["boxes"]
    assert len(stored) == 2 and all("score" in box for box in stored)
    packed = np.fromfile(str(folder / "labels" / "000004.label"), "<u4")
    assert (packed[6000:6700] >> 16 == editor.labels.inst[mover_ids[0]]).mean() > 0.97
    assert formats.read_label_file(str(folder / "labels" / "000004.label"), count)[0][6000:].mean() > 9.7


def test_axes_and_markers_keep_their_size_on_screen(session):
    """Outdoor scans reach far out (and hold stray points); nothing drawn as a helper may scale with that extent."""
    from mapbarber.formats import CLOUD
    rng = np.random.default_rng(8)
    near = rng.uniform([-20, -20, -2], [20, 20, 2], (20000, 3))
    stray = rng.uniform(-400, 400, (40, 3))
    editor = session.window.show_document(CLOUD, (np.vstack([near, stray]), None))
    session.pump(0.4)

    def on_screen(length):
        return length / editor.viewport.pixel_size()

    for zoom in (1.0, 6.0, 0.2):
        editor.viewport.zoom(zoom)
        session.pump(0.2)
        editor.update_levels()
        axes = editor.viewport.axes.GetTotalLength()[0]
        assert 40 <= on_screen(axes) <= 110, f"axes are {on_screen(axes):.0f} px long"
        assert 2 <= on_screen(editor._marker_size()) <= 6
    session.trigger("I")
    session.click(tuple(near[0]))
    assert 4 <= on_screen(editor.hover_source.GetRadius()) <= 16, "the measure marker must stay a few pixels wide"
    assert 2 <= on_screen(editor.ruler.marker_size) <= 6


def test_arrow_keys_slide_the_frame_range_by_its_width(session):
    from mapbarber.qt import QtCore, QtGui, QtTest, QtWidgets
    folder = session.folder / "strip"
    (folder / "velodyne").mkdir(parents=True)
    for index in range(11):
        np.column_stack([np.random.default_rng(index).uniform(-5, 5, (50, 3)), np.zeros(50)]).astype("<f4").tofile(
            str(folder / "velodyne" / f"{index:06d}.bin"))
    assert session.window.open(str(folder))
    session.pump(0.3)
    editor = session.editor
    slider = editor.timeline.slider
    assert slider.focusPolicy() == QtCore.Qt.ClickFocus

    def press(key, shift=False):
        modifiers = QtCore.Qt.ShiftModifier if shift else QtCore.Qt.NoModifier
        QtWidgets.QApplication.sendEvent(slider, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, key, modifiers))
        session.pump()
        session.check("after an arrow key")

    slider.on_range(0, 2)
    assert editor.frame_ids == [0, 1, 2]
    bar, focused = editor.timeline, []
    real_focus = slider.setFocus
    slider.setFocus = lambda *reason: focused.append(True)
    for widget, spot in ((bar.caption, bar.caption.rect().center()), (bar, QtCore.QPoint(bar.width() - 4, bar.height() // 2)),
                         (slider, QtCore.QPoint(slider.width() - 30, slider.height() // 2))):
        QtTest.QTest.mouseClick(widget, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, spot)
        session.pump()
        assert editor.frame_ids == [0, 1, 2], "a click beside the handles must not move the range"
    assert len(focused) >= 2, "a click on the frame numbers or the strip gives the slider the keyboard"
    slider.setFocus = real_focus
    slider.on_focus(True)
    assert "4f9cf7" in bar.styleSheet()
    slider.on_focus(False)
    press(QtCore.Qt.Key_Right)
    assert editor.frame_ids == [3, 4, 5]
    press(QtCore.Qt.Key_Right)
    assert editor.frame_ids == [6, 7, 8]
    press(QtCore.Qt.Key_Right)
    assert editor.frame_ids == [8, 9, 10], "the last range stops at the last frame and keeps its width"
    press(QtCore.Qt.Key_Right)
    assert editor.frame_ids == [8, 9, 10]
    press(QtCore.Qt.Key_Left, shift=True)
    assert editor.frame_ids == [7, 8, 9]
    press(QtCore.Qt.Key_Left)
    assert editor.frame_ids == [4, 5, 6]
    press(QtCore.Qt.Key_Left)
    press(QtCore.Qt.Key_Left)
    assert editor.frame_ids == [0, 1, 2]
    editor.select(np.arange(50), "replace")
    editor.set_active(40)
    editor.assign_selection()
    press(QtCore.Qt.Key_Right)
    assert editor.frame_store[0][0].tolist() == [40] * 50, "labels stay with their frame when the range moves on"
    press(QtCore.Qt.Key_Left)
    assert (editor.labels.cls[:50] == 40).all()

    def drag(dx):
        at = QtCore.QPoint(int(slider._x(slider.first)), slider.height() // 2)
        QtTest.QTest.mousePress(slider, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, at)
        for step in range(1, 7):
            QtWidgets.QApplication.sendEvent(slider, QtGui.QMouseEvent(
                QtCore.QEvent.MouseMove, QtCore.QPointF(at.x() + dx * step / 6, at.y()), QtCore.QPointF(at.x() + dx * step / 6, at.y()),
                QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
        QtTest.QTest.mouseRelease(slider, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                                  QtCore.QPoint(int(at.x() + dx), at.y()))
        session.pump()
        session.check("after dragging a handle")

    slider.on_range(5, 5)
    assert editor.frame_ids == [5]
    one = slider._x(1) - slider._x(0)
    drag(2.2 * one)
    assert editor.frame_ids == [5, 6, 7], "where the handles meet, dragging to the right moves the last frame"
    slider.on_range(5, 5)
    drag(-2.2 * one)
    assert editor.frame_ids == [3, 4, 5], "and dragging to the left moves the first"
    slider.on_range(5, 5)
    QtTest.QTest.mouseClick(slider, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                            QtCore.QPoint(int(slider._x(5)), slider.height() // 2))
    session.pump()
    assert editor.frame_ids == [5], "a click on the handles without moving changes nothing"


def test_tracking_keeps_up_with_a_changing_view(session):
    """A car drives past: first only its front is seen, then its side, then its back. In every frame the box
    holds what that frame and the two before it show of the car, keeps the car's heading, and no frame may keep
    car points unlabeled."""
    folder = session.folder / "passing"
    (folder / "velodyne").mkdir(parents=True)
    rng = np.random.default_rng(9)
    side = rng.integers(0, 3, 4000)
    sign = rng.choice([-1.0, 1.0], 4000)
    local = rng.uniform([-2, -0.9, -0.75], [2, 0.9, 0.75], (4000, 3))
    normals = np.zeros((4000, 3))
    for axis, half in enumerate((2.0, 0.9, 0.75)):
        local[side == axis, axis] = half * sign[side == axis]
        normals[side == axis, axis] = sign[side == axis]
    road = np.column_stack([rng.uniform(-25, 25, 9000), rng.uniform(0, 18, 9000), np.full(9000, -1.2)])
    centres, counts, views = [], [], []
    for index in range(13):
        centre = np.array([-9.0 + 1.5 * index, 9.0, -1.2 + 0.35 + 0.75])
        world = local + centre
        away = -world / np.linalg.norm(world, axis=1, keepdims=True)
        visible = np.einsum("ij,ij->i", normals, away) > 0.6
        views.append(local[visible])
        seen = world[visible]
        scan = np.vstack([road, seen])
        np.column_stack([scan, np.zeros(len(scan))]).astype("<f4").tofile(str(folder / "velodyne" / f"{index:06d}.bin"))
        centres.append(centre)
        counts.append(len(scan))
    (folder / "poses.txt").write_text("1 0 0 0 0 1 0 0 0 0 1 0\n" * 13)
    assert session.window.open(str(folder))
    session.pump(0.3)
    editor = session.editor
    session.step("open", undoable=False)
    editor.select(np.arange(9000, counts[0]), "replace")
    editor.set_active(10)
    session.step("label the car in the first frame", lambda: session.trigger("Return"))
    session.step("box it", lambda: editor.class_boxes.click())
    first = editor.box_store[0][0]
    assert first["size"][0] * first["size"][1] < 0.75 * 4.0 * 1.8, "the first frame shows only part of the car"
    number = first["instance"]

    session.step("all frames", lambda: editor.timeline.slider.on_range(0, 12), undoable=False)
    session.step("track", lambda: editor.track_boxes())
    for index in range(1, 13):
        boxes = [box for box in editor.box_store[index] if box["instance"] == number]
        assert len(boxes) == 1, f"frame {index}: {len(boxes)} boxes"
        box = boxes[0]
        seen = np.vstack([views[k] for k in range(max(0, index - 2), index + 1)])
        low, high = seen.min(axis=0), seen.max(axis=0)
        assert np.allclose(box["size"], high - low, atol=0.25), (index, box["size"], high - low)
        assert abs(np.sin(box["yaw"])) < np.sin(np.radians(3.0)), (index, np.degrees(box["yaw"]))
        assert np.allclose(box["center"][:2], (centres[index] + (low + high) / 2.0)[:2], atol=0.25), (index, box["center"])
        start = int(editor.frame_starts[index])
        cls = editor.labels.cls[start:start + counts[index]]
        inst = editor.labels.inst[start:start + counts[index]]
        assert (cls[9000:] == 10).mean() > 0.97, f"frame {index}: {(cls[9000:] != 10).sum()} car points left unlabeled"
        assert (inst[9000:] == number).mean() > 0.97 and not cls[:9000].any()
    session.step("look for points left outside", lambda: editor.select_leftovers(), undoable=False)
    assert editor.selected.sum() < 40
    editor.clear_selection()
    final = session.snapshot()
    session.walk_history()
    assert session.same(final, session.snapshot()) is None


def test_points_left_outside_a_box_can_be_taken_in(session):
    from mapbarber.formats import CLOUD
    rng = np.random.default_rng(10)
    floor = np.column_stack([rng.uniform(-4, 4, 6000), rng.uniform(-4, 4, 6000), np.zeros(6000)])
    crate = rng.uniform([-1.0, -0.4, 0.3], [1.0, 0.4, 1.1], (3000, 3))
    editor = session.window.show_document(CLOUD, (np.vstack([floor, crate]), None))
    session.pump(0.3)
    session.trigger("Ctrl+L")
    half = 6000 + np.flatnonzero(crate[:, 0] < 0.7)
    rest = 6000 + np.flatnonzero(crate[:, 0] >= 0.7)
    editor.select(half, "replace")
    editor.set_active(5)
    session.step("label most of the crate", lambda: session.trigger("Return"))
    session.step("box it", lambda: editor.class_boxes.click())
    assert max(editor.box_store[None][0]["size"]) < 1.8
    session.step("select what is left outside", lambda: editor.select_leftovers(), undoable=False)
    assert editor.selected[rest].mean() > 0.97 and not editor.selected[:6000].any()
    editor.clear_selection()
    session.step("take it in", lambda: editor.take_leftovers())
    box = editor.box_store[None][0]
    assert (editor.labels.cls[rest] == 5).mean() > 0.97 and (editor.labels.inst[rest] == box["instance"]).mean() > 0.97
    assert np.allclose(sorted(box["size"]), [0.8, 0.8, 2.0], atol=0.08) and np.allclose(box["center"], [0, 0, 0.7], atol=0.06)
    assert not editor.labels.cls[:6000].any()
    final = session.snapshot()
    session.walk_history()
    assert session.same(final, session.snapshot()) is None


def test_view_can_be_fixed_to_the_world_the_sensor_or_a_box(session):
    folder = session.folder / "ride"
    (folder / "velodyne").mkdir(parents=True)
    rng = np.random.default_rng(11)
    road = np.column_stack([rng.uniform(-10, 40, 3000), rng.uniform(-6, 6, 3000), np.zeros(3000)])
    block = rng.uniform([-1.0, -0.5, 0.4], [1.0, 0.5, 1.6], (500, 3))
    for index in range(6):
        scan = np.vstack([road, block + [6.0 + 2.0 * index, 2.0, 0.0]]) - [1.0 * index, 0, 0]
        np.column_stack([scan, np.zeros(3500)]).astype("<f4").tofile(str(folder / "velodyne" / f"{index:06d}.bin"))
    (folder / "poses.txt").write_text("".join(f"1 0 0 {1.0 * i} 0 1 0 0 0 0 1 0\n" for i in range(6)))
    assert session.window.open(str(folder))
    session.pump(0.3)
    editor = session.editor
    bar = editor.timeline
    assert [bar.anchor.itemData(i) for i in range(bar.anchor.count())] == ["world", "lidar", "object"]

    def camera():
        view = editor.viewport.renderer.GetActiveCamera()
        return np.array(view.GetPosition()), np.array(view.GetFocalPoint())

    def axes_at():
        matrix = editor.viewport.axes.GetUserMatrix()
        return np.zeros(3) if matrix is None else np.array([matrix.GetElement(i, 3) for i in range(3)])

    position, focus = camera()
    session.step("next frame, fixed to the world", lambda: session.trigger("."), undoable=False)
    assert np.allclose(camera()[0], position) and np.allclose(axes_at(), 0)

    bar.anchor.setCurrentIndex(bar.anchor.findData("lidar"))
    session.pump()
    assert np.allclose(axes_at(), [1.0, 0, 0]), "the axes sit at the sensor of the first frame shown"
    position, focus = camera()
    session.step("next frame, fixed to the LiDAR", lambda: session.trigger("."), undoable=False)
    assert editor.frame_ids == [2]
    assert np.allclose(camera()[0], position + [1.0, 0, 0]) and np.allclose(camera()[1], focus + [1.0, 0, 0])
    assert np.allclose(axes_at(), [2.0, 0, 0])
    session.step("back two frames", lambda: (session.trigger(","), session.trigger(",")), undoable=False)
    assert np.allclose(camera()[0], position - [1.0, 0, 0])

    editor.select(np.arange(3000, 3500), "replace")
    editor.set_active(10)
    editor.assign_selection()
    editor.class_boxes.click()
    editor.timeline.slider.on_range(0, 5)
    editor.track_boxes()
    session.pump()
    assert all(len(editor.box_store[index]) == 1 for index in range(6))
    editor.timeline.slider.on_range(0, 0)
    editor.box_list.setCurrentItem(editor.box_list.topLevelItem(0))
    bar.anchor.setCurrentIndex(bar.anchor.findData("object"))
    session.pump()
    assert np.allclose(axes_at()[:2], [6.0, 2.0], atol=0.2), "the axes sit on the chosen box"
    position, focus = camera()
    session.step("next frame, fixed to the box", lambda: session.trigger("."), undoable=False)
    assert np.allclose(camera()[0], position + [2.0, 0, 0], atol=0.2), "the box moves 2 m per frame in the world"
    assert np.allclose(axes_at()[:2], [8.0, 2.0], atol=0.2)
    bar.anchor.setCurrentIndex(bar.anchor.findData("world"))
    session.pump()
    assert np.allclose(axes_at(), 0)
    session.check("anchors")


def test_a_few_mislabeled_points_do_not_spoil_a_box(session):
    from mapbarber.formats import CLOUD
    rng = np.random.default_rng(14)
    floor = np.column_stack([rng.uniform(-4, 4, 6000), rng.uniform(-4, 4, 6000), np.zeros(6000)])
    crate = rng.uniform([-1.0, -0.4, 0.3], [1.0, 0.4, 1.1], (3000, 3))
    slips = np.array([[2.2, 0.0, 0.0], [2.3, 0.1, 0.0], [-0.2, 1.5, 0.0], [0.3, 0.0, 2.0]])
    editor = session.window.show_document(CLOUD, (np.vstack([floor, crate, slips]), None))
    session.pump(0.3)
    session.trigger("Ctrl+L")
    crate_ids, slip_ids = 6000 + np.arange(3000), 9000 + np.arange(len(slips))
    editor.select(np.concatenate([crate_ids, slip_ids]), "replace")
    editor.set_active(5)
    editor.own_instance.setChecked(True)
    session.step("label the crate as one object, with a few slips", lambda: session.trigger("Return"))
    assert len(np.unique(editor.labels.inst[np.concatenate([crate_ids, slip_ids])])) == 1
    assert editor.robust_boxes.isChecked()
    session.step("box it", lambda: editor.class_boxes.click())
    box = editor.box_store[None][0]
    assert np.allclose(sorted(box["size"]), [0.8, 0.8, 2.0], atol=0.05), box["size"]
    assert np.allclose(box["center"], [0, 0, 0.7], atol=0.04) and "stray" not in box
    assert "4 stray" in editor.box_list.topLevelItem(0).text(2)
    assert "4 stray" in session.window.statusBar().currentMessage()

    editor.box_list.setCurrentItem(editor.box_list.topLevelItem(0))
    editor.robust_boxes.setChecked(False)
    session.step("refit around every labeled point", lambda: editor.refit_box())
    assert max(editor.box_store[None][0]["size"]) > 3.0 and "stray" not in editor.box_list.topLevelItem(0).text(2)
    editor.robust_boxes.setChecked(True)
    session.step("refit without the slips", lambda: editor.refit_box())
    assert np.allclose(sorted(editor.box_store[None][0]["size"]), [0.8, 0.8, 2.0], atol=0.05)

    session.step("select the stray points", lambda: editor.select_strays(), undoable=False)
    assert np.array_equal(np.flatnonzero(editor.selected), slip_ids)
    session.step("clear their labels", lambda: session.trigger("Delete"))
    assert not editor.labels.cls[slip_ids].any() and not editor.labels.inst[slip_ids].any()
    assert (editor.labels.cls[crate_ids] == 5).all() and editor.cloud.alive.all()
    assert "stray" not in editor.box_list.topLevelItem(0).text(2)
    final = session.snapshot()
    session.walk_history()
    assert session.same(final, session.snapshot()) is None


def test_a_corrected_box_is_tracked_again_up_to_the_corrected_boxes(session):
    """The track jumps onto a look-alike halfway; the box is moved back onto the right car in one frame and
    tracked again from there: the frames after it follow the right car, the frames before the jump stay as
    they were, the look-alike loses the labels, and the corrected box is left alone by a later full track."""
    folder = session.folder / "swap"
    (folder / "velodyne").mkdir(parents=True)
    rng = np.random.default_rng(15)
    side = rng.integers(0, 3, 1500)
    local = rng.uniform([-2, -0.9, -0.75], [2, 0.9, 0.75], (1500, 3))
    for axis, half in enumerate((2.0, 0.9, 0.75)):
        local[side == axis, axis] = half * rng.choice([-1.0, 1.0], (side == axis).sum())
    road = np.column_stack([rng.uniform(-25, 25, 9000), rng.uniform(0, 20, 9000), np.full(9000, -1.2)])
    height = -1.2 + 0.35 + 0.75
    layout = []
    for index in range(12):
        car = np.array([-9.0 + 1.5 * index, 9.0 if index < 6 else 13.0, height])
        parts = [road, local + car]
        if index >= 6:
            parts.append(local + [-9.0 + 1.5 * index, 9.0, height])
        scan = np.vstack(parts)
        np.column_stack([scan, np.zeros(len(scan))]).astype("<f4").tofile(str(folder / "velodyne" / f"{index:06d}.bin"))
        layout.append((car, len(scan)))
    (folder / "poses.txt").write_text("1 0 0 0 0 1 0 0 0 0 1 0\n" * 12)
    assert session.window.open(str(folder))
    session.pump(0.3)
    editor = session.editor
    session.step("open", undoable=False)
    editor.select(np.arange(9000, 10500), "replace")
    editor.set_active(10)
    session.step("label the car in the first frame", lambda: session.trigger("Return"))
    session.step("box it", lambda: editor.class_boxes.click())
    number = editor.box_store[0][0]["instance"]
    session.step("all frames", lambda: editor.timeline.slider.on_range(0, 11), undoable=False)
    session.step("track", lambda: editor.track_boxes())

    def box_of(frame):
        found = [box for box in editor.box_store[frame] if box.get("instance") == number]
        return found[0] if found else None

    assert all(abs(box_of(frame)["center"][1] - 9.0) < 0.3 for frame in range(12)), "the track follows the look-alike"
    before = {frame: copy.deepcopy(box_of(frame)) for frame in range(1, 6)}
    size = list(box_of(0)["size"])

    from mapbarber.qt import QtCore
    rows = [editor.box_list.topLevelItem(row) for row in range(editor.box_list.topLevelItemCount())]
    wanted = (8, editor.box_store[8].index(box_of(8)))
    item = next(row for row in rows if tuple(row.data(0, QtCore.Qt.UserRole)) == wanted)
    editor.box_list.setCurrentItem(item)
    session.step("move the box onto the right car", lambda: editor.box_fields[1].setValue(13.0))
    assert box_of(8)["key"] and "score" not in box_of(8)
    assert "Auto-label again" in session.window.statusBar().currentMessage()
    assert "corrected" in editor.box_list.currentItem().text(2)
    session.step("track again from it", lambda: editor.track_again())
    assert "Auto-labeled again" in session.window.statusBar().currentMessage()

    for frame in range(12):
        car, count = layout[frame]
        start = int(editor.frame_starts[frame])
        cls = editor.labels.cls[start:start + count]
        inst = editor.labels.inst[start:start + count]
        if frame >= 6:
            box = box_of(frame)
            assert abs(box["center"][1] - 13.0) < 0.3 and abs(box["center"][0] - car[0]) < 0.3, (frame, box["center"])
            assert np.allclose(box["size"], size, atol=1e-6), "the corrected box keeps its size"
            assert (inst[9000:10500] == number).mean() > 0.97 and (cls[9000:10500] == 10).mean() > 0.97, frame
            assert not (inst[10500:] == number).any() and not cls[10500:].any(), f"frame {frame}: the look-alike keeps labels"
        elif frame > 0:
            assert box_of(frame) == before[frame], f"frame {frame} before the jump changed"
        assert not cls[:9000].any()

    corrected = copy.deepcopy(box_of(8))
    session.step("track everything again", lambda: editor.track_boxes())
    assert box_of(8) == corrected, "a full track leaves corrected boxes alone"
    final = session.snapshot()
    session.walk_history()
    assert session.same(final, session.snapshot()) is None


def test_an_object_labeled_in_a_middle_frame_is_tracked_backwards_and_forwards(session):
    """Labels added in the middle of a sequence: the object is followed back to the first frame with one button
    and on to the last with the other; the box made by hand stays, and each direction leaves the other side alone."""
    folder = session.folder / "middle"
    (folder / "velodyne").mkdir(parents=True)
    rng = np.random.default_rng(17)
    side = rng.integers(0, 3, 1500)
    local = rng.uniform([-2, -0.9, -0.75], [2, 0.9, 0.75], (1500, 3))
    for axis, half in enumerate((2.0, 0.9, 0.75)):
        local[side == axis, axis] = half * rng.choice([-1.0, 1.0], (side == axis).sum())
    road = np.column_stack([rng.uniform(-25, 25, 6000), rng.uniform(0, 20, 6000), np.full(6000, -1.2)])
    centres = [np.array([-7.5 + 1.5 * index, 9.0, -1.2 + 0.35 + 0.75]) for index in range(11)]
    for index, centre in enumerate(centres):
        scan = np.vstack([road, local + centre])
        np.column_stack([scan, np.zeros(len(scan))]).astype("<f4").tofile(str(folder / "velodyne" / f"{index:06d}.bin"))
    (folder / "poses.txt").write_text("1 0 0 0 0 1 0 0 0 0 1 0\n" * 11)
    assert session.window.open(str(folder))
    session.pump(0.3)
    editor = session.editor
    session.step("open", undoable=False)
    session.step("all frames", lambda: editor.timeline.slider.on_range(0, 10), undoable=False)
    middle = int(editor.frame_starts[5])
    editor.select(np.arange(middle + 6000, middle + 7500), "replace")
    editor.set_active(10)
    session.step("label the car in frame 5", lambda: session.trigger("Return"))
    session.step("box it", lambda: editor.class_boxes.click())
    made = [box for box in editor.box_store[5] if box.get("instance")]
    assert len(made) == 1 and made[0]["key"] and not any(editor.box_store.get(index) for index in range(11) if index != 5)
    number = made[0]["instance"]

    def box_of(frame):
        found = [box for box in editor.box_store.get(frame, []) if box.get("instance") == number]
        return found[0] if found else None

    def car_labeled(frame):
        start = int(editor.frame_starts[frame])
        return (editor.labels.inst[start + 6000:start + 7500] == number).mean()

    session.step("track backwards", lambda: editor.track_back())
    assert "◀" in editor.tr("track_back") and all(box_of(frame) is not None for frame in range(5))
    assert all(box_of(frame) is None for frame in range(6, 11)), "tracking backwards leaves the later frames alone"
    assert all(car_labeled(frame) > 0.97 for frame in range(6)) and car_labeled(7) == 0
    for frame in range(5):
        assert np.allclose(box_of(frame)["center"][:2], centres[frame][:2], atol=0.3), frame
    hand_made = copy.deepcopy(box_of(5))
    session.step("track forwards", lambda: editor.track_boxes(1))
    assert all(box_of(frame) is not None for frame in range(11))
    assert all(car_labeled(frame) > 0.97 for frame in range(11))
    assert box_of(5)["center"] == hand_made["center"] and box_of(5)["size"] == hand_made["size"], "the hand-made box stays"
    for frame in range(6, 11):
        assert np.allclose(box_of(frame)["center"][:2], centres[frame][:2], atol=0.3), frame
        assert np.cos(box_of(frame)["yaw"]) > 0.99, "the boxes point the way the car drives"
    final = session.snapshot()
    session.walk_history()
    assert session.same(final, session.snapshot()) is None
