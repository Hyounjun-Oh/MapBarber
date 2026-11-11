"""Record the README animations by driving the real application and capturing every frame.

    python tools/record_demo.py docs/        (needs ffmpeg and a display)
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

    def pump(self, seconds=0.05):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()

    def start(self):
        self.frame_dir = tempfile.mkdtemp(prefix="frames_", dir=self.workdir)
        self.frames = 0

    def compose(self):
        image = self.window.capture().convertToFormat(QtGui.QImage.Format_RGB32)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        origin = self.window.mapToGlobal(QtCore.QPoint(0, 0))
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if widget is self.window or not widget.isVisible():
                continue
            if isinstance(widget, (QtWidgets.QMenu, QtWidgets.QDialog)):
                corner = widget.mapToGlobal(QtCore.QPoint(0, 0)) - origin
                painter.drawPixmap(corner, widget.grab())
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
        self.glide(self.in_window(widget), steps)
        self.ripple = 4
        QtTest.QTest.mouseClick(widget, Qt.LeftButton)
        self.frame(3)

    def shortcut(self, sequence):
        wanted = QtGui.QKeySequence(sequence)
        for action in self.window.actions():
            if action.shortcut() == wanted and action.isEnabled():
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

    def canvas_drag(self, cells, steps_each=6):
        viewport = self.window.editor.canvas.viewport()
        first = self.cell_to_window(*cells[0])
        self.glide(first, 8, lambda p: QtTest.QTest.mouseMove(viewport, self.canvas_local(p)))
        QtTest.QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, self.canvas_local(first))
        self.ripple = 4
        for cell in cells[1:]:
            target = self.cell_to_window(*cell)
            self.glide(target, steps_each, lambda p: QtTest.QTest.mouseMove(viewport, self.canvas_local(p), 1))
        QtTest.QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, self.canvas_local(self.cursor))
        self.frame(3)

    def canvas_click(self, row, column):
        self.canvas_drag([(row, column)])

    def write_gif(self, path, width=960):
        palette = (f"fps={FPS},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];"
                   "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i",
                        os.path.join(self.frame_dir, "%05d.png"), "-vf", palette, path], check=True)
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
        rec.say(caption, 2.2)
    window.open(os.path.join(rec.workdir, "room.bt"))
    rec.pump(0.3)
    rec.say("Convert ▸ To 2D occupancy grid", 0.6)
    item = menu_pick(rec, "Convert", "To 2D occupancy grid…")
    rec.say("Pick the height band to project")
    answer_dialog(rec, [0.3, 1.9])
    item.trigger()
    rec.pump(0.3)
    rec.say("The voxels become a ROS occupancy grid", 2.2)
    rec.say("Language ▸ 한국어")
    window.set_language("ko")
    rec.pump(0.3)
    rec.hold(1.6)
    window.set_language("en")
    rec.write_gif(out)


def demo_voxels(rec, out):
    window = rec.window
    window.open(os.path.join(rec.workdir, "room.bt"))
    rec.pump(0.4)
    editor = window.editor
    rec.start()
    rec.say("A voxel map with sensor noise", 1.2)
    w, h = editor.viewport.renderer.GetSize()
    centre = rec.vtk_to_window(w * 0.5, h * 0.5)
    rec.say("Drag to orbit")
    rec.vtk_drag(centre, centre + QtCore.QPointF(-120, 30), 18)
    rec.hold(0.4)
    button = rec.panel_button("Select islands")
    rec.say("Select islands finds floating specks")
    rec.click_widget(button)
    rec.hold(1.4)
    rec.say("Delete removes them")
    rec.shortcut("Delete")
    rec.hold(1.2)

    rec.say("Shift + drag around the ghost blob")
    window.set_tool("select")
    corners = [rec.project((x, y, z)) for x in (3.6, 4.0) for y in (0.8, 1.1) for z in (1.5, 1.65)]
    xs, ys = [p.x() for p in corners], [p.y() for p in corners]
    start = QtCore.QPointF(min(xs) - 18, min(ys) - 18)
    end = QtCore.QPointF(max(xs) + 18, max(ys) + 18)
    rec.vtk_drag(start, end, 14, shift=True)
    rec.hold(1.0)
    rec.shortcut("Delete")
    rec.say("Gone", 0.8)

    rec.say("Box ▸ Fill patches the hole in the wall")
    rec.scroll_panel_to(rec.panel_button("Fill"))
    editor.set_box((5.94, 1.6, 0.9), (6.0, 2.0, 1.3))
    window.editor.look_from((1, -0.2, 0.25), (0, 0, 1))
    rec.hold(0.8)
    rec.click_widget(rec.panel_button("Fill"))
    rec.hold(1.4)
    editor.show_box.setChecked(False)

    window.editor.look_from((1, -1, 0.8), (0, 0, 1))
    rec.say("Add tool: click a face to grow a layer")
    window.set_tool("add")
    editor.brush.setValue(3)
    target = rec.project((2.7, 1.9, 0.76))
    for _ in range(3):
        rec.vtk_click(target, 6)
        target = target + QtCore.QPointF(0, -9)
    rec.hold(0.8)
    rec.say("Erase tool with a 3-cell brush")
    window.set_tool("delete")
    for x in (1.10, 1.15, 1.20):
        rec.vtk_click(rec.project((x, 3.0, 2.38)), 6)
    rec.hold(0.8)
    rec.say("Ctrl+S writes a standard OctoMap .bt")
    window.save()
    rec.hold(1.6)
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
    rec.hold(1.0)

    editor.look_from((1, -1, 0.8), (0, 0, 1))
    rec.say("Colour by any field")
    rec.glide(rec.in_window(editor.colour_box), 8)
    editor.colour_box.setCurrentIndex(editor.colour_box.findData("intensity"))
    rec.ripple = 4
    rec.hold(1.4)
    rec.say("Thin out to a 5 cm grid")
    rec.scroll_panel_to(rec.panel_button("Thin out"))
    rec.click_widget(rec.panel_button("Thin out"))
    rec.hold(1.4)
    rec.say("Ctrl+Z undoes it")
    rec.shortcut("Ctrl+Z")
    rec.hold(1.4)
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
    rec.hold(1.2)

    rec.say("Line tool: close a doorway")
    window.set_tool("line")
    editor.brush.setValue(3)
    rec.canvas_drag([(151, 330), (151, 352)], 14)
    rec.hold(0.8)

    rec.say("Pen: sketch an obstacle")
    window.set_tool("pen")
    editor.brush.setValue(2)
    loop = [(220 + 18 * math.sin(a), 300 + 30 * math.cos(a)) for a in np.linspace(0, 2 * math.pi, 14)]
    rec.canvas_drag([(int(r), int(c)) for r, c in loop], 3)
    rec.hold(0.6)

    rec.say("Rectangle: mark a keep-out zone")
    window.set_tool("rectangle")
    rec.canvas_drag([(80, 250), (110, 330)], 12)
    rec.hold(0.8)

    rec.say("Fill with free space to repair the unknown hole")
    editor.set_state(0)
    window.set_tool("fill")
    rec.canvas_click(65, 67)
    rec.hold(1.2)

    rec.say("Trim the unknown border (origin follows)")
    rec.click_widget(rec.panel_button("Trim unknown border"))
    rec.hold(1.6)
    rec.say("Ctrl+S writes the image and its YAML")
    window.save()
    rec.hold(1.4)
    rec.write_gif(out)


def main(out_dir):
    from mapbarber.app import launch
    os.makedirs(out_dir, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="mapbarber_demo_")
    for name in os.listdir(EXAMPLES):
        shutil.copy(os.path.join(EXAMPLES, name), workdir)
    app, window = launch(None, "en")
    window.resize(*WINDOW_SIZE)
    recorder = Recorder(app, window, workdir)
    recorder.pump(1.0)
    demos = (("overview.gif", demo_overview), ("voxel.gif", demo_voxels), ("cloud.gif", demo_cloud),
             ("grid.gif", demo_grid))
    selected = sys.argv[2:] or [name for name, _ in demos]
    for name, demo in demos:
        if name in selected:
            for editor in window.editors.values():
                editor.map.mark_saved() if hasattr(editor, "map") else editor.cloud.mark_saved()
            demo(recorder, os.path.join(out_dir, name))
    for editor in window.editors.values():
        editor.map.mark_saved() if hasattr(editor, "map") else editor.cloud.mark_saved()
    window.close()
    shutil.rmtree(workdir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
