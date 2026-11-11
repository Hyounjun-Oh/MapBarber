"""End-to-end run of the three editors in a real window (needs a display): MAPBARBER_GUI_TESTS=1 pytest."""
import os
import shutil
import time

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("MAPBARBER_GUI_TESTS") != "1", reason="set MAPBARBER_GUI_TESTS=1")

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


@pytest.fixture(scope="module")
def workbench(tmp_path_factory):
    from mapbarber.qt import QtWidgets
    dialogs = []
    for name in ("critical", "warning", "information", "question"):
        setattr(QtWidgets.QMessageBox, name,
                staticmethod(lambda *args, _n=name, **kw: dialogs.append((_n, args[1:3])) or QtWidgets.QMessageBox.Yes))
    from mapbarber.app import launch
    folder = tmp_path_factory.mktemp("gui")
    for name in os.listdir(EXAMPLES):
        shutil.copy(os.path.join(EXAMPLES, name), folder)
    app, window = launch(None, "en")

    def pump(seconds=0.3):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()

    pump(0.5)
    yield window, folder, pump, dialogs
    for editor in window.documents:
        (editor.cloud if hasattr(editor, "cloud") else editor.map).mark_saved()
    window.close()


def vtk_click(viewport, x, y, shift=False):
    x, y = int(x), int(y)
    for name in ("MouseMoveEvent", "LeftButtonPressEvent", "LeftButtonReleaseEvent"):
        viewport.interactor.SetEventInformation(x, y, 0, int(shift))
        getattr(viewport.interactor, name)()


def test_voxel_editor(workbench):
    window, folder, pump, dialogs = workbench
    assert window.open(str(folder / "room.bt"))
    pump()
    editor = window.editor
    assert type(editor).__name__ == "VoxelEditor"
    total = len(editor.map)
    editor.select_islands()
    assert len(editor.selection) > 0
    editor.delete_selection()
    assert len(editor.map) < total
    width, height = editor.viewport.renderer.GetSize()
    window.set_tool("delete")
    hits = [(x, y) for x in range(100, width, 60) for y in range(100, height, 60) if editor.target_cells(x, y) is not None]
    before = len(editor.map)
    vtk_click(editor.viewport, *hits[len(hits) // 2])
    assert len(editor.map) < before
    window.set_tool("add")
    erased = len(editor.map)
    vtk_click(editor.viewport, *hits[len(hits) // 2])
    assert len(editor.map) > erased
    assert window.write(str(folder / "room_out.bt"), None)
    assert not dialogs


def test_cloud_editor(workbench):
    window, folder, pump, dialogs = workbench
    assert window.open(str(folder / "scan.pcd"))
    pump()
    editor = window.editor
    assert type(editor).__name__ == "CloudEditor"
    assert editor.colour_box.findData("intensity") >= 0 and editor.colour_box.findData("rgb") >= 0
    editor.select_outliers()
    selected = len(editor.selection)
    editor.delete_selection()
    assert editor.cloud.removed() == selected > 0
    editor.thin_out()
    editor.undo()
    assert editor.cloud.removed() == selected
    assert window.write(str(folder / "scan_out.pcd"), None)
    from mapbarber import formats
    xyz, table = formats.read_cloud(str(folder / "scan_out.pcd"))
    assert table.dtype.names == ("x", "y", "z", "intensity", "rgb") and len(xyz) == len(editor.cloud)
    assert not dialogs


def test_grid_editor(workbench):
    from mapbarber.qt import QtCore, QtTest
    window, folder, pump, dialogs = workbench
    assert window.open(str(folder / "floor.pgm"))
    pump()
    editor = window.editor
    assert type(editor).__name__ == "GridEditor" and editor.map.origin == (-1.5, -1.5, 0.0)
    occupied = editor.map.counts()[1]
    editor.clear_speckles()
    assert editor.map.counts()[1] < occupied
    canvas = editor.canvas

    def at(row, column):
        return canvas.mapFromScene(QtCore.QPointF(column + 0.5, editor.map.shape[0] - row - 0.5))

    window.set_tool("line")
    editor.brush.setValue(3)
    before = editor.map.counts()[1]
    QtTest.QTest.mousePress(canvas.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, at(151, 330))
    QtTest.QTest.mouseMove(canvas.viewport(), at(151, 352))
    QtTest.QTest.mouseRelease(canvas.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, at(151, 352))
    pump()
    assert editor.map.counts()[1] == before + 66
    editor.trim()
    assert editor.map.shape == (244, 364) and np.allclose(editor.map.origin, (-0.1, -0.1, 0.0))
    editor.undo()
    assert editor.map.shape == (300, 420)
    assert window.write(str(folder / "floor_out.yaml"), None)
    assert (folder / "floor_out.pgm").exists()
    assert not dialogs


def vtk_drag(viewport, start, end, steps=8):
    viewport.interactor.SetEventInformation(int(start[0]), int(start[1]), 0, 0)
    viewport.interactor.LeftButtonPressEvent()
    for t in np.linspace(0, 1, steps + 1)[1:]:
        point = np.asarray(start) + (np.asarray(end) - np.asarray(start)) * t
        viewport.interactor.SetEventInformation(int(point[0]), int(point[1]), 0, 0)
        viewport.interactor.MouseMoveEvent()
    viewport.interactor.LeftButtonReleaseEvent()


def vtk_right_click(viewport, x, y):
    viewport.interactor.SetEventInformation(int(x), int(y), 0, 0)
    viewport.interactor.RightButtonPressEvent()
    viewport.interactor.RightButtonReleaseEvent()


def screen(editor, world):
    return np.array(editor.viewport.to_display(world))


def floor_map():
    from mapbarber.voxels import pack
    cells = np.stack(np.meshgrid(np.arange(20), np.arange(20), [0], indexing="ij"), -1).reshape(-1, 3)
    return pack(cells), 0.1


def test_voxel_ruler_box_handles_slice_and_right_click(workbench):
    from mapbarber.formats import VOXEL
    from mapbarber.voxels import unpack
    window, _folder, pump, dialogs = workbench
    window.show_document(VOXEL, floor_map())
    pump()
    editor = window.editor
    editor.look_from((0, 0, 1), (0, 1, 0))
    pump()

    window.set_tool("measure")
    editor.ruler_snap.setChecked(True)
    vtk_click(editor.viewport, *screen(editor, (0.25, 0.25, 0.1)).astype(int))
    assert editor.ruler.pending
    vtk_click(editor.viewport, *screen(editor, (1.25, 0.25, 0.1)).astype(int))
    assert editor.measurement["d"] == pytest.approx(1.0) and editor.measurement["cells"] == pytest.approx(10.0)
    assert "1.000" in editor.ruler_label.text()
    editor.ruler_snap.setChecked(False)
    vtk_click(editor.viewport, *screen(editor, (0.25, 0.25, 0.1)).astype(int))
    vtk_click(editor.viewport, *screen(editor, (0.25, 1.25, 0.1)).astype(int))
    assert editor.measurement["dz"] == pytest.approx(0.0, abs=1e-9) and 0.9 < editor.measurement["d"] < 1.1

    editor.set_box((0.2, 0.2, -0.1), (0.6, 0.6, 0.3))
    pump()
    length = editor.box_gizmo.length()
    grab = screen(editor, (0.4 + 0.6 * length, 0.4, 0.1))
    per_metre = screen(editor, (1.4, 0.4, 0.1)) - screen(editor, (0.4, 0.4, 0.1))
    vtk_drag(editor.viewport, grab, grab + per_metre * 0.5)
    (x_low, x_high), (y_low, y_high), _ = editor.box.values()
    assert (x_low, x_high) == (pytest.approx(0.7), pytest.approx(1.1))
    assert (y_low, y_high) == (pytest.approx(0.2), pytest.approx(0.6))
    dot = screen(editor, (1.1, 0.4, 0.1))
    vtk_drag(editor.viewport, dot, dot + per_metre * 0.3)
    (x_low, x_high), _, _ = editor.box.values()
    assert (x_low, x_high) == (pytest.approx(0.7), pytest.approx(1.4))

    total = len(editor.map)
    editor.slice.axes.button(0).setChecked(True)
    editor.slice.enabled.setChecked(True)
    assert editor.slice.position.value() == pytest.approx(1.0)
    editor.slice.position.setValue(1.0)
    pump()
    shown = (unpack(editor.visible_keys)[:, 0] + 0.5) * 0.1
    assert shown.max() <= 1.0 and editor.hidden == total - len(editor.visible_keys) > 0
    editor.set_box((0.0, 0.0, 0.1), (2.0, 2.0, 0.2))
    editor.box_fill()
    added = np.setdiff1d(editor.map.occupied, editor.map.saved)
    assert len(added) > 0 and ((unpack(added)[:, 0] + 0.5) * 0.1).max() <= 1.0
    editor.set_box((0.0, 0.0, -0.1), (2.0, 2.0, 0.3))
    editor.box_delete()
    assert len(editor.map) == total - len(np.setdiff1d(editor.map.saved, editor.map.occupied))
    removed = np.setdiff1d(editor.map.saved, editor.map.occupied)
    assert ((unpack(removed)[:, 0] + 0.5) * 0.1).min() >= 0.0 and ((unpack(removed)[:, 0] + 0.5) * 0.1).max() <= 1.0
    editor.undo()
    editor.undo()
    assert not editor.map.dirty

    plane = editor.slice_gizmo.centre()
    grab = screen(editor, plane + np.array([0.6 * editor.slice_gizmo.length(), 0, 0]))
    vtk_drag(editor.viewport, grab, grab - per_metre * 0.4)
    assert editor.slice.position.value() == pytest.approx(0.6)
    editor.restore_view()
    assert not editor.slice.enabled.isChecked() and len(editor.visible_keys) == total

    editor.select_all()
    window.set_tool("view")
    before = len(editor.selection)
    vtk_right_click(editor.viewport, *screen(editor, (1.05, 1.05, 0.1)))
    assert len(editor.selection) == before - 1
    editor.clear_ruler()
    assert not dialogs


def test_cloud_ruler_slice_and_right_click(workbench):
    from mapbarber.formats import CLOUD
    window, _folder, pump, dialogs = workbench
    xy = np.stack(np.meshgrid(np.arange(0, 5.01, 0.5), np.arange(0, 5.01, 0.5), indexing="ij"), -1).reshape(-1, 2)
    xyz = np.column_stack([xy, np.zeros(len(xy))])
    window.show_document(CLOUD, (xyz, None))
    pump()
    editor = window.editor
    editor.look_from((0, 0, 1), (0, 1, 0))
    pump()
    window.set_tool("measure")
    vtk_click(editor.viewport, *screen(editor, (0, 0, 0)).astype(int))
    vtk_click(editor.viewport, *screen(editor, (3, 4, 0)).astype(int))
    assert editor.measurement["d"] == pytest.approx(5.0) and editor.measurement["dx"] == pytest.approx(3.0)

    editor.slice.axes.button(1).setChecked(True)
    editor.slice.keep.setCurrentIndex(1)
    editor.slice.enabled.setChecked(True)
    assert editor.slice.position.value() == pytest.approx(2.5)
    editor.slice.position.setValue(2.4)
    pump()
    assert editor.visible_points[:, 1].min() >= 2.4 and editor.hidden == 11 * 5
    editor.slice.flip()
    pump()
    assert editor.visible_points[:, 1].max() <= 2.4
    editor.restore_view()
    assert len(editor.visible_ids) == len(xyz)

    editor.select_all()
    window.set_tool("view")
    editor.radius.setValue(0.1)
    vtk_right_click(editor.viewport, *screen(editor, (2.5, 2.5, 0)))
    assert len(editor.selection) == len(xyz) - 1
    assert not dialogs


def test_grid_ruler(workbench):
    from mapbarber.formats import GRID
    from mapbarber.grid import FREE, GridMap
    from mapbarber.qt import QtCore, QtTest
    window, _folder, pump, dialogs = workbench
    window.show_document(GRID, GridMap(np.full((60, 80), FREE, np.uint8), 0.05, (1.0, 2.0, np.pi / 2)))
    pump()
    editor = window.editor
    canvas = editor.canvas

    def at(row, column):
        return canvas.mapFromScene(QtCore.QPointF(column + 0.5, editor.map.shape[0] - row - 0.5))

    window.set_tool("measure")
    for cell in ((10, 10), (10, 40)):
        QtTest.QTest.mousePress(canvas.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, at(*cell))
        QtTest.QTest.mouseRelease(canvas.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, at(*cell))
        pump(0.1)
    result = editor.measurement
    assert result["px"] == pytest.approx(30.0) and result["d"] == pytest.approx(1.5)
    assert result["dx"] == pytest.approx(0.0, abs=1e-9) and result["dy"] == pytest.approx(1.5)
    assert (result["dc"], result["dr"]) == (30, 0) and "30.0 px" in editor.ruler_label.text()
    assert not editor.map.dirty and not dialogs


def test_tabs(workbench):
    window, folder, pump, dialogs = workbench
    window.close_all(ask=False)
    pump()
    assert window.stack.currentWidget() is window.welcome and window.editor is None
    for name in ("room.bt", "scan.pcd", "floor.yaml"):
        assert window.open(str(folder / name))
    pump()
    kinds = [type(d).__name__ for d in window.documents]
    assert kinds == ["VoxelEditor", "CloudEditor", "GridEditor"] and window.tabs.count() == 3
    assert window.open(str(folder / "room.bt")) and window.tabs.count() == 3 and window.tabs.currentIndex() == 0
    window.editor.select_islands()
    window.editor.delete_selection()
    pump()
    assert window.tabs.tabText(0).endswith("*")
    window.tabs.setCurrentIndex(1)
    pump()
    assert type(window.editor).__name__ == "CloudEditor" and "Points" in window.counts.text()
    window.tabs.setCurrentIndex(0)
    pump()
    assert window.editor.map.dirty and window.dock.windowTitle() == "Voxel map"
    count = len(dialogs)
    assert window.close_document(window.documents[0])
    assert len(dialogs) == count + 1 and window.tabs.count() == 2
    dialogs.clear()
    window.close_all(ask=False)
    pump()
    assert window.editor is None and window.stack.currentWidget() is window.welcome


def test_standard_shortcuts(workbench):
    from mapbarber.qt import QtGui
    window, folder, pump, dialogs = workbench
    assert window.open(str(folder / "floor.yaml"))
    pump()

    def bound(sequence):
        wanted = QtGui.QKeySequence(sequence)
        return [action.text() for action in window.actions() if wanted in action.shortcuts()]

    def assert_unambiguous():
        seen = {}
        for action in window.actions():
            for sequence in action.shortcuts():
                key = sequence.toString()
                assert key not in seen, (key, seen.get(key), action.text())
                seen[key] = action.text()

    assert_unambiguous()

    expected = {"Ctrl+O": "Open…", "Ctrl+S": "Save", "Ctrl+Shift+S": "Save As / Export…", "Ctrl+Z": "Undo",
                "Ctrl+Shift+Z": "Redo", "Ctrl+Y": "Redo", "Ctrl+W": "Close tab", "Ctrl+Q": "Quit", "Ctrl+Tab": "Next tab",
                "F1": "Controls", "F11": "Full screen", "Ctrl+0": "Fit to window", "H": "Navigate", "B": "Pen",
                "L": "Line", "R": "Rectangle", "G": "Fill", "I": "Measure", "[": "Smaller brush", "]": "Larger brush"}
    for sequence, label in expected.items():
        assert bound(sequence) == [label], (sequence, bound(sequence))
    window.close_all(ask=False)
    assert window.open(str(folder / "room.bt"))
    pump()
    for sequence, label in {"V": "Select", "E": "Erase", "Delete": "Delete selection", "Backspace": "Delete selection",
                            "Ctrl+A": "Select all visible", "Ctrl+Shift+I": "Invert selection", "Ctrl+D": "Clear selection",
                            "Escape": "Clear selection", "7": "Top", "1": "Front", "3": "Side", "Home": "Isometric"}.items():
        assert bound(sequence) == [label], (sequence, bound(sequence))
    assert_unambiguous()
    window.close_all(ask=False)
    assert window.open(str(folder / "scan.pcd"))
    pump()
    assert_unambiguous()
    window.close_all(ask=False)
    assert not dialogs


def test_grid_shift_constraints(workbench):
    from mapbarber.formats import GRID
    from mapbarber.grid import FREE, OCCUPIED, GridMap
    from mapbarber.qt import QtCore, QtTest
    window, _folder, pump, dialogs = workbench
    editor = window.show_document(GRID, GridMap(np.full((80, 80), FREE, np.uint8), 0.05))
    pump()
    canvas, Qt = editor.canvas, QtCore.Qt

    def at(row, column):
        return canvas.mapFromScene(QtCore.QPointF(column + 0.5, editor.map.shape[0] - row - 0.5))

    def drag(start, end, modifiers=Qt.NoModifier):
        QtTest.QTest.mousePress(canvas.viewport(), Qt.LeftButton, modifiers, at(*start))
        event_move(end, modifiers)
        QtTest.QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, modifiers, at(*end))
        pump(0.05)

    def event_move(cell, modifiers):
        from mapbarber.qt import QtGui
        point = QtCore.QPointF(at(*cell))
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, point, point, Qt.NoButton, Qt.LeftButton, modifiers)
        QtWidgets_send(canvas.viewport(), event)

    from mapbarber.qt import QtWidgets
    QtWidgets_send = QtWidgets.QApplication.sendEvent
    editor.brush.setValue(1)
    window.set_tool("line")
    drag((10, 10), (13, 40), Qt.ShiftModifier)
    rows, columns = np.nonzero(editor.map.cells == OCCUPIED)
    assert set(rows) == {10} and (columns.min(), columns.max()) == (10, 40)
    editor.undo()
    window.set_tool("rectangle")
    drag((20, 20), (25, 30), Qt.ShiftModifier)
    rows, columns = np.nonzero(editor.map.cells == OCCUPIED)
    assert (rows.min(), rows.max(), columns.min(), columns.max()) == (20, 30, 20, 30)
    editor.undo()
    drag((40, 40), (42, 45), Qt.AltModifier)
    rows, columns = np.nonzero(editor.map.cells == OCCUPIED)
    assert (rows.min(), rows.max(), columns.min(), columns.max()) == (38, 42, 35, 45)
    editor.undo()
    window.set_tool("pen")
    drag((60, 10), (60, 10))
    drag((60, 50), (60, 50), Qt.ShiftModifier)
    rows, columns = np.nonzero(editor.map.cells == OCCUPIED)
    assert set(rows) == {60} and len(columns) == 41
    window.set_tool("measure")
    for cell, modifiers in (((5, 5), Qt.NoModifier), ((9, 35), Qt.ShiftModifier)):
        QtTest.QTest.mousePress(canvas.viewport(), Qt.LeftButton, modifiers, at(*cell))
        QtTest.QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, modifiers, at(*cell))
    assert editor.measurement["px"] == pytest.approx(30.0) and editor.measurement["dr"] == 0
    editor.map.mark_saved()
    window.close_all(ask=False)
    assert not dialogs


def test_voxel_ruler_shift_locks_axis(workbench):
    from mapbarber.formats import VOXEL
    window, _folder, pump, dialogs = workbench
    editor = window.show_document(VOXEL, floor_map())
    pump()
    editor.look_from((0, 0, 1), (0, 1, 0))
    pump()
    window.set_tool("measure")
    editor.ruler_snap.setChecked(True)
    vtk_click(editor.viewport, *screen(editor, (0.25, 0.25, 0.1)).astype(int))
    vtk_click(editor.viewport, *screen(editor, (1.25, 0.55, 0.1)).astype(int), shift=True)
    assert editor.measurement["d"] == pytest.approx(1.0) and editor.measurement["dy"] == pytest.approx(0.0)
    window.close_all(ask=False)
    assert not dialogs


def test_rectangle_select_is_dense_on_surfaces(workbench):
    from mapbarber.formats import VOXEL
    from mapbarber.voxels import pack, unpack
    window, _folder, pump, dialogs = workbench
    floor = np.stack(np.meshgrid(np.arange(200), np.arange(200), [0], indexing="ij"), -1).reshape(-1, 3)
    wall = np.stack(np.meshgrid(np.arange(200), [199], np.arange(1, 60), indexing="ij"), -1).reshape(-1, 3)
    editor = window.show_document(VOXEL, (pack(np.vstack([floor, wall])), 0.05))
    pump()
    width, height = editor.viewport.renderer.GetSize()
    corners = ((width * 0.3, height * 0.3), (width * 0.7, height * 0.7))
    for zoom in (1.0, 3.0):
        editor.look_from((1, -1, 0.8), (0, 0, 1))
        editor.viewport.zoom(zoom)
        pump(0.1)
        editor.front_only.setChecked(False)
        editor._rectangle(*corners, False)
        everything = len(editor.selection)
        editor.clear_selection()
        editor.front_only.setChecked(True)
        editor._rectangle(*corners, False)
        assert everything > 500 and len(editor.selection) > 0.97 * everything, (zoom, len(editor.selection), everything)
        editor.clear_selection()
    near = np.stack(np.meshgrid(np.arange(200), [100], np.arange(1, 60), indexing="ij"), -1).reshape(-1, 3)
    editor.edit(add=pack(near))
    editor.look_from((0, -1, 0), (0, 0, 1))
    pump(0.1)
    editor._rectangle((0, 0), (width, height), False)
    rows = unpack(editor.selection)
    front, back = (rows[:, 1] == 100).sum(), ((rows[:, 1] == 199) & (rows[:, 2] > 0)).sum()
    assert front > 0.97 * len(near) and back < 0.05 * len(wall), (front, back)
    editor.map.mark_saved()
    window.close_all(ask=False)
    assert not dialogs


def test_cloud_rectangle_select_is_dense(workbench):
    from mapbarber.formats import CLOUD
    window, _folder, pump, dialogs = workbench
    xy = np.stack(np.meshgrid(np.arange(0, 10, 0.02), np.arange(0, 10, 0.02), indexing="ij"), -1).reshape(-1, 2)
    editor = window.show_document(CLOUD, (np.column_stack([xy, np.zeros(len(xy))]), None))
    pump()
    width, height = editor.viewport.renderer.GetSize()
    corners = ((width * 0.3, height * 0.3), (width * 0.7, height * 0.7))
    counts = []
    for front in (False, True):
        editor.front_only.setChecked(front)
        editor._rectangle(*corners, False)
        counts.append(len(editor.selection))
        editor.clear_selection()
    assert counts[0] > 5000 and counts[1] > 0.97 * counts[0], counts
    window.close_all(ask=False)
    assert not dialogs


def test_wheel_scrolls_the_panel_unless_a_field_was_clicked(workbench):
    from mapbarber.formats import VOXEL
    from mapbarber.qt import QtCore, QtGui, QtTest, QtWidgets
    window, _folder, pump, dialogs = workbench
    editor = window.show_document(VOXEL, floor_map())
    size = window.size()
    window.resize(1200, 480)
    pump()
    bar = window.dock.widget().verticalScrollBar()
    assert bar.maximum() > 0

    def wheel(box, delta=-120):
        target = box.findChild(QtWidgets.QLineEdit) or box
        centre = target.rect().center()
        event = QtGui.QWheelEvent(QtCore.QPointF(centre), QtCore.QPointF(target.mapToGlobal(centre)), QtCore.QPoint(0, 0),
                                  QtCore.QPoint(0, delta), QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
                                  QtCore.Qt.NoScrollPhase, False)
        QtWidgets.QApplication.sendEvent(target, event)
        pump(0.05)

    for box in (editor.brush, editor.plane, editor.tolerance):
        bar.setValue(0)
        value = box.value()
        wheel(box)
        assert box.value() == value and bar.value() > 0, box

    bar.setValue(0)
    box = editor.plane
    QtTest.QTest.mouseClick(box.findChild(QtWidgets.QLineEdit), QtCore.Qt.LeftButton)
    pump(0.05)
    value = box.value()
    wheel(box, 120)
    assert box.value() > value and bar.value() == 0
    other = editor.brush.value()
    wheel(editor.brush)
    assert editor.brush.value() == other and bar.value() > 0

    QtWidgets.QApplication.sendEvent(box, QtCore.QEvent(QtCore.QEvent.Leave))
    bar.setValue(0)
    value = box.value()
    wheel(box, 120)
    wheel(box, -120)
    assert box.value() == value and bar.value() > 0
    window.resize(size)
    window.close_all(ask=False)
    assert not dialogs


def test_ruler_highlights_what_is_under_the_cursor(workbench):
    from mapbarber.formats import CLOUD, VOXEL
    window, _folder, pump, dialogs = workbench
    editor = window.show_document(VOXEL, floor_map())
    pump()
    editor.look_from((0, 0, 1), (0, 1, 0))
    window.set_tool("measure")
    spot = screen(editor, (0.75, 0.75, 0.1)).astype(int)
    editor.viewport.interactor.SetEventInformation(int(spot[0]), int(spot[1]), 0, 0)
    editor.viewport.interactor.MouseMoveEvent()
    bounds = editor.hover_source.GetBounds()
    assert editor.hover_actor.GetVisibility() and bounds[0] < 0.75 < bounds[1] and bounds[1] - bounds[0] < 0.12
    editor.viewport.interactor.SetEventInformation(2, 2, 0, 0)
    editor.viewport.interactor.MouseMoveEvent()
    assert not editor.hover_actor.GetVisibility()
    xy = np.stack(np.meshgrid(np.arange(0, 3.01, 0.5), np.arange(0, 3.01, 0.5), indexing="ij"), -1).reshape(-1, 2)
    cloud = window.show_document(CLOUD, (np.column_stack([xy, np.zeros(len(xy))]), None))
    pump()
    cloud.look_from((0, 0, 1), (0, 1, 0))
    window.set_tool("measure")
    spot = screen(cloud, (1.5, 1.0, 0.0)).astype(int)
    cloud.viewport.interactor.SetEventInformation(int(spot[0]), int(spot[1]), 0, 0)
    cloud.viewport.interactor.MouseMoveEvent()
    assert cloud.hover_actor.GetVisibility() and np.allclose(cloud.hover_source.GetCenter(), (1.5, 1.0, 0.0))
    window.close_all(ask=False)
    assert not dialogs


def test_ruler_shows_axis_offsets(workbench):
    from mapbarber.formats import GRID, VOXEL
    from mapbarber.grid import FREE, GridMap
    window, _folder, pump, dialogs = workbench
    editor = window.show_document(VOXEL, floor_map())
    pump()
    editor.look_from((0, 0, 1), (0, 1, 0))
    window.set_tool("measure")
    editor.ruler_snap.setChecked(True)
    vtk_click(editor.viewport, *screen(editor, (0.25, 0.25, 0.1)))
    vtk_click(editor.viewport, *screen(editor, (1.25, 0.75, 0.1)))
    shown = [bool(actor.GetVisibility()) for _, actor, _ in editor.ruler.legs]
    assert shown == [True, True, False]
    x_leg, y_leg = editor.ruler.legs[0][0], editor.ruler.legs[1][0]
    assert np.allclose(x_leg.GetPoint2(), (1.25, 0.25, 0.05)) and np.allclose(y_leg.GetPoint2(), (1.25, 0.75, 0.05))
    assert editor.ruler.legs[0][2].GetInput() == "dx +1.000"
    vtk_click(editor.viewport, *screen(editor, (0.25, 0.25, 0.1)))
    vtk_click(editor.viewport, *screen(editor, (1.25, 0.25, 0.1)))
    assert not any(actor.GetVisibility() for _, actor, _ in editor.ruler.legs)

    grid_editor = window.show_document(GRID, GridMap(np.full((60, 80), FREE, np.uint8), 0.05))
    pump()
    window.set_tool("measure")
    grid_editor._measure_press(10, 10)
    grid_editor._measure_press(30, 50)
    assert all(leg.isVisible() for leg, _, _ in grid_editor.ruler_legs)
    assert "+2.000" in grid_editor.ruler_legs[0][1].toPlainText() and "+1.000" in grid_editor.ruler_legs[1][1].toPlainText()
    grid_editor.clear_ruler()
    assert not any(leg.isVisible() for leg, _, _ in grid_editor.ruler_legs)
    window.close_all(ask=False)
    assert not dialogs


def test_measurements_accumulate_in_the_corner_overlay(workbench):
    from mapbarber.formats import GRID, VOXEL
    from mapbarber.grid import FREE, GridMap
    window, _folder, pump, dialogs = workbench
    editor = window.show_document(VOXEL, floor_map())
    pump()
    editor.look_from((0, 0, 1), (0, 1, 0))
    window.set_tool("measure")
    editor.ruler_snap.setChecked(True)
    overlay = editor.overlay
    assert not overlay.isVisible()
    for end in ((1.25, 0.25), (0.25, 1.75), (1.25, 0.75)):
        vtk_click(editor.viewport, *screen(editor, (0.25, 0.25, 0.1)))
        vtk_click(editor.viewport, *screen(editor, (*end, 0.1)))
    pump(0.1)
    assert overlay.isVisible() and len(overlay.entries) == 3
    assert [overlay.tabs.tabText(i) for i in range(overlay.tabs.count())] == ["Σ", "1", "2", "3"]
    assert overlay.tabs.currentIndex() == 3 and "1.118" in overlay.text.text()
    right_edge = overlay.x() + overlay.width()
    assert editor.widget.width() - right_edge == 12 and overlay.y() == 12

    overlay.tabs.setCurrentIndex(2)
    assert "1.500" in overlay.text.text() and editor.measurement["d"] == pytest.approx(1.5)
    assert np.allclose(editor.ruler.second, (0.25, 1.75, 0.05))
    overlay.tabs.setCurrentIndex(0)
    assert "#1   1.000 m" in overlay.text.text() and "3.618" in overlay.text.text() and not overlay.schematic.isVisible()
    assert overlay.total() == pytest.approx(1.0 + 1.5 + 1.25 ** 0.5)
    overlay.tabs.tabCloseRequested.emit(1)
    assert len(overlay.entries) == 2 and overlay.total() == pytest.approx(1.5 + 1.25 ** 0.5)
    window.set_language("ko")
    assert "합계" in overlay.text.text() or overlay.tabs.currentIndex() != 0
    window.set_language("en")
    editor = window.editor
    editor.clear_ruler()
    assert not editor.overlay.isVisible() and not editor.overlay.entries

    grid_editor = window.show_document(GRID, GridMap(np.full((60, 80), FREE, np.uint8), 0.05))
    pump()
    window.set_tool("measure")
    for start, end in (((10, 10), (10, 50)), ((10, 10), (40, 10))):
        grid_editor._measure_press(*start)
        grid_editor._measure_press(*end)
    assert len(grid_editor.overlay.entries) == 2 and grid_editor.overlay.total() == pytest.approx(3.5)
    grid_editor.overlay.tabs.setCurrentIndex(1)
    assert grid_editor.measurement["px"] == pytest.approx(40.0) and grid_editor.ruler_line.isVisible()
    window.close_all(ask=False)
    assert not dialogs
