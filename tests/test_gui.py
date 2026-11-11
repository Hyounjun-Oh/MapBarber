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
    for editor in window.editors.values():
        (editor.cloud if hasattr(editor, "cloud") else editor.map).mark_saved()
    window.close()


def vtk_click(viewport, x, y, shift=False):
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
