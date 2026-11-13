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
    window.ask_losses = lambda fmt, lines: window.answered_losses.append((fmt, lines)) or True
    window.answered_losses = []

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
    for sequence, label in {"V": "Select", "E": "Erase", "Delete": "Delete selection", "Backspace": "Undo last selection step",
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


def test_far_chunks_are_drawn_coarser_and_edits_touch_few_chunks(workbench):
    from mapbarber.formats import VOXEL
    from mapbarber.voxels import pack
    window, _folder, pump, dialogs = workbench
    floor = np.stack(np.meshgrid(np.arange(600), np.arange(600), [0, 1], indexing="ij"), -1).reshape(-1, 3)
    editor = window.show_document(VOXEL, (pack(floor), 0.05))
    pump(0.4)
    editor.update_levels()
    editor.finish_levels()
    assert len(editor.map.chunks) == 100 and editor.visible_count == len(floor)
    assert editor.view.drawn() < len(floor) / 3 and max(editor.view.levels.values()) >= 1
    editor.viewport.zoom(12.0)
    editor.update_levels()
    editor.finish_levels()
    assert min(editor.view.levels.values()) == 0
    cached = editor.view.cached
    editor.viewport.zoom(1 / 12.0)
    editor.update_levels()
    assert not editor._pending and editor.view.cached == cached
    editor.viewport.zoom(12.0)
    editor.update_levels()
    assert not editor._pending and min(editor.view.levels.values()) == 0
    width, height = editor.viewport.renderer.GetSize()
    window.set_tool("delete")
    cells = editor.target_cells(width // 2, height // 2)
    assert cells is not None and len(cells) == 1
    editor._click(width // 2, height // 2, False)
    assert editor.map.changes() == (0, 1) and len(editor.map.touched) == 1
    editor.undo()
    assert not editor.map.dirty and editor.visible_count == len(floor)
    window.close_all(ask=False)
    assert not dialogs


def test_backspace_steps_the_selection_back(workbench):
    from mapbarber.formats import CLOUD, VOXEL
    window, _folder, pump, dialogs = workbench
    editor = window.show_document(VOXEL, floor_map())
    pump()
    editor.look_from((0, 0, 1), (0, 1, 0))
    window.set_tool("select")
    for x in (0.25, 0.75, 1.25):
        vtk_click(editor.viewport, *screen(editor, (x, 0.25, 0.1)))
    assert len(editor.selected) == 3
    back = next(action for action in window.actions() if action.text() == "Undo last selection step")
    back.trigger()
    assert len(editor.selected) == 2
    editor.select_all()
    assert len(editor.selected) == 400
    back.trigger()
    assert len(editor.selected) == 2
    back.trigger()
    back.trigger()
    back.trigger()
    assert len(editor.selected) == 0 and not editor.map.dirty

    xy = np.stack(np.meshgrid(np.arange(0, 3.01, 0.5), np.arange(0, 3.01, 0.5), indexing="ij"), -1).reshape(-1, 2)
    cloud = window.show_document(CLOUD, (np.column_stack([xy, np.zeros(len(xy))]), None))
    pump()
    cloud.look_from((0, 0, 1), (0, 1, 0))
    window.set_tool("select")
    cloud.radius.setValue(0.1)
    spot = screen(cloud, (1.0, 1.0, 0.0)).astype(int)
    cloud.viewport.interactor.SetEventInformation(int(spot[0]), int(spot[1]), 0, 0)
    cloud.viewport.interactor.MouseMoveEvent()
    assert cloud.preview_actor.GetVisibility() and cloud.preview.GetNumberOfPoints() == 1
    for x in (0.5, 1.0, 1.5):
        vtk_click(cloud.viewport, *screen(cloud, (x, 1.0, 0.0)))
    assert len(cloud.selection) == 3
    cloud.selection_back()
    assert len(cloud.selection) == 2
    window.close_all(ask=False)
    assert not dialogs


def vtk_stroke(viewport, points, ctrl=True):
    first = points[0]
    viewport.interactor.SetEventInformation(int(first[0]), int(first[1]), int(ctrl), 0)
    viewport.interactor.LeftButtonPressEvent()
    for point in points[1:]:
        viewport.interactor.SetEventInformation(int(point[0]), int(point[1]), int(ctrl), 0)
        viewport.interactor.MouseMoveEvent()
    viewport.interactor.LeftButtonReleaseEvent()


def test_ctrl_drag_paints_without_moving_the_view(workbench):
    from mapbarber.formats import CLOUD, VOXEL
    window, _folder, pump, dialogs = workbench
    editor = window.show_document(VOXEL, floor_map())
    pump()
    editor.look_from((0, 0, 1), (0, 1, 0))
    camera = editor.viewport.renderer.GetActiveCamera()
    position = camera.GetPosition()
    window.set_tool("select")
    path = [screen(editor, (x, 0.55, 0.1)) for x in np.arange(0.25, 1.26, 0.05)]
    vtk_stroke(editor.viewport, path)
    assert camera.GetPosition() == position
    assert len(editor.selected) == 11 and len(editor._selection_steps) == 1
    editor.selection_back()
    assert len(editor.selected) == 0
    window.set_tool("delete")
    vtk_stroke(editor.viewport, path)
    assert editor.map.changes() == (0, 11) and editor.map.undo_depth() == 1
    editor.undo()
    assert not editor.map.dirty
    vtk_stroke(editor.viewport, path, ctrl=False)
    assert not editor.map.dirty and camera.GetPosition() != position

    xy = np.stack(np.meshgrid(np.arange(0, 3.01, 0.25), np.arange(0, 3.01, 0.25), indexing="ij"), -1).reshape(-1, 2)
    cloud = window.show_document(CLOUD, (np.column_stack([xy, np.zeros(len(xy))]), None))
    pump()
    cloud.look_from((0, 0, 1), (0, 1, 0))
    cloud.radius.setValue(0.05)
    window.set_tool("select")
    path = [screen(cloud, (x, 1.0, 0.0)) for x in np.arange(0.5, 2.01, 0.125)]
    vtk_stroke(cloud.viewport, path)
    assert len(cloud.selection) == 7 and len(cloud._selection_steps) == 1
    window.set_tool("delete")
    vtk_stroke(cloud.viewport, path)
    assert cloud.cloud.removed() == 7 and cloud.cloud.undo_depth() == 1
    cloud.undo()
    assert not cloud.cloud.dirty
    window.close_all(ask=False)
    assert not dialogs


def test_large_cloud_is_thinned_far_away_and_edits_touch_few_chunks(workbench):
    from mapbarber.formats import CLOUD
    window, _folder, pump, dialogs = workbench
    rng = np.random.default_rng(4)
    xyz = np.column_stack([rng.uniform(0, 40, 600_000), rng.uniform(0, 40, 600_000), rng.normal(0, 0.01, 600_000)])
    editor = window.show_document(CLOUD, (xyz, None))
    pump(0.4)
    editor.finish_levels()
    assert len(editor.chunks) > 20 and editor.visible_count == len(xyz)
    editor.viewport.zoom(0.1)
    editor.update_levels()
    editor.finish_levels()
    assert editor.view.drawn() < len(xyz) / 4 and max(editor.view.levels.values()) >= 1
    editor.viewport.zoom(150.0)
    editor.update_levels()
    editor.finish_levels()
    assert min(editor.view.levels.values()) == 0
    width, height = editor.viewport.renderer.GetSize()
    window.set_tool("delete")
    editor.radius.setValue(0.2)
    centre = editor._pick(width // 2, height // 2)
    assert centre is not None
    expected = int((np.linalg.norm(xyz - centre, axis=1) <= 0.2).sum())
    editor._click(width // 2, height // 2, False)
    assert editor.cloud.removed() == expected > 0
    assert len(editor.chunks.touched(editor.cloud.touched)) <= 8
    editor.undo()
    assert not editor.cloud.dirty and editor.visible_count == len(xyz)
    editor.select_all()
    assert int(editor.selected.sum()) == len(xyz)
    editor.selection_back()
    assert not editor.selected.any()
    window.close_all(ask=False)
    assert not dialogs


def test_conversions_between_cloud_and_voxels_lose_nothing(workbench):
    import mapbarber.cloud_editor as cloud_editor
    window, folder, pump, dialogs = workbench
    asked = []
    original_ask = cloud_editor.ask_numbers
    cloud_editor.ask_numbers = lambda parent, title, fields: asked.append(fields[0][1]) or [field[1] for field in fields]
    try:
        assert window.open(str(folder / "scan.pcd"))
        pump()
        source = window.editor
        xyz, table = source.cloud.surviving()
        window.convert(source.to_voxels)
        voxels = window.editor
        size = voxels.map.resolution
        window.convert(voxels.to_cloud)
        restored = window.editor
        back_xyz, back_table = restored.cloud.surviving()
        assert np.array_equal(back_xyz, xyz) and np.array_equal(back_table, table)
        window.convert(restored.to_voxels)
        assert asked[-1] == size and np.array_equal(window.editor.map.occupied, voxels.map.occupied)

        assert window.open(str(folder / "room.bt"))
        pump()
        first = window.editor
        window.convert(first.to_cloud)
        window.convert(window.editor.to_voxels)
        assert asked[-1] == first.map.resolution and np.array_equal(window.editor.map.occupied, first.map.occupied)
    finally:
        cloud_editor.ask_numbers = original_ask
    for document in window.documents:
        (document.cloud if hasattr(document, "cloud") else document.map).mark_saved()
    window.close_all(ask=False)
    assert not dialogs


def test_slice_plane_can_be_tilted(workbench):
    from mapbarber.formats import CLOUD, VOXEL
    from mapbarber.voxels import unpack
    window, _folder, pump, dialogs = workbench
    editor = window.show_document(VOXEL, floor_map())
    pump()
    editor.slice.axes.button(0).click()
    editor.slice.enabled.setChecked(True)
    assert editor.slice.position.value() == pytest.approx(1.0)
    upright = len(editor.visible_keys)
    editor.slice.tilts[1].setValue(45.0)
    pump()
    assert [label.text() for label in editor.slice.tilt_labels] == ["Tilt about Y [°]", "Tilt about Z [°]"]
    centres = (unpack(editor.visible_keys) + 0.5) * 0.1
    assert len(centres) and (centres[:, 0] + centres[:, 1] <= 2.0 + 1e-6).all()
    assert abs(len(centres) - upright) <= 20 and editor.hidden == 400 - len(centres)
    assert np.allclose(editor.slice_gizmo.normal, (0.5 ** 0.5, 0.5 ** 0.5, 0.0))
    total = len(editor.map)
    editor.select_all()
    editor.delete_selection()
    assert len(editor.map) == total - len(centres)
    editor.undo()
    editor.restore_view()
    assert len(editor.visible_keys) == total

    xy = np.stack(np.meshgrid(np.arange(0, 4.01, 0.25), np.arange(0, 4.01, 0.25), indexing="ij"), -1).reshape(-1, 2)
    cloud = window.show_document(CLOUD, (np.column_stack([xy, np.zeros(len(xy))]), None))
    pump()
    cloud.slice.axes.button(0).click()
    cloud.slice.enabled.setChecked(True)
    cloud.slice.tilts[1].setValue(45.0)
    pump()
    shown = cloud.visible_points
    assert 0 < len(shown) < len(xy) and (shown[:, 0] + shown[:, 1] <= 4.0 + 1e-6).all()
    window.close_all(ask=False)
    assert not dialogs


def test_grid_zoom_keeps_the_point_under_the_cursor(workbench):
    from mapbarber.formats import GRID
    from mapbarber.grid import FREE, GridMap
    from mapbarber.qt import QtCore, QtGui, QtWidgets
    window, _folder, pump, dialogs = workbench
    editor = window.show_document(GRID, GridMap(np.full((300, 400), FREE, np.uint8), 0.05))
    pump()
    canvas = editor.canvas
    for spot in (QtCore.QPoint(40, 30), QtCore.QPoint(canvas.viewport().width() - 30, canvas.viewport().height() - 40)):
        for delta in (120, 120, 120, 120, -120, -120, 120):
            before = canvas.mapToScene(spot)
            scale = canvas.transform().m11()
            event = QtGui.QWheelEvent(QtCore.QPointF(spot), QtCore.QPointF(canvas.viewport().mapToGlobal(spot)),
                                      QtCore.QPoint(0, 0), QtCore.QPoint(0, delta), QtCore.Qt.NoButton,
                                      QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
            QtWidgets.QApplication.sendEvent(canvas.viewport(), event)
            pump(0.02)
            after = canvas.mapToScene(spot)
            assert canvas.transform().m11() != scale
            assert abs(after.x() - before.x()) < 1.5 / scale and abs(after.y() - before.y()) < 1.5 / scale
    centre = canvas.viewport().rect().center()
    before = canvas.mapToScene(centre)
    editor.zoom(2.0)
    after = canvas.mapToScene(centre)
    assert abs(after.x() - before.x()) < 1.0 and abs(after.y() - before.y()) < 1.0
    window.close_all(ask=False)
    assert not dialogs


def test_saving_warns_once_about_what_the_format_cannot_hold(workbench, monkeypatch):
    from mapbarber import octree
    from mapbarber.voxels import OFFSET, pack
    window, folder, pump, dialogs = workbench
    source, flat = str(folder / "graded.ot"), str(folder / "graded_flat.bt")
    cells = np.array([[0, 0, 0], [1, 0, 0], [6, 6, 6]])
    leaves = octree.Leaves(octree.morton_encode(cells + OFFSET), np.zeros(3, np.int64), np.array([0.4, 2.0, -1.0]),
                           np.array([[9, 8, 7], [1, 2, 3], [0, 0, 0]], np.uint8), "ColorOcTree")
    octree.write_ot(source, pack(cells[:2]), 0.1, leaves)
    asked, answer = [], [False]
    monkeypatch.setattr(window, "ask_losses", lambda fmt, lines: asked.append((fmt, lines)) or answer[0])
    assert window.open(source)
    pump()
    editor = window.editor
    editor.map.apply(add=pack(np.array([[3, 3, 3]])))
    assert window.save() and not asked
    kept = octree.read(source, "ot")[2]
    assert kept.tree_id == "ColorOcTree" and int(kept.free.sum()) == 1 and [9, 8, 7] in kept.colours.tolist()

    assert not window.write(flat, None) and not os.path.exists(flat)
    assert asked[0][0] == "bt" and len(asked[0][1]) == 2
    answer[0] = True
    assert window.write(flat, None) and window.write(flat, None)
    assert len(asked) == 2
    keys, _, written = octree.read(flat, "bt")
    assert len(keys) == 3 and int(written.free.sum()) == 1
    window.close_document(editor, ask=False)


def unambiguous(window):
    seen = {}
    for action in window.actions():
        for sequence in action.shortcuts():
            key = sequence.toString()
            assert key not in seen, (key, seen.get(key), action.text())
            seen[key] = action.text()


def labelled_scene():
    """Floor (class 1), wall (2) and a box floating apart (3)."""
    rng = np.random.default_rng(0)
    floor = np.column_stack([rng.uniform(0, 4, 4000), rng.uniform(0, 4, 4000), rng.normal(0, 0.004, 4000)])
    wall = np.column_stack([rng.uniform(0, 4, 3000), rng.normal(4.0, 0.004, 3000), rng.uniform(0, 2, 3000)])
    box = rng.uniform(0, 0.4, (1500, 3)) + [1.5, 1.5, 0.6]
    return np.vstack([floor, wall, box]), np.repeat([1, 2, 3], [4000, 3000, 1500])


def test_labelling_a_cloud(workbench):
    from mapbarber import formats
    from mapbarber.qt import QtCore
    window, folder, pump, dialogs = workbench
    points, truth = labelled_scene()
    path = folder / "scene.pcd"
    formats.save_cloud(str(path), points)
    assert window.open(str(path))
    pump()
    editor = window.editor
    assert not editor.label_mode and [name for name, _ in editor.tools] == ["view", "select", "delete", "measure"]
    colour_before = editor.colour_box.currentData()
    window.set_tool("delete")
    window.set_label_mode(True)
    unambiguous(window)
    assert editor.label_mode and editor.tool == "label" and window.label_action.isChecked()
    assert [name for name, _ in editor.tools] == ["view", "select", "label", "smart", "measure"]
    assert editor.colour_box.currentData() == "label"
    assert editor.classes.numbers()[:3] == [1, 2, 3] and editor.class_list.topLevelItemCount() == 10
    assert editor.rule_box.currentData() == "unlabeled"

    window.set_tool("smart")
    editor.smart_box.setCurrentIndex(editor.smart_box.findData("plane"))
    floor = editor.smart_ids(np.array([2.0, 2.0, 0.0]))
    assert len(floor) > 3800 and (truth[floor] == 1).mean() > 0.97
    editor.select(floor, "replace")
    from mapbarber.qt import QtGui
    wanted = QtGui.QKeySequence("Ctrl+1")
    next(action for action in window.actions() if wanted in action.shortcuts()).trigger()
    pump()
    assert (editor.labels.cls[floor] == 1).all() and not editor.selected.any()
    assert editor.colour_box.currentData() == "label" and editor.active_class == 1

    editor.smart_box.setCurrentIndex(editor.smart_box.findData("object"))
    editor.at_once.setChecked(True)
    editor.set_active(3)
    box = np.flatnonzero(truth == 3)
    editor.look_from((1, -1, 0.8), (0, 0, 1))
    pump()
    target = points[box][np.argmax(points[box][:, 2])]
    editor._smart_click(*screen(editor, target), False)
    pump()
    assert (editor.labels.cls[box] == 3).all() and set(editor.labels.cls[editor.labels.cls == 3].tolist()) == {3}
    assert (editor.labels.cls == 3).sum() == 1500

    editor.rule_box.setCurrentIndex(editor.rule_box.findData("unlabeled"))
    editor.select(np.arange(len(points)), "replace")
    editor.assign_selection(2)
    assert (editor.labels.cls[floor] == 1).all() and (editor.labels.cls[box] == 3).all()
    wall = np.setdiff1d(np.flatnonzero(truth == 2), floor)
    assert (editor.labels.cls[wall] == 2).all()
    editor.undo()
    assert (editor.labels.cls[wall] == 0).all()
    editor.redo()
    editor.rule_box.setCurrentIndex(editor.rule_box.findData("all"))

    editor.toggle_all_classes(2)
    assert editor.hidden_classes == set([0] + editor.classes.numbers()) and editor.visible_count == 0
    editor.toggle_all_classes(2)
    assert editor.hidden_classes == set() and editor.visible_count == len(points)
    editor.toggle_all_classes(3)
    assert editor.locked_classes == set([0] + editor.classes.numbers())
    assert editor.class_list.topLevelItem(4).checkState(3) == QtCore.Qt.Checked
    editor.toggle_all_classes(3)
    assert editor.locked_classes == set()
    locked = editor.class_list.topLevelItem(1)
    locked.setCheckState(3, QtCore.Qt.Checked)
    editor.select(floor[:10], "replace")
    editor.assign_selection(3)
    assert (editor.labels.cls[floor[:10]] == 1).all()
    locked.setCheckState(3, QtCore.Qt.Unchecked)
    editor.class_list.topLevelItem(1).setCheckState(2, QtCore.Qt.Unchecked)
    assert editor.visible_count == len(points) - len(floor)
    editor.select_all()
    assert not editor.selected[floor].any()
    editor.clear_selection()
    editor.solo_class()
    editor.solo_class()
    assert editor.hidden_classes == set() and editor.visible_count == len(points)

    inner = floor[(truth[floor] == 1) & (points[floor, 1] < 3.5)]
    wrong = inner[::97]
    editor.labels.assign(wrong, 3)
    editor.select_disagreeing()
    assert set(wrong.tolist()) <= set(editor.selection.tolist())
    editor.labels.assign(wrong, 0)
    editor.fill_gaps()
    assert editor.labels.pending[wrong].all() and (editor.labels.cls[wrong] == 1).all()
    editor.confirm_pending()
    assert not editor.labels.pending.any()
    editor.clear_selection()
    editor.next_unlabeled()
    assert not editor.selected.any()

    window.set_label_mode(False)
    assert not editor.label_bar.isVisible() and not editor.timeline.isVisible()
    assert editor.tool == "delete" and editor.colour_box.currentData() == colour_before
    assert window.tool_actions["delete"].isChecked() and not window.label_action.isChecked()
    editor.remove(box[:100], "erase")
    editor.undo()
    assert editor.cloud.alive.all() and (editor.labels.cls[box] == 3).all()
    editor.undo()
    assert editor.labels.pending[wrong].all()
    window.set_label_mode(True)
    assert editor.colour_box.currentData() == "label" and editor.rule_box.currentData() == "all"

    editor.labels.confirm()
    editor.set_active(3)
    editor.split_instances()
    assert editor.labels.inst[box].min() > 0 and len(np.unique(editor.labels.inst[box])) == 1
    assert window.save()
    xyz, table = formats.read_cloud(str(path))
    cls, inst = formats.table_labels(table)
    assert cls.tolist() == editor.labels.cls.tolist() and inst.tolist() == editor.labels.inst.tolist()
    assert (folder / "scene.pcd.labels.yaml").is_file() and not editor.dirty

    window.close_document(editor, ask=False)
    assert window.open(str(path))
    pump()
    again = window.editor
    assert again.labels.cls.tolist() == cls.tolist() and not again.label_mode
    window.set_label_mode(True)
    assert again.colour_box.currentData() == "label"
    again.labels.assign([0], 2)
    again._order.append("label")
    again.save_labels_only()
    assert formats.read_label_file(str(path) + ".labels.npz")[0][0] == 2
    assert formats.table_labels(formats.read_cloud(str(path))[1])[0][0] == cls[0] and not again.dirty
    window.close_all(ask=False)
    assert not dialogs


def test_labelling_frames(workbench):
    from mapbarber import formats
    window, folder, pump, dialogs = workbench
    sequence = folder / "drive"
    (sequence / "velodyne").mkdir(parents=True)
    rng = np.random.default_rng(1)
    wall = np.column_stack([rng.uniform(0, 10, 500), np.full(500, 5.0), rng.uniform(0, 2, 500)])
    poses = []
    for index in range(5):
        walker = np.column_stack([np.full(40, 2.0 + index), rng.uniform(2, 2.4, 40), rng.uniform(0, 1.7, 40)])
        scan = np.vstack([wall, walker]) - [index, 0, 0]
        np.column_stack([scan, np.zeros(len(scan))]).astype("<f4").tofile(str(sequence / "velodyne" / f"{index:06d}.bin"))
        poses.append(f"1 0 0 {index} 0 1 0 0 0 0 1 0")
    (sequence / "poses.txt").write_text("\n".join(poses) + "\n")

    assert window.open(str(sequence))
    pump()
    editor = window.editor
    unambiguous(window)
    assert editor.frame_ids == [0] and len(editor.cloud.xyz) == 540 and editor.frame_list.count() == 5
    assert editor.timeline.isVisible() and editor.label_bar.isVisible()
    assert "1 of 5" in editor.timeline.caption.text()
    editor.timeline.slider.on_range(1, 3)
    assert editor.frame_ids == [1, 2, 3] and editor.timeline.slider.first == 1 and editor.timeline.slider.last == 3
    editor.step_frame(1)
    assert editor.frame_ids == [2, 3, 4] and "3 of 5" in editor.timeline.caption.text()
    editor.show_frames([0])
    assert editor.label_bar.protect.isChecked() and editor.protecting()
    editor.label_bar.protect.click()
    assert not editor.protecting() and editor.rule_box.currentData() == "all"
    editor.toggle_protect()
    assert editor.label_bar.protect.isChecked() and "ON" in editor.label_bar.protect.text()
    for row in (0, 2):
        editor.frame_list.item(row).setSelected(True)
    editor.show_selected_frames()
    assert editor.frame_ids == [0, 2] and len(editor.cloud.xyz) == 1080
    assert np.allclose(editor.cloud.xyz[:500], wall, atol=1e-4) and np.allclose(editor.cloud.xyz[540:1040], wall, atol=1e-4)

    editor.select(np.r_[0:500, 540:1040], "replace")
    editor.assign_selection(50)
    editor.paint_frame.setCurrentIndex(editor.paint_frame.findData(2))
    editor.select(np.arange(1080), "replace")
    editor.set_active(30)
    editor.rule_box.setCurrentIndex(editor.rule_box.findData("unlabeled"))
    editor.assign_selection()
    assert (editor.labels.cls[500:540] == 0).all() and (editor.labels.cls[1040:] == 30).all()
    editor.rule_box.setCurrentIndex(editor.rule_box.findData("all"))
    editor.paint_frame.setCurrentIndex(0)
    assert editor.label_mode and not window.label_action.isEnabled() and "delete" not in dict(editor.tools)
    editor.remove([0], "erase")
    assert editor.cloud.alive.all()

    editor.propagate_frames()
    pump()
    for index in (1, 3, 4):
        cls, _, pending = editor.frame_store[index]
        assert (cls[:500] == 50).all() and pending[:500].all() and (cls[500:] == 0).all()
    editor.step_frame(1)
    assert editor.frame_ids == [1, 3] and editor.labels.pending[:500].all()
    editor.confirm_pending()
    editor.labels.assign([5], 30)
    editor._order.append("label")
    editor.select_conflicts()
    assert 5 in editor.selection.tolist()
    editor.labels.assign([5], 50)

    assert window.save()
    labels_dir = sequence / "labels"
    assert sorted(p.name for p in labels_dir.iterdir()) == [f"{i:06d}.label" for i in range(5)]
    for index in range(5):
        cls, _ = formats.read_label_file(str(labels_dir / f"{index:06d}.label"), 540)
        assert (cls[:500] == 50).all()
        assert (cls[500:] == (30 if index == 2 else 0)).all()
    assert (sequence / "labels.yaml").is_file() and not editor.dirty
    assert window.write(str(folder / "merged.pcd"), None)
    merged = formats.read_cloud(str(folder / "merged.pcd"))[1]
    assert sorted(set(merged["frame"].tolist())) == [1, 3] and editor.path == str(sequence)
    window.close_all(ask=False)
    assert not dialogs


def test_labels_survive_the_trip_through_voxels(workbench, monkeypatch):
    import mapbarber.cloud_editor as cloud_editor
    from mapbarber import formats
    from mapbarber.qt import QtWidgets
    window, folder, pump, dialogs = workbench
    points, truth = labelled_scene()
    path = folder / "labelled.pcd"
    person = np.random.default_rng(2).uniform([3.0, 3.0, 0.0], [3.3, 3.3, 1.7], (200, 3))
    points = np.vstack([points, person])
    truth = np.concatenate([truth, np.full(200, 7)])
    table = formats.with_labels(points, None, truth.astype(np.uint16), np.where(truth == 3, 9, 0).astype(np.uint32))
    formats.save_cloud(str(path), points, table)
    monkeypatch.setattr(cloud_editor, "ask_numbers", lambda parent, title, fields: [0.1 if len(f) > 2 else True
                                                                                    for f in fields])
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Yes))
    assert window.open(str(path))
    pump()
    source = window.editor
    assert source.labels.cls.tolist() == table["label"].tolist()
    points, person = source.cloud.xyz.copy(), source.cloud.xyz[-200:].copy()
    window.convert(source.to_voxels)
    voxels = window.editor
    assert voxels.vlabels.any and not voxels.label_mode
    window.set_label_mode(True)
    unambiguous(window)
    assert voxels.by_class.isChecked() and voxels.tool in dict(voxels.tools)
    from mapbarber.convert import point_keys
    person_keys = np.unique(point_keys(person[person[:, 2] > 0.2], 0.1))
    assert not np.isin(person_keys, voxels.map.occupied).any()
    wall_key = point_keys(points[4100:4101], 0.1)
    assert voxels.vlabels.get(wall_key).tolist() == [2]

    window.convert(voxels.to_cloud)
    back = window.editor
    assert np.array_equal(back.cloud.xyz, points) and back.labels.cls.tolist() == table["label"].tolist()
    assert back.labels.inst.tolist() == table["instance"].tolist()

    window.tabs.setCurrentWidget(voxels.widget)
    assert voxels.label_mode and voxels.protect.isChecked() and voxels.label_bar.isVisible()
    voxels.select(wall_key, "replace", trusted=True)
    assert not len(voxels.selected)
    voxels.toggle_protect()
    voxels.select(wall_key, "replace", trusted=True)
    voxels.assign_selection(4)
    voxels.toggle_protect()
    window.set_label_mode(False)
    voxels.edit(remove=point_keys(points[:1], 0.1), label="erase")
    voxels.undo()
    voxels.redo()
    window.convert(voxels.to_cloud)
    relabelled = window.editor
    in_wall = point_keys(points, 0.1) == wall_key[0]
    gone = point_keys(points, 0.1) == point_keys(points[:1], 0.1)[0]
    expected = table["label"].copy()
    expected[in_wall & (table["label"] != 7)] = 4
    assert relabelled.labels.cls.tolist() == expected[~gone].tolist()

    window.tabs.setCurrentWidget(voxels.widget)
    target = folder / "labelled_map.bt"
    assert window.write(str(target), None)
    assert window.answered_losses[-1] == ("bt", [window.tr_("loss_points")])
    expected_labels = voxels.vlabels.get(voxels.map.occupied).tolist()
    voxels.map.mark_saved()
    voxels.vlabels.mark_saved()
    window.close_document(voxels, ask=False)
    assert (folder / "labelled_map.bt.labels.npz").is_file() and (folder / "labelled_map.bt.labels.yaml").is_file()
    assert window.open(str(target))
    pump()
    reopened = window.editor
    window.set_label_mode(True)
    assert reopened.by_class.isChecked()
    assert reopened is not voxels and reopened.source is None
    assert reopened.vlabels.get(reopened.map.occupied).tolist() == expected_labels
    assert reopened.classes.name(4) == voxels.classes.name(4)
    window.close_all(ask=False)
    assert not dialogs


def test_protected_labels_stay_out_of_a_wide_selection(workbench):
    from mapbarber.formats import CLOUD
    window, _folder, pump, dialogs = workbench
    points, truth = labelled_scene()
    editor = window.show_document(CLOUD, (points, None))
    pump()
    window.set_label_mode(True)
    box = np.flatnonzero(truth == 3)
    editor.select(box, "replace")
    editor.assign_selection(5)
    window.set_tool("select")
    width, height = editor.viewport.renderer.GetSize()
    editor._rectangle((0, 0), (width, height), False)
    assert editor.selected.any() and not editor.selected[box].any()
    editor.select(np.arange(len(points)), "replace")
    assert not editor.selected[box].any()
    editor.selected[box] = True
    editor.assign_selection(2)
    assert (editor.labels.cls[box] == 5).all() and (editor.labels.cls[truth != 3] == 2).all()
    assert "1500" in window.statusBar().currentMessage()
    editor.select_class()
    editor.set_active(5)
    editor.select_class()
    assert editor.selected[box].all()
    editor.toggle_protect()
    editor.select(np.arange(len(points)), "replace")
    assert editor.selected.all()
    editor.clear_selection()
    window.close_all(ask=False)
    assert not dialogs


def test_undo_covers_classes_and_frame_writes(workbench, tmp_path):
    from mapbarber.formats import CLOUD
    window, folder, pump, dialogs = workbench
    points, truth = labelled_scene()
    editor = window.show_document(CLOUD, (points, None))
    pump()
    window.set_label_mode(True)
    assert editor.apply_button.text().startswith("Label mapping") and "floor" in editor.apply_button.text()
    editor.set_active(2)
    assert "wall" in editor.apply_button.text()
    count = len(editor.classes)
    editor.remove_class()
    assert 2 not in editor.classes and len(editor.classes) == count - 1
    editor.undo()
    assert 2 in editor.classes and editor.classes.name(2) == "wall"
    assert editor.class_list.topLevelItemCount() == count + 1
    editor.redo()
    assert 2 not in editor.classes
    editor.undo()
    editor.preset_box.setCurrentIndex(editor.preset_box.findData("las"))
    editor.load_preset(editor.preset_box.findData("las"))
    assert editor.classes.name(2) == "ground"
    editor.undo()
    assert editor.classes.name(2) == "wall"
    window.close_all(ask=False)

    sequence = tmp_path / "seq"
    (sequence / "velodyne").mkdir(parents=True)
    wall = np.column_stack([np.linspace(0, 9, 300), np.full(300, 5.0), np.linspace(0, 2, 300)])
    for index in range(3):
        np.column_stack([wall - [index, 0, 0], np.zeros(300)]).astype("<f4").tofile(
            str(sequence / "velodyne" / f"{index:06d}.bin"))
    (sequence / "poses.txt").write_text("".join(f"1 0 0 {i} 0 1 0 0 0 0 1 0\n" for i in range(3)))
    assert window.open(str(sequence))
    pump()
    frames = window.editor
    frames.select(np.arange(300), "replace")
    frames.assign_selection(50)
    frames.propagate_frames()
    assert (frames.frame_store[1][0] == 50).all() and frames.frame_store[1][2].all()
    frames.step_frame(1)
    assert frames.frame_ids == [1] and frames.labels.pending.all()
    frames.undo()
    assert not frames.labels.cls.any() and not frames.frame_store[2][0].any()
    frames.undo()
    frames.step_frame(-1)
    assert frames.frame_ids == [0] and not frames.labels.cls.any()
    frames.redo()
    assert (frames.labels.cls == 50).all()
    for document in window.documents:
        document.mark_saved()
    window.close_all(ask=False)
    assert not dialogs


def test_connected_pick_keeps_clear_of_the_ground(workbench):
    from mapbarber.formats import CLOUD
    window, _folder, pump, dialogs = workbench
    rng = np.random.default_rng(4)
    floor = np.column_stack([rng.uniform(-3, 3, 20000), rng.uniform(-3, 3, 20000), rng.normal(0, 0.01, 20000)])
    crate = rng.uniform([-0.3, -0.3, 0.0], [0.3, 0.3, 0.8], (3000, 3))
    points = np.vstack([floor, crate])
    editor = window.show_document(CLOUD, (points, None))
    pump()
    window.set_label_mode(True)
    window.set_tool("smart")
    editor.smart_box.setCurrentIndex(editor.smart_box.findData("object"))
    editor.clearance.setValue(0.0)
    editor.stop_bends.setChecked(False)
    assert len(editor.smart_ids(np.array([0.0, 0.0, 0.5]))) > 20000
    editor.stop_bends.setChecked(True)
    by_direction = editor.smart_ids(np.array([0.0, 0.0, 0.5]))
    assert np.isin(np.arange(20000, 23000), by_direction).mean() > 0.9 and (by_direction < 20000).sum() < 600
    floor_only = editor.smart_ids(np.array([2.0, 2.0, 0.0]))
    assert len(floor_only) > 15000 and (floor_only >= 20000).sum() < 400
    editor.stop_bends.setChecked(False)
    editor.clearance.setValue(0.1)
    picked = editor.smart_ids(np.array([0.0, 0.0, 0.5]))
    assert (picked < 20000).sum() < 30 and np.isin(np.arange(20000, 23000), picked).mean() > 0.9
    floor_pick = editor.smart_ids(np.array([2.0, 2.0, 0.0]))
    assert len(floor_pick) > 15000 and (points[floor_pick[floor_pick >= 20000], 2] < 0.15).all()
    window.close_all(ask=False)
    assert not dialogs


def test_objects_and_boxes(workbench, tmp_path):
    import json
    from mapbarber import formats
    window, _folder, pump, dialogs = workbench
    rng = np.random.default_rng(6)
    floor = np.column_stack([rng.uniform(-5, 5, 8000), rng.uniform(-5, 5, 8000), np.zeros(8000)])
    crates = [rng.uniform([x - 0.3, -0.4, 0.05], [x + 0.3, 0.4, 0.9], (800, 3)) for x in (-3, 0, 3)]
    crumbs = rng.uniform([4.0, 4.0, 0.3], [4.05, 4.05, 0.35], (5, 3))
    points = np.vstack([floor] + crates + [crumbs])
    path = str(tmp_path / "crates.pcd")
    formats.save_cloud(path, points)
    assert window.open(path)
    pump()
    editor = window.editor
    window.set_label_mode(True)
    crate_ids = np.arange(8000, 10405)
    editor.select(crate_ids, "replace")
    editor.assign_selection(5)
    editor.set_active(5)
    editor.split_instances()
    inst = editor.labels.inst[crate_ids]
    assert len(np.unique(inst[:2400])) == 3 and (inst[2400:] == 0).all()
    assert editor.instance_list.topLevelItemCount() == 3
    editor._instance_chosen(editor.instance_list.topLevelItem(1))
    assert editor.selected.sum() == 800
    editor.clear_selection()

    editor.clear_instances()
    assert not editor.labels.inst.any() and "furniture" in editor.class_boxes.text()
    editor.boxes_for_class()
    assert len(np.unique(editor.labels.inst[crate_ids[:2400]])) == 3
    assert len(editor.box_store[None]) == 3 and editor.box_list.topLevelItemCount() == 3
    assert {box["class"] for box in editor.box_store[None]} == {5}
    editor.boxes_for_class()
    assert len(editor.box_store[None]) == 3
    editor.set_active(2)
    editor.boxes_for_class()
    assert len(editor.box_store[None]) == 3
    editor.set_active(5)
    size = sorted(editor.box_store[None][0]["size"])
    assert np.allclose(size, [0.6, 0.8, 0.85], atol=0.05)
    editor.box_list.setCurrentItem(editor.box_list.topLevelItem(0))
    editor.box_fields[6].setValue(30.0)
    assert np.isclose(np.degrees(editor.box_store[None][0]["yaw"]), 30.0)
    editor.undo()
    assert not np.isclose(np.degrees(editor.box_store[None][0]["yaw"]), 30.0)
    editor.select_in_box()
    assert editor.selected.sum() >= 790
    editor.delete_box()
    assert len(editor.box_store[None]) == 2
    editor.undo()
    assert len(editor.box_store[None]) == 3
    editor.select(np.arange(10400, 10405), "replace", review=True)
    assert editor.selected.sum() == 5
    editor.label_box_from_selection()
    assert len(editor.box_store[None]) == 4

    editor.clear_selection()
    editor.clear_instances()
    assert not editor.labels.inst.any() and (editor.labels.cls[crate_ids] == 5).all()
    editor.undo()
    assert editor.labels.inst[crate_ids[:2400]].all()

    out = tmp_path / "standard"
    out.mkdir()
    editor.export_standard(str(out), [True, True, True])
    scan = np.fromfile(str(out / "velodyne" / "000000.bin"), "<f4").reshape(-1, 4)
    packed = np.fromfile(str(out / "labels" / "000000.label"), "<u4")
    assert np.allclose(scan[:, :3], points, atol=1e-4) and (packed & 0xFFFF).tolist() == editor.labels.cls.tolist()
    assert (packed >> 16).tolist() == editor.labels.inst.tolist()
    config = (out / "semantic-kitti.yaml").read_text()
    assert '5: "furniture"' in config and "learning_map:" in config and "color_map: # bgr" in config
    kitti_rows = (out / "label_2" / "000000.txt").read_text().splitlines()
    pcdet_rows = (out / "boxes_pcdet" / "000000.txt").read_text().splitlines()
    assert len(kitti_rows) == len(pcdet_rows) == 4 and len(kitti_rows[0].split()) == 15
    first = editor.box_store[None][0]
    values = pcdet_rows[0].split()
    assert values[-1] == "furniture" and np.allclose([float(v) for v in values[:3]], first["center"], atol=1e-3)
    fields = kitti_rows[0].split()
    assert fields[0] == "furniture" and np.isclose(float(fields[8]), first["size"][2], atol=0.01)
    assert np.allclose([float(fields[11]), float(fields[12]), float(fields[13])],
                       [-first["center"][1], -(first["center"][2] - first["size"][2] / 2), first["center"][0]], atol=0.011)

    assert window.save()
    saved = json.load(open(path + ".boxes.json"))
    assert len(saved["boxes"]) == 4 and saved["boxes"][0]["name"] == "furniture"
    window.close_document(editor, ask=False)
    assert window.open(path)
    pump()
    again = window.editor
    window.set_label_mode(True)
    assert len(again.box_store[None]) == 4 and again.box_list.topLevelItemCount() == 4
    window.close_all(ask=False)

    sequence = tmp_path / "seq"
    (sequence / "velodyne").mkdir(parents=True)
    for index in range(2):
        scan = np.vstack([floor, crates[1]]) - [index, 0, 0]
        np.column_stack([scan, np.zeros(len(scan))]).astype("<f4").tofile(str(sequence / "velodyne" / f"{index:06d}.bin"))
    (sequence / "poses.txt").write_text("1 0 0 0 0 1 0 0 0 0 1 0\n1 0 0 1 0 1 0 0 0 0 1 0\n")
    assert window.open(str(sequence))
    pump()
    frames_editor = window.editor
    frames_editor.show_frames([0, 1])
    frames_editor.select(np.r_[8000:8800, 16800:17600], "replace")
    frames_editor.assign_selection(10)
    frames_editor.set_active(10)
    frames_editor.clear_selection()
    frames_editor.split_instances()
    frames_editor.fit_boxes()
    assert len(frames_editor.box_store[0]) == 1 and len(frames_editor.box_store[1]) == 1
    assert np.allclose(frames_editor.box_store[1][0]["center"][0], -1.0, atol=0.05)
    assert window.save()
    stored = json.load(open(sequence / "boxes" / "000001.json"))
    assert stored["frame"] == "000001" and np.isclose(stored["boxes"][0]["center"][0], -1.0, atol=0.05)
    for document in window.documents:
        document.mark_saved()
    window.close_all(ask=False)
    assert not dialogs


def test_voxel_smart_pick(workbench):
    from mapbarber.formats import VOXEL
    from mapbarber.voxels import pack
    window, _folder, pump, dialogs = workbench
    floor = np.stack(np.meshgrid(np.arange(60), np.arange(60), [0], indexing="ij"), -1).reshape(-1, 3)
    crate = np.stack(np.meshgrid(np.arange(20, 26), np.arange(20, 26), np.arange(1, 9), indexing="ij"), -1).reshape(-1, 3)
    wall = np.stack(np.meshgrid(np.arange(60), [59], np.arange(1, 30), indexing="ij"), -1).reshape(-1, 3)
    editor = window.show_document(VOXEL, (pack(np.vstack([floor, crate, wall])), 0.05))
    pump()
    window.set_label_mode(True)
    unambiguous(window)
    window.set_tool("smart")
    assert editor.tool == "smart" and editor.smart_box.currentData() == "object"
    crate_keys, floor_keys, wall_keys = set(pack(crate).tolist()), set(pack(floor).tolist()), set(pack(wall).tolist())
    editor.stop_bends.setChecked(False)
    editor.clearance.setValue(0.0)
    assert len(editor.smart_keys(np.array([22, 22, 8]))) == len(floor) + len(crate) + len(wall)
    editor.clearance.setValue(0.05)
    assert set(editor.smart_keys(np.array([22, 22, 8])).tolist()) == crate_keys
    editor.smart_box.setCurrentIndex(editor.smart_box.findData("plane"))
    plane = set(editor.smart_keys(np.array([40, 10, 0])).tolist())
    assert plane == floor_keys
    wall_pick = set(editor.smart_keys(np.array([30, 59, 15])).tolist())
    assert len(wall_pick & wall_keys) > 0.95 * len(wall_keys) and not wall_pick & crate_keys
    editor.smart_box.setCurrentIndex(editor.smart_box.findData("object"))
    editor.look_from((1, -1, 0.8), (0, 0, 1))
    pump()
    editor._smart_click(*screen(editor, (1.15, 1.15, 0.45)), False)
    assert set(editor.selection.tolist()) == crate_keys
    editor.set_active(5)
    editor.assign_selection()
    assert set(editor.vlabels.get(pack(crate)).tolist()) == {5} and not editor.vlabels.get(pack(floor)).any()
    editor.at_once.setChecked(True)
    editor.smart_box.setCurrentIndex(editor.smart_box.findData("plane"))
    editor.set_active(1)
    editor._smart_click(*screen(editor, (2.5, 0.5, 0.05)), False)
    assert set(editor.vlabels.get(pack(floor)).tolist()) == {1} and set(editor.vlabels.get(pack(crate)).tolist()) == {5}
    editor.undo()
    assert not editor.vlabels.get(pack(floor)).any()
    for document in window.documents:
        document.mark_saved()
    window.close_all(ask=False)
    assert not dialogs
