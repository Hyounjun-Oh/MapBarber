"""Record the README animations by driving the real application and capturing every frame.

    python tools/record_demo.py docs/media/ [name.gif ...] [--kitti=/path/to/2011_09_26_drive_0005_sync]

Needs ffmpeg and a display. The labeling animations need the KITTI raw drive 2011_09_26_0005 (with its
calib_*.txt one folder up) whose frame 0 holds labels and boxes made by hand (labels/, boxes/); they only show
and use those, and are skipped without --kitti.
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from mapbarber.qt import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

Qt = QtCore.Qt
EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo")
WINDOW_SIZE = (1280, 760)
FPS = 12
CURSOR = [(0, 0), (0, 17), (4.5, 13), (7.5, 20), (10, 19), (7, 12), (13, 12)]

for _name in ("critical", "warning", "information", "question"):
    setattr(QtWidgets.QMessageBox, _name, staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Yes))


class Recorder:
    def __init__(self, app, window, workdir):
        self.app, self.window = app, window
        self.workdir = workdir
        self.frames = 0
        self.frame_dir = None
        self.cursor = QtCore.QPointF(WINDOW_SIZE[0] * 0.45, WINDOW_SIZE[1] * 0.5)
        self.caption = ""
        self.ripple = 0
        self.last = None
        self.crop = None

    def pump(self, seconds=0.05):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()

    def start(self, crop=None):
        """Begin a recording; `crop` (a widget) keeps only the part of the window that widget covers."""
        self.frame_dir = tempfile.mkdtemp(prefix="frames_", dir=self.workdir)
        self.frames = 0
        self.crop = None
        if crop is not None:
            corner = crop.mapTo(self.window, QtCore.QPoint(0, 0))
            self.crop = QtCore.QRect(corner, crop.size())

    def compose(self):
        image = self.window.capture().convertToFormat(QtGui.QImage.Format_RGB32)
        shift = QtCore.QPoint(0, 0)
        if self.crop is not None:
            image = image.copy(self.crop)
            shift = self.crop.topLeft()
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.translate(-shift)
        origin = self.window.mapToGlobal(QtCore.QPoint(0, 0))
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if widget is self.window or not widget.isVisible():
                continue
            if isinstance(widget, (QtWidgets.QMenu, QtWidgets.QDialog)):
                corner = widget.mapToGlobal(QtCore.QPoint(0, 0)) - origin
                painter.drawPixmap(corner, widget.grab())
        painter.resetTransform()
        if self.caption:
            font = painter.font()
            font.setPointSizeF(13)
            font.setBold(True)
            painter.setFont(font)
            metrics = QtGui.QFontMetrics(font)
            width = metrics.horizontalAdvance(self.caption) + 36
            box = QtCore.QRectF((image.width() - width) / 2, image.height() - 86, width, 40)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QtGui.QColor(15, 17, 22, 225))
            painter.drawRoundedRect(box, 10, 10)
            painter.setPen(QtGui.QColor(255, 255, 255))
            painter.drawText(box, Qt.AlignCenter, self.caption)
        painter.translate(-shift)
        if self.ripple:
            radius = 8 + (4 - self.ripple) * 6
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 210, 40), 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(self.cursor, radius, radius)
            self.ripple -= 1
        arrow = QtGui.QPolygonF([QtCore.QPointF(self.cursor.x() + x, self.cursor.y() + y) for x, y in CURSOR])
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1.5))
        painter.setBrush(QtGui.QColor(255, 255, 255))
        painter.drawPolygon(arrow)
        painter.end()
        return image

    def frame(self, hold=1):
        self.pump(0.02)
        path = os.path.join(self.frame_dir, f"{self.frames:05d}.png")
        self.compose().save(path)
        self.frames += 1
        for _ in range(hold - 1):
            shutil.copyfile(path, os.path.join(self.frame_dir, f"{self.frames:05d}.png"))
            self.frames += 1

    def hold(self, seconds):
        self.frame(max(1, int(seconds * FPS)))

    def say(self, text, seconds=0.0):
        self.caption = text
        if seconds:
            self.hold(seconds)

    def glide(self, target, steps=10, each=None):
        start = QtCore.QPointF(self.cursor)
        target = QtCore.QPointF(target)
        for i in range(1, steps + 1):
            t = 0.5 - 0.5 * math.cos(math.pi * i / steps)
            self.cursor = start + (target - start) * t
            if each:
                each(self.cursor)
            self.frame()

    def in_window(self, widget, point=None):
        point = point if point is not None else widget.rect().center()
        return QtCore.QPointF(widget.mapTo(self.window, QtCore.QPoint(int(point.x()), int(point.y()))))

    def click_widget(self, widget, steps=10):
        spot = widget.rect().center()
        if isinstance(widget, QtWidgets.QCheckBox):
            spot = QtCore.QPoint(10, widget.height() // 2)
        self.glide(self.in_window(widget, spot), steps)
        self.ripple = 4
        QtTest.QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, spot)
        self.frame(3)

    def shortcut(self, sequence):
        wanted = QtGui.QKeySequence(sequence)
        for action in self.window.actions():
            if wanted in action.shortcuts() and action.isEnabled():
                action.trigger()
                return

    def toolbar_button(self, text_part):
        for action in self.window.toolbar.actions():
            if text_part in action.text():
                return self.window.toolbar.widgetForAction(action)
        raise KeyError(text_part)

    def panel_button(self, text):
        for widget in self.window.dock.findChildren(QtWidgets.QPushButton):
            if widget.text() == text:
                return widget
        raise KeyError(text)

    def scroll_panel_to(self, widget):
        scroll = self.window.dock.widget()
        scroll.ensureWidgetVisible(widget, 0, 40)
        scroll.horizontalScrollBar().setValue(0)
        self.pump(0.05)

    def vtk_to_window(self, x, y):
        widget = self.window.editor.widget
        return self.in_window(widget, QtCore.QPointF(x, widget.height() - y))

    def window_to_vtk(self, point):
        widget = self.window.editor.widget
        local = widget.mapFrom(self.window, QtCore.QPoint(int(point.x()), int(point.y())))
        return local.x(), widget.height() - local.y()

    def vtk_event(self, name, point, shift=False, ctrl=False):
        interactor = self.window.editor.viewport.interactor
        x, y = self.window_to_vtk(point)
        interactor.SetEventInformation(x, y, int(ctrl), int(shift))
        getattr(interactor, name)()

    def vtk_hover_to(self, target, steps=10):
        self.glide(target, steps, lambda p: self.vtk_event("MouseMoveEvent", p))

    def vtk_click(self, target, steps=8):
        self.vtk_hover_to(target, steps)
        self.ripple = 4
        self.vtk_event("LeftButtonPressEvent", target)
        self.vtk_event("LeftButtonReleaseEvent", target)
        self.frame(3)

    def vtk_drag(self, start, end, steps=16, shift=False):
        self.vtk_hover_to(start, 6)
        self.vtk_event("LeftButtonPressEvent", start, shift=shift)
        self.glide(end, steps, lambda p: self.vtk_event("MouseMoveEvent", p, shift=shift))
        self.vtk_event("LeftButtonReleaseEvent", end, shift=shift)
        self.frame(2)

    def project(self, world):
        renderer = self.window.editor.viewport.renderer
        renderer.SetWorldPoint(*world, 1.0)
        renderer.WorldToDisplay()
        x, y, _ = renderer.GetDisplayPoint()
        return self.vtk_to_window(x, y)

    def cell_to_window(self, row, column):
        editor = self.window.editor
        view = editor.canvas.mapFromScene(QtCore.QPointF(column + 0.5, editor.map.shape[0] - row - 0.5))
        return self.in_window(editor.canvas.viewport(), QtCore.QPointF(view))

    def canvas_local(self, point):
        viewport = self.window.editor.canvas.viewport()
        return viewport.mapFrom(self.window, QtCore.QPoint(int(point.x()), int(point.y())))

    def canvas_move(self, point, modifiers=Qt.NoModifier, buttons=Qt.NoButton):
        local = QtCore.QPointF(self.canvas_local(point))
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, local, local, Qt.NoButton, buttons, modifiers)
        QtWidgets.QApplication.sendEvent(self.window.editor.canvas.viewport(), event)

    def canvas_move_to(self, cell, modifiers=Qt.NoModifier, steps=10):
        self.glide(self.cell_to_window(*cell), steps, lambda p: self.canvas_move(p, modifiers))

    def canvas_drag(self, cells, steps_each=6, modifiers=Qt.NoModifier):
        viewport = self.window.editor.canvas.viewport()
        first = self.cell_to_window(*cells[0])
        self.glide(first, 8, lambda p: self.canvas_move(p))
        QtTest.QTest.mousePress(viewport, Qt.LeftButton, modifiers, self.canvas_local(first))
        self.ripple = 4
        for cell in cells[1:]:
            target = self.cell_to_window(*cell)
            self.glide(target, steps_each, lambda p: self.canvas_move(p, modifiers, Qt.LeftButton))
        QtTest.QTest.mouseRelease(viewport, Qt.LeftButton, modifiers, self.canvas_local(self.cursor))
        self.frame(3)

    def canvas_click(self, row, column, modifiers=Qt.NoModifier):
        self.canvas_drag([(row, column)], modifiers=modifiers)

    def write_gif(self, path, width=960, colours=160, dither="bayer:bayer_scale=4"):
        """Encode the frames: a GIF, or for a .webp path an animated WebP (far smaller for whole LiDAR scans)."""
        frames = ["-framerate", str(FPS), "-i", os.path.join(self.frame_dir, "%05d.png")]
        if path.endswith(".webp"):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *frames, "-vf", f"scale={width}:-1:flags=lanczos",
                            "-c:v", "libwebp_anim", "-lossless", "0", "-q:v", "62", "-compression_level", "6",
                            "-loop", "0", path], check=True)
        else:
            palette = (f"fps={FPS},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors={colours}:stats_mode=diff[p];"
                       f"[b][p]paletteuse=dither={dither}:diff_mode=rectangle")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *frames, "-vf", palette, path], check=True)
        shutil.rmtree(self.frame_dir)
        print(f"{path}: {self.frames} frames, {os.path.getsize(path) // 1024} KiB")


def menu_pick(recorder, menu_title, item_text):
    window = recorder.window
    bar = window.menuBar()
    action = next(a for a in bar.actions() if a.text().replace("&", "") == menu_title)
    recorder.glide(QtCore.QPointF(bar.mapTo(window, bar.actionGeometry(action).center())), 10)
    recorder.ripple = 4
    menu = action.menu()
    menu.popup(bar.mapToGlobal(bar.actionGeometry(action).bottomLeft()))
    recorder.frame(4)
    item = next(a for a in menu.actions() if a.text() == item_text)
    target = QtCore.QPointF(menu.actionGeometry(item).center())
    corner = menu.mapToGlobal(QtCore.QPoint(0, 0)) - window.mapToGlobal(QtCore.QPoint(0, 0))
    menu.setActiveAction(item)
    recorder.glide(target + QtCore.QPointF(corner), 8)
    recorder.frame(4)
    menu.hide()
    return item


def answer_dialog(recorder, values, seconds=1.4):
    """Show the modal number dialog on screen for a moment, type values, and press OK."""
    def step():
        dialog = QtWidgets.QApplication.activeModalWidget()
        if dialog is None:
            QtCore.QTimer.singleShot(30, step)
            return
        recorder.frame(3)
        boxes = dialog.findChildren(QtWidgets.QAbstractSpinBox)
        for box, value in zip(boxes, values):
            recorder.glide(_dialog_point(recorder, dialog, box), 6)
            box.setValue(value)
            recorder.frame(4)
        ok = dialog.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok)
        recorder.glide(_dialog_point(recorder, dialog, ok), 6)
        recorder.ripple = 4
        recorder.hold(seconds / 2)
        dialog.accept()
    QtCore.QTimer.singleShot(30, step)


def _dialog_point(recorder, dialog, widget):
    corner = dialog.mapToGlobal(QtCore.QPoint(0, 0)) - recorder.window.mapToGlobal(QtCore.QPoint(0, 0))
    return QtCore.QPointF(widget.mapTo(dialog, widget.rect().center()) + corner)


def demo_overview(rec, out):
    window = rec.window
    rec.start()
    rec.say("One window for every robot map", 1.6)
    for name, caption in (("room.bt", "room.bt  →  OctoMap octree  →  voxel editor"),
                          ("scan.pcd", "scan.pcd  →  point cloud  →  point cloud editor"),
                          ("floor.yaml", "floor.yaml  →  ROS map_server map  →  2D grid editor")):
        rec.say("")
        rec.glide(rec.in_window(rec.toolbar_button("Open")), 8)
        rec.ripple = 4
        rec.frame(2)
        window.open(os.path.join(rec.workdir, name))
        rec.pump(0.3)
        rec.say(caption, 2.0)
    rec.say("Each map in its own tab  ·  Ctrl+Tab switches")
    for _ in range(3):
        rec.shortcut("Ctrl+Tab")
        rec.pump(0.2)
        rec.hold(0.8)
    window.tabs.setCurrentIndex(0)
    rec.pump(0.3)
    rec.say("Convert ▸ To 2D occupancy grid", 0.6)
    item = menu_pick(rec, "Convert", "To 2D occupancy grid…")
    rec.say("Pick the height band to project")
    answer_dialog(rec, [0.3, 1.9])
    item.trigger()
    rec.pump(0.3)
    rec.say("The result opens in a new tab", 2.0)
    rec.say("Language ▸ 한국어")
    window.set_language("ko")
    rec.pump(0.3)
    rec.hold(1.6)
    window.set_language("en")
    rec.write_gif(out)


def demo_voxels(rec, out):
    window = rec.window
    window.open(os.path.join(rec.workdir, "office_octomap.bt"))
    rec.pump(0.4)
    editor = window.editor
    rec.start()
    rec.say("An office mapped by a depth camera — the ceiling hides everything", 1.6)

    rec.say("Slice the space along z")
    rec.scroll_panel_to(editor.slice.enabled)
    rec.click_widget(editor.slice.enabled)
    rec.hold(0.8)
    rec.say("Drag the plane up until only the ceiling is cut away")
    plane = editor.slice_gizmo.centre()
    grab = rec.project(plane + np.array([0, 0, 0.6 * editor.slice_gizmo.length()]))
    target = rec.project(plane + np.array([0, 0, 0.6 * editor.slice_gizmo.length() + 1.35]))
    rec.vtk_drag(grab, target, 18)
    editor.slice.position.setValue(2.85)
    rec.pump(0.4)
    rec.hold(1.2)
    rec.say("…or tilt it")
    for angle in (8.0, 16.0, 24.0):
        editor.slice.tilts[0].setValue(angle)
        rec.pump(0.3)
        rec.hold(0.4)
    rec.hold(0.8)
    editor.slice.tilts[0].setValue(0.0)
    rec.pump(0.4)
    rec.hold(0.6)

    rec.say("Select islands finds the floating specks")
    rec.click_widget(rec.panel_button("Select small isolated clusters"))
    rec.hold(1.2)
    rec.say("Delete removes them")
    rec.shortcut("Delete")
    rec.hold(1.0)

    rec.say("Box: drag its arrows onto the ghost of a passer-by")
    rec.scroll_panel_to(rec.panel_button("Erase inside the box"))
    editor.set_box((4.3, 2.6, 0.05), (4.7, 3.0, 1.85))
    rec.hold(0.6)
    length = editor.box_gizmo.length()
    for axis, shift in ((0, 0.95), (1, 1.4)):
        centre = (editor.box_gizmo.low + editor.box_gizmo.high) / 2
        tip = centre.copy()
        tip[axis] += 0.6 * length
        moved = tip.copy()
        moved[axis] += shift
        rec.vtk_drag(rec.project(tip), rec.project(moved), 14)
    editor.set_box((5.15, 3.95, 0.05), (5.55, 4.35, 1.85))
    rec.hold(0.6)
    rec.click_widget(rec.panel_button("Erase inside the box"))
    rec.hold(1.2)

    rec.say("…and fill the holes in a black monitor")
    editor.set_box((2.6, 3.6, 0.75), (3.0, 3.65, 1.1))
    rec.hold(0.8)
    rec.click_widget(rec.panel_button("Fill the box"))
    rec.hold(1.2)
    editor.show_box.setChecked(False)

    rec.say("Ruler: desk height — Shift locks it to the z axis")
    window.set_tool("measure")
    rec.vtk_click(rec.project((3.9, 3.4, 0.0)), 8)
    rec.vtk_hover_to(rec.project((3.4, 3.2, 0.75)), 10)
    rec.vtk_event("LeftButtonPressEvent", rec.cursor, shift=True)
    rec.vtk_event("LeftButtonReleaseEvent", rec.cursor, shift=True)
    rec.ripple = 4
    rec.hold(1.8)
    editor.clear_ruler()

    rec.say("Restore view — the hidden half was never touched")
    rec.click_widget(rec.panel_button("Restore view"))
    rec.hold(1.4)
    rec.say("Ctrl+S writes a standard OctoMap .bt")
    window.save()
    rec.hold(1.4)
    rec.write_gif(out)


def demo_cloud(rec, out):
    window = rec.window
    window.open(os.path.join(rec.workdir, "scan.pcd"))
    rec.pump(0.4)
    editor = window.editor
    editor.colour_box.setCurrentIndex(editor.colour_box.findData("rgb"))
    rec.start()
    rec.say("A noisy point cloud with intensity and colour fields", 1.4)
    rec.say("Select outliers (statistical filter)")
    rec.click_widget(rec.panel_button("Select outliers"))
    rec.hold(1.4)
    rec.shortcut("Delete")
    rec.say("Deleted — every other field is kept", 1.0)

    editor.look_from((0, 0, 1), (0, 1, 0))
    rec.say("Erase brush: sweep away the streak")
    window.set_tool("delete")
    editor.radius.setValue(0.2)
    for t in np.linspace(0.0, 1.0, 8):
        point = np.array([3.0, 0.5, 0.4]) + t * np.array([1.2, 1.3, 1.6])
        rec.vtk_click(rec.project(point), 5)
    rec.hold(0.8)

    rec.say("Ruler: wall to wall, Shift locks it to x")
    window.set_tool("measure")
    rec.vtk_click(rec.project((0.0, 2.0, 2.4)), 8)
    rec.vtk_hover_to(rec.project((6.0, 2.2, 2.4)), 12)
    rec.vtk_event("LeftButtonPressEvent", rec.cursor, shift=True)
    rec.vtk_event("LeftButtonReleaseEvent", rec.cursor, shift=True)
    rec.ripple = 4
    rec.hold(1.8)
    editor.clear_ruler()

    editor.look_from((1, -1, 0.8), (0, 0, 1))
    rec.say("Colour by any field")
    rec.glide(rec.in_window(editor.colour_box), 8)
    editor.colour_box.setCurrentIndex(editor.colour_box.findData("intensity"))
    rec.ripple = 4
    rec.hold(1.2)
    rec.say("Thin out to a 5 cm grid")
    rec.scroll_panel_to(rec.panel_button("Thin out (one point per cell)"))
    rec.click_widget(rec.panel_button("Thin out (one point per cell)"))
    rec.hold(1.2)
    rec.say("Ctrl+Z undoes it")
    rec.shortcut("Ctrl+Z")
    rec.hold(1.2)
    rec.write_gif(out)


def demo_grid(rec, out):
    window = rec.window
    window.open(os.path.join(rec.workdir, "floor.yaml"))
    rec.pump(0.4)
    editor = window.editor
    rec.start()
    rec.say("A ROS map with speckles, gaps and a hole", 1.4)
    rec.say("Clear speckles")
    rec.click_widget(rec.panel_button("Clear speckles"))
    rec.hold(1.0)

    rec.say("Line + Shift: a perfectly straight wall across the doorway")
    window.set_tool("line")
    editor.brush.setValue(3)
    rec.canvas_drag([(151, 330), (155, 342), (153, 352)], 8, Qt.ShiftModifier)
    rec.hold(0.8)

    rec.say("Pen: sketch an obstacle")
    window.set_tool("pen")
    editor.brush.setValue(2)
    loop = [(220 + 18 * math.sin(a), 300 + 30 * math.cos(a)) for a in np.linspace(0, 2 * math.pi, 14)]
    rec.canvas_drag([(int(r), int(c)) for r, c in loop], 3)
    rec.hold(0.5)

    rec.say("Rectangle + Shift: a square keep-out zone")
    window.set_tool("rectangle")
    rec.canvas_drag([(80, 250), (100, 290), (104, 300)], 8, Qt.ShiftModifier)
    rec.hold(0.8)

    rec.say("Fill with free space to repair the unknown hole")
    editor.set_state(0)
    window.set_tool("fill")
    rec.canvas_click(65, 67)
    rec.hold(1.0)

    rec.say("Ruler: metres and pixels, Shift keeps it level")
    window.set_tool("measure")
    rec.canvas_click(110, 31)
    rec.canvas_move_to((114, 200), Qt.ShiftModifier)
    rec.canvas_click(114, 200, Qt.ShiftModifier)
    rec.hold(1.8)
    editor.clear_ruler()

    rec.say("Trim the unknown border (origin follows)")
    rec.click_widget(rec.panel_button("Trim unknown border"))
    rec.hold(1.4)
    rec.say("Ctrl+S writes the image and its YAML")
    window.save()
    rec.hold(1.2)
    rec.write_gif(out)


KITTI = None
KITTI_CLASSES = {"road": 40, "car": 10, "person": 30, "pole": 80, "bus": 13}


def kitti(rec, labels=True, boxes=True):
    """A working copy of a KITTI raw drive (the scans stay where they are and are only read), opened in the editor.

    labels / boxes: also copy the drive's labels/ and boxes/ folders (the frame labeled by hand).
    """
    root = os.path.join(rec.workdir, "kitti")
    target = os.path.join(root, "drive")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(target)
    parent = os.path.dirname(os.path.abspath(KITTI))
    for name in os.listdir(parent):
        if name.startswith("calib_") and name.endswith(".txt"):
            shutil.copy(os.path.join(parent, name), root)
    os.symlink(os.path.join(os.path.abspath(KITTI), "velodyne_points"), os.path.join(target, "velodyne_points"))
    shutil.copytree(os.path.join(KITTI, "oxts"), os.path.join(target, "oxts"))
    for name, wanted in (("labels.yaml", True), ("labels", labels), ("boxes", boxes)):
        source = os.path.join(KITTI, name)
        if wanted and os.path.isdir(source):
            shutil.copytree(source, os.path.join(target, name))
        elif wanted and os.path.isfile(source):
            shutil.copy(source, target)
    rec.window.open(target)
    rec.pump(0.8)
    return rec.window.editor


def hand_boxes(editor):
    """The boxes of the frame labeled by hand (frame 0), in world coordinates, by object number."""
    from mapbarber import boxes
    path = os.path.join(KITTI, "boxes", editor.sequence.names[0] + ".json")
    return {box["instance"]: boxes.moved(box, editor.sequence.poses[0]) for box in boxes.load(path)}


def show(editor, low, high, direction=(-1.0, -0.9, 0.85)):
    editor.viewport.look_from(direction, (0, 0, 1), (low[0], high[0], low[1], high[1], low[2], high[2]))
    editor.viewport.fit_axes()
    editor.viewport.render()


def spot(editor, box, frame, grow=1.0):
    """A point of a frame inside a (world) box grown by `grow`, the one nearest its centre: a safe place to click."""
    from mapbarber import boxes
    ids = editor._key_ids(frame)
    inside = ids[boxes.inside(dict(box, size=[v + grow for v in box["size"]]), editor.cloud.xyz[ids])]
    centre = np.asarray(box["center"])
    return editor.cloud.xyz[inside[np.argmin(np.linalg.norm(editor.cloud.xyz[inside] - centre, axis=1))]]


def zoom(editor, box, pad=7.0, direction=(-0.8, -1.0, 0.8)):
    centre = np.asarray(box["center"], float)
    show(editor, centre - [pad, pad, pad / 3], centre + [pad, pad, pad / 3], direction)


def around(boxes, pad=3.0):
    centres = np.array([box["center"] for box in boxes])
    return centres.min(axis=0) - [pad, pad, 1.5], centres.max(axis=0) + [pad, pad, 2.0]


def tree_item(rec, tree, item):
    return rec.in_window(tree.viewport(), QtCore.QPointF(tree.visualItemRect(item).center()))


def demo_labeling(rec, out):
    editor = kitti(rec, labels=True, boxes=False)
    known = hand_boxes(editor)
    editor.timeline.slider.on_range(0, 0)
    rec.pump(0.5)
    show(editor, (-14, -12, -2.5), (16, 12, 2), (-0.8, -1.0, 0.9))
    rec.start()
    rec.say("KITTI drive 0005, frame 0 labeled by hand: cars, a bus, pedestrians, poles", 2.0)
    rec.scroll_panel_to(editor.class_list)
    rec.say("The class list counts the points of every class; the corner bar shows the active one")
    rec.glide(rec.in_window(editor.class_list), 10)
    rec.hold(1.4)
    editor.set_active(KITTI_CLASSES["person"])
    solo = rec.panel_button(editor.tr("label_solo"))
    rec.say("Show only this class: the pedestrians")
    rec.click_widget(solo)
    rec.hold(1.6)
    rec.say("Select all of this class")
    rec.click_widget(rec.panel_button(editor.tr("label_select_class")))
    rec.hold(1.4)
    rec.shortcut("Escape")
    rec.click_widget(solo)
    rec.hold(0.6)
    rec.say("Colour by object: every instance gets its own shade of its class")
    rec.scroll_panel_to(editor.colour_box)
    rec.glide(rec.in_window(editor.colour_box), 8)
    editor.colour_box.setCurrentIndex(editor.colour_box.findData("instance"))
    rec.ripple = 4
    rec.hold(1.8)
    editor.colour_box.setCurrentIndex(editor.colour_box.findData("label"))
    zoom(editor, known[8], 7.0)
    rec.shortcut("V")
    rec.say("Labeled points are protected: a wide rectangle takes only what is still unlabeled")
    car = np.asarray(known[8]["center"])
    rec.vtk_drag(rec.project(car + [-4, -3, -1]), rec.project(car + [4, 3, 1.5]), 16, shift=True)
    rec.hold(2.0)
    rec.shortcut("Escape")
    rec.hold(0.6)
    rec.write_gif(out)


def demo_smart_pick(rec, out):
    editor = kitti(rec, labels=True, boxes=False)
    known = hand_boxes(editor)
    editor.timeline.slider.on_range(0, 0)
    rec.pump(0.5)
    show(editor, (-12, -12, -2.5), (16, 12, 2), (-0.8, -1.0, 0.9))
    rec.start()
    rec.say("Smart pick (W) against the hand labels of frame 0", 1.6)
    rec.say("Protection off, so labeled points can be picked (the labels stay as they are)")
    rec.glide(rec.in_window(editor.label_bar.protect), 10)
    rec.ripple = 4
    editor.label_bar.protect.click()
    rec.hold(1.0)
    rec.shortcut("W")
    rec.scroll_panel_to(editor.smart_box)
    editor.smart_box.setCurrentIndex(editor.smart_box.findData("object"))
    for number, text in ((8, "One click: the car, without the road under it"),
                         (1, "A pedestrian, without the ground under the feet"),
                         (13, "A pole, cut off where it meets the ground")):
        zoom(editor, known[number], 5.0)
        rec.say(text)
        rec.hold(0.6)
        rec.vtk_click(rec.project(spot(editor, known[number], 0)), 12)
        rec.hold(1.6)
        rec.shortcut("Escape")
    show(editor, (-12, -10, -2.5), (8, 10, 2), (-0.7, -1.0, 0.75))
    rec.say("Flat surface: the road with one click")
    rec.glide(rec.in_window(editor.smart_box), 8)
    editor.smart_box.setCurrentIndex(editor.smart_box.findData("plane"))
    editor.reach.setValue(25.0)
    editor.flatness.setValue(0.08)
    rec.ripple = 4
    rec.hold(0.6)
    pose = editor.sequence.poses[0]
    rec.vtk_click(rec.project(spot(editor, {"center": list(pose[:3, :3] @ [4.0, 0.0, -1.73] + pose[:3, 3]),
                                            "size": [1.0, 1.0, 0.4], "yaw": 0.0}, 0)), 12)
    rec.hold(1.8)
    rec.shortcut("Escape")
    rec.write_gif(out)


def demo_boxes(rec, out):
    editor = kitti(rec, labels=True, boxes=False)
    known = hand_boxes(editor)
    editor.timeline.slider.on_range(0, 0)
    rec.pump(0.5)
    show(editor, (-12, -12, -2.5), (16, 10, 2), (-0.8, -1.0, 0.9))
    rec.start()
    rec.say("Frame 0 labeled by hand: cars, a bus, pedestrians, poles", 1.8)
    for name in ("car", "person"):
        editor.set_active(KITTI_CLASSES[name])
        rec.scroll_panel_to(editor.class_boxes)
        rec.say(f"Auto 3D boxes: every {name} is split off and gets an upright box")
        rec.click_widget(editor.class_boxes)
        rec.hold(1.6)
    rec.scroll_panel_to(editor.box_list)
    rec.say("Every box is listed with its size; pick one to edit it")
    item = editor.box_list.topLevelItem(0)
    rec.glide(tree_item(rec, editor.box_list, item), 10)
    rec.ripple = 4
    editor.box_list.setCurrentItem(item)
    rec.hold(1.4)
    rec.say("Edit centre, size and yaw in the fields")
    yaw = editor.box_fields[6]
    rec.glide(rec.in_window(yaw), 10)
    start = yaw.value()
    for value in np.linspace(start, start + 25, 6):
        yaw.setValue(float(value))
        rec.frame(2)
    rec.hold(0.8)
    rec.say("Refit to its points")
    rec.click_widget(rec.panel_button("Refit to its points"))
    rec.hold(1.4)
    rec.write_gif(out)


def demo_auto_labeling(rec, out):
    editor = kitti(rec, labels=True, boxes=True)
    known = hand_boxes(editor)
    last = len(editor.sequence) - 1
    editor.timeline.slider.on_range(0, 0)
    rec.pump(0.5)
    low, high = around(list(known.values()), 6.0)
    show(editor, low, high, (-0.8, -1.0, 1.0))
    rec.start(crop=editor.timeline.parentWidget())
    rec.say("Frame 0 labeled by hand, with its 3D boxes", 1.6)
    rec.say(f"Set the timeline to the whole drive: frames 0–{last}")
    rec.glide(rec.in_window(editor.timeline.slider), 10)
    editor.timeline.slider.on_range(0, last)
    rec.pump(0.5)
    show(editor, *editor.data_bounds, (-0.6, -1.0, 1.4))
    rec.hold(1.4)
    forward = rec.panel_button(editor.tr("track"))
    rec.scroll_panel_to(forward)
    rec.say("▶ Auto 3D box labeling forwards in time")
    rec.click_widget(forward)
    rec.hold(1.4)
    rec.say(f"The result, scan by scan from frame 0 to {last}, with the view fixed to the LiDAR")
    editor.timeline.anchor.setCurrentIndex(editor.timeline.anchor.findData("lidar"))
    editor.timeline.slider.on_range(0, 0)
    rec.pump(0.3)
    pose = editor.sequence.poses[0]
    centre = pose[:3, 3]
    show(editor, centre - [22, 22, 3], centre + [22, 22, 3], (-0.5, -1.0, 1.1))
    rec.hold(0.6)
    for frame in range(1, last + 1):
        editor.timeline.slider.on_range(frame, frame)
        rec.pump(0.05)
        rec.caption = f"Auto 3D box labeling from the hand-labeled frame 0 — frame {frame} / {last}"
        rec.frame()
    rec.hold(1.2)
    rec.write_gif(out, width=720)


def demo_conversion(rec, out):
    window = rec.window
    window.open(os.path.join(rec.workdir, "scan.pcd"))
    rec.pump(0.4)
    rec.start()
    rec.say("A point cloud with colour and intensity", 1.4)
    rec.say("Convert ▸ To voxel map")
    item = menu_pick(rec, "Convert", window.tr_("to_voxels"))
    answer_dialog(rec, [0.05])
    item.trigger()
    rec.pump(0.4)
    rec.say("… a voxel map, in a new tab", 1.6)
    rec.say("Convert ▸ To 2D occupancy grid")
    item = menu_pick(rec, "Convert", window.tr_("to_grid"))
    answer_dialog(rec, [0.3, 1.9])
    item.trigger()
    rec.pump(0.4)
    rec.say("… and a ROS 2D occupancy grid", 1.6)
    window.tabs.setCurrentIndex(1)
    rec.pump(0.3)
    rec.say("Back again: the voxel map returns the cloud's own points")
    item = menu_pick(rec, "Convert", window.tr_("to_cloud"))
    item.trigger()
    rec.pump(0.4)
    rec.say("Every point at its exact position, with all its fields", 1.8)
    rec.write_gif(out)


def demo_frames(rec, out):
    editor = kitti(rec, labels=True, boxes=True)
    known = hand_boxes(editor)
    editor.timeline.slider.on_range(0, 0)
    rec.pump(0.5)
    low, high = around(list(known.values()), 8.0)
    show(editor, low, high, (-0.8, -1.0, 1.0))
    rec.start()
    rec.say("A folder of LiDAR scans opens as one sequence (KITTI raw, poses from the GPS/IMU)", 2.0)
    slider = editor.timeline.slider
    rec.say("Drag the timeline handles: frames 0–9 merged by their poses")
    rec.glide(rec.in_window(slider, QtCore.QPointF(slider._x(0), slider.height() / 2)), 8)
    rec.glide(rec.in_window(slider, QtCore.QPointF(slider._x(9), slider.height() / 2)), 10)
    slider.on_range(0, 9)
    rec.pump(0.4)
    show(editor, low - [10, 10, 0], high + [10, 10, 0], (-0.8, -1.0, 1.0))
    rec.hold(1.6)
    rec.say("Click the strip, then → slides the range by its own width")
    rec.ripple = 4
    slider.setFocus(QtCore.Qt.MouseFocusReason)
    for _ in range(3):
        QtTest.QTest.keyClick(slider, QtCore.Qt.Key_Right)
        rec.pump(0.3)
        rec.hold(0.9)
    rec.say("One scan at a time, with the view fixed to the LiDAR")
    editor.timeline.anchor.setCurrentIndex(editor.timeline.anchor.findData("lidar"))
    slider.on_range(40, 40)
    rec.pump(0.3)
    centre = editor.sequence.poses[40][:3, 3]
    show(editor, centre - [22, 22, 3], centre + [22, 22, 3], (-0.5, -1.0, 1.1))
    for _ in range(30):
        rec.shortcut(".")
        rec.pump(0.05)
        rec.frame(2)
    rec.hold(0.8)
    rec.write_gif(out)


def main(out_dir):
    global KITTI
    from mapbarber.app import launch
    os.makedirs(out_dir, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="mapbarber_demo_")
    for name in os.listdir(EXAMPLES):
        shutil.copy(os.path.join(EXAMPLES, name), workdir)
    shutil.copy(os.path.join(DEMO, "office_octomap.bt"), workdir)
    app, window = launch(None, "en")
    window.resize(*WINDOW_SIZE)
    recorder = Recorder(app, window, workdir)
    recorder.pump(1.0)
    demos = (("overview.gif", demo_overview), ("voxel.gif", demo_voxels), ("cloud.gif", demo_cloud),
             ("grid.gif", demo_grid), ("labeling.gif", demo_labeling), ("smart_pick.gif", demo_smart_pick),
             ("boxes.gif", demo_boxes), ("auto_labeling.webp", demo_auto_labeling),
             ("conversion.gif", demo_conversion), ("frames.gif", demo_frames))
    KITTI_DEMOS = {"labeling.gif", "smart_pick.gif", "boxes.gif", "auto_labeling.webp", "frames.gif"}
    options = [arg for arg in sys.argv[2:] if arg.startswith("--kitti=")]
    KITTI = options[0].split("=", 1)[1] if options else None
    selected = [arg for arg in sys.argv[2:] if not arg.startswith("--")] or [name for name, _ in demos]
    if KITTI is None:
        selected = [name for name in selected if name not in KITTI_DEMOS]
    for name, demo in demos:
        if name in selected:
            window.close_all(ask=False)
            recorder.pump(0.3)
            demo(recorder, os.path.join(out_dir, name))
    for editor in window.documents:
        editor.mark_saved()
    window.close()
    shutil.rmtree(workdir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
