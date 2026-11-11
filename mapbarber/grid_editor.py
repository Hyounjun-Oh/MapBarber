"""Editor for 2D occupancy grids in the ROS map_server layout."""
import math

import numpy as np

from . import convert, grid
from .editor import Editor
from .formats import GRID, VOXEL
from .grid import FREE, OCCUPIED, UNKNOWN, GridMap
from .qt import QtCore, QtGui, QtWidgets
from .widgets import RANGE_LIMIT, ask_numbers, button, int_spin, set_quietly, spin

Qt = QtCore.Qt
STATE_RGB = np.array([[250, 250, 250], [20, 20, 24], [128, 132, 140]], np.uint8)
STATES = ((OCCUPIED, "state_occupied", "O"), (FREE, "state_free", "F"), (UNKNOWN, "state_unknown", "U"))
TOOL_PEN = {"pen", "line", "rectangle"}
DEFAULTS = {"brush": 1, "state": OCCUPIED, "speckle": 4}


def cosmetic_pen(rgb, width=1.5, style=Qt.SolidLine):
    pen = QtGui.QPen(QtGui.QColor(*rgb))
    pen.setCosmetic(True)
    pen.setWidthF(width)
    pen.setStyle(style)
    return pen


class MapItem(QtWidgets.QGraphicsItem):
    """Draws only the exposed part of the grid, so large maps repaint quickly while painting."""

    def __init__(self):
        super().__init__()
        self.rgb = np.zeros((1, 1, 3), np.uint8)
        self.setFlag(QtWidgets.QGraphicsItem.ItemUsesExtendedStyleOption, True)

    def set_image(self, rgb):
        if rgb.shape != self.rgb.shape:
            self.prepareGeometryChange()
        self.rgb = rgb
        self.update()

    def boundingRect(self):
        return QtCore.QRectF(0, 0, self.rgb.shape[1], self.rgb.shape[0])

    def paint(self, painter, option, widget=None):
        area = option.exposedRect.intersected(self.boundingRect())
        x0, y0 = max(int(math.floor(area.left())), 0), max(int(math.floor(area.top())), 0)
        x1, y1 = min(int(math.ceil(area.right())), self.rgb.shape[1]), min(int(math.ceil(area.bottom())), self.rgb.shape[0])
        if x1 <= x0 or y1 <= y0:
            return
        block = np.ascontiguousarray(self.rgb[y0:y1, x0:x1])
        data = block.tobytes()
        image = QtGui.QImage(data, x1 - x0, y1 - y0, 3 * (x1 - x0), QtGui.QImage.Format_RGB888)
        painter.drawImage(QtCore.QRectF(x0, y0, x1 - x0, y1 - y0), image)


class Canvas(QtWidgets.QGraphicsView):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setBackgroundBrush(QtGui.QColor(26, 28, 33))
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setRenderHint(QtGui.QPainter.Antialiasing, False)
        self._pan = None

    def wheelEvent(self, event):
        factor = 1.2 ** (event.angleDelta().y() / 120.0)
        self.scale(factor, factor)

    def _scene_point(self, event):
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        return self.mapToScene(position), position

    def mousePressEvent(self, event):
        point, position = self._scene_point(event)
        panning = event.button() in (Qt.MiddleButton, Qt.RightButton) or (
            event.button() == Qt.LeftButton and self.editor.tool == "view")
        if panning:
            self._pan = position
            self.setCursor(Qt.ClosedHandCursor)
        elif event.button() == Qt.LeftButton:
            self.editor.press(point)

    def mouseMoveEvent(self, event):
        point, position = self._scene_point(event)
        if self._pan is not None:
            delta = position - self._pan
            self._pan = position
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        self.editor.move(point, bool(event.buttons() & Qt.LeftButton))

    def mouseReleaseEvent(self, event):
        point, _ = self._scene_point(event)
        if self._pan is not None:
            self._pan = None
            self.editor.set_tool(self.editor.tool)
        elif event.button() == Qt.LeftButton:
            self.editor.release(point)


class GridEditor(Editor):
    kind = GRID
    tools = (("view", "1"), ("pen", "2"), ("line", "3"), ("rectangle", "4"), ("fill", "5"))
    export_filters = (("ROS map, YAML + PGM", "yaml"), ("ROS map, YAML + PNG", "png"), ("PGM image + YAML", "pgm"))

    def __init__(self, window):
        super().__init__(window)
        self.map = GridMap(np.full((1, 1), UNKNOWN, np.uint8))
        self.panel_values = dict(DEFAULTS)
        self.canvas = Canvas(self)
        self.widget = self.canvas
        scene = self.canvas.scene()
        self.item = MapItem()
        scene.addItem(self.item)
        self.hover = scene.addRect(QtCore.QRectF(), cosmetic_pen((255, 210, 40)))
        self.preview_line = scene.addLine(QtCore.QLineF(), cosmetic_pen((255, 210, 40), 2.0, Qt.DashLine))
        self.preview_rect = scene.addRect(QtCore.QRectF(), cosmetic_pen((255, 210, 40), 2.0, Qt.DashLine))
        self.axis_x = scene.addLine(QtCore.QLineF(), cosmetic_pen((230, 60, 50), 3.0))
        self.axis_y = scene.addLine(QtCore.QLineF(), cosmetic_pen((60, 200, 80), 3.0))
        for item in (self.hover, self.preview_line, self.preview_rect):
            item.setZValue(3)
            item.hide()
        self._before = None
        self._start = None
        self._last = None

    @property
    def dirty(self):
        return self.map.dirty

    def load(self, path):
        self.set_document(grid.load(path), path, None)

    def set_document(self, payload, path=None, fmt=None):
        self.map = payload
        self.path, self.format = path, fmt
        self.redraw()
        self.sync_panel()

    def save(self, path, fmt=None):
        grid.save(path, self.map)
        self.map.mark_saved()
        self.changed()

    def undo(self):
        if self.map.undo():
            self.redraw()
            self.sync_panel()

    def redo(self):
        if self.map.redo():
            self.redraw()
            self.sync_panel()

    def summary(self):
        occupied, free, unknown = self.map.counts()[OCCUPIED], self.map.counts()[FREE], self.map.counts()[UNKNOWN]
        return self.tr("grid_counts", w=self.map.shape[1], h=self.map.shape[0], o=occupied, f=free, u=unknown,
                       res=f"{self.map.resolution:g}")

    def build_panel(self):
        t, values, W = self.tr, self.panel_values, QtWidgets
        panel = W.QWidget()
        layout = W.QVBoxLayout(panel)

        group = W.QGroupBox(t("paint_with"))
        column = W.QVBoxLayout(group)
        self.state_buttons = W.QButtonGroup(group)
        for value, key, shortcut in STATES:
            radio = W.QRadioButton(f"{t(key)}  ({shortcut})")
            radio.setChecked(value == values["state"])
            self.state_buttons.addButton(radio, value)
            column.addWidget(radio)
        layout.addWidget(group)

        group = W.QGroupBox(t("brush"))
        form = W.QFormLayout(group)
        self.brush = int_spin(1, 201, values["brush"], t("cells"))
        self.brush.setToolTip(t("grid_brush_tip"))
        form.addRow(t("brush_size"), self.brush)
        layout.addWidget(group)

        group = W.QGroupBox(t("speckles"))
        form = W.QFormLayout(group)
        self.speckle = int_spin(1, 1_000_000, values["speckle"], t("cells"))
        form.addRow(t("island_size"), self.speckle)
        form.addRow(button(t("clear_speckles"), self.clear_speckles, t("speckles_tip")))
        layout.addWidget(group)

        group = W.QGroupBox(t("map_info"))
        form = W.QFormLayout(group)
        self.resolution = spin(1e-4, 100.0, self.map.resolution, 0.01, decimals=4)
        self.origin_x = spin(-1e6, 1e6, self.map.origin[0], 0.1)
        self.origin_y = spin(-1e6, 1e6, self.map.origin[1], 0.1)
        self.origin_yaw = spin(-math.pi, math.pi, self.map.origin[2], 0.01, decimals=4)
        form.addRow(t("resolution_label"), self.resolution)
        form.addRow(t("origin_x"), self.origin_x)
        form.addRow(t("origin_y"), self.origin_y)
        form.addRow(t("origin_yaw"), self.origin_yaw)
        form.addRow(button(t("apply"), self.apply_info))
        form.addRow(button(t("trim"), self.trim, t("trim_tip")))
        layout.addWidget(group)

        layout.addStretch(1)
        legend = W.QLabel(t("grid_legend"))
        legend.setWordWrap(True)
        legend.setStyleSheet("color: gray;")
        layout.addWidget(legend)
        return panel

    def store_panel(self):
        if self.panel_alive:
            self.panel_values = {"brush": self.brush.value(), "state": self.paint_state(), "speckle": self.speckle.value()}

    def sync_panel(self):
        if self.panel_alive:
            for box, value in zip((self.resolution, self.origin_x, self.origin_y, self.origin_yaw),
                                  (self.map.resolution, *self.map.origin)):
                set_quietly(box, value)

    def paint_state(self):
        return self.state_buttons.checkedId() if self.panel_alive else self.panel_values["state"]

    def set_state(self, value):
        self.state_buttons.button(value).setChecked(True)

    def extra_actions(self):
        return [(self.tr(key), shortcut, lambda v=value: self.set_state(v)) for value, key, shortcut in STATES]

    def view_actions(self):
        return [(self.tr("view_fit"), self.fit)]

    def conversions(self):
        return [(self.tr("to_voxels"), self.to_voxels)]

    def activate(self):
        self.fit()

    def redraw(self):
        self.item.set_image(STATE_RGB[np.flipud(self.map.cells)])
        height, width = self.map.shape
        margin = max(width, height) * 0.1
        self.canvas.scene().setSceneRect(-margin, -margin, width + 2 * margin, height + 2 * margin)
        self._draw_axes()
        self.changed()

    def _redraw_rows(self, rows, columns):
        r0, r1 = max(min(rows), 0), min(max(rows) + 1, self.map.shape[0])
        c0, c1 = max(min(columns), 0), min(max(columns) + 1, self.map.shape[1])
        if r1 <= r0 or c1 <= c0:
            return
        height = self.map.shape[0]
        self.item.rgb[height - r1:height - r0, c0:c1] = STATE_RGB[np.flipud(self.map.cells[r0:r1, c0:c1])]
        self.item.update(QtCore.QRectF(c0, height - r1, c1 - c0, r1 - r0))

    def _scene_of_world(self, x, y):
        c, s = math.cos(self.map.origin[2]), math.sin(self.map.origin[2])
        dx, dy = x - self.map.origin[0], y - self.map.origin[1]
        column = (c * dx + s * dy) / self.map.resolution
        row = (-s * dx + c * dy) / self.map.resolution
        return QtCore.QPointF(column, self.map.shape[0] - row)

    def _draw_axes(self):
        length = max(0.5, 12 * self.map.resolution)
        origin = self._scene_of_world(0.0, 0.0)
        self.axis_x.setLine(QtCore.QLineF(origin, self._scene_of_world(length, 0.0)))
        self.axis_y.setLine(QtCore.QLineF(origin, self._scene_of_world(0.0, length)))

    def fit(self):
        height, width = self.map.shape
        self.canvas.fitInView(QtCore.QRectF(0, 0, width, height), Qt.KeepAspectRatio)

    def set_tool(self, name):
        self.tool = name
        self.hover.hide()
        self.canvas.setCursor(Qt.OpenHandCursor if name == "view" else Qt.CrossCursor)

    def _cell(self, point):
        return int(math.floor(self.map.shape[0] - point.y())), int(math.floor(point.x()))

    def _finish(self, label):
        changed = self.map.commit(self._before)
        self._before = None
        self.changed()
        if changed:
            self.status(self.tr("status_painted", what=label, n=changed))

    def press(self, point):
        if self.tool == "view":
            return
        row, column = self._cell(point)
        state = self.paint_state()
        self._before = self.map.snapshot()
        self._start = self._last = (row, column)
        if self.tool == "pen":
            self.map.stamp(row, column, self.brush.value(), state)
            half = self.brush.value()
            self._redraw_rows((row - half, row + half), (column - half, column + half))
        elif self.tool == "fill":
            self.map.flood(row, column, state)
            self.redraw()
            self._finish(self.tr("tool_fill"))

    def move(self, point, pressed):
        row, column = self._cell(point)
        if self.tool != "view":
            self._show_hover(row, column)
        if not pressed or self._before is None:
            return
        size = self.brush.value()
        if self.tool == "pen":
            self.map.line(self._last, (row, column), size, self.paint_state())
            rows, columns = (self._last[0], row), (self._last[1], column)
            self._redraw_rows((min(rows) - size, max(rows) + size), (min(columns) - size, max(columns) + size))
            self._last = (row, column)
        elif self.tool == "line":
            height = self.map.shape[0]
            self.preview_line.setLine(self._start[1] + 0.5, height - self._start[0] - 0.5, column + 0.5, height - row - 0.5)
            self.preview_line.show()
        elif self.tool == "rectangle":
            height = self.map.shape[0]
            r0, r1 = sorted((self._start[0], row))
            c0, c1 = sorted((self._start[1], column))
            self.preview_rect.setRect(QtCore.QRectF(c0, height - r1 - 1, c1 - c0 + 1, r1 - r0 + 1))
            self.preview_rect.show()

    def release(self, point):
        if self._before is None:
            return
        row, column = self._cell(point)
        if self.tool == "line":
            self.preview_line.hide()
            self.map.line(self._start, (row, column), self.brush.value(), self.paint_state())
            self.redraw()
        elif self.tool == "rectangle":
            self.preview_rect.hide()
            self.map.rectangle(self._start, (row, column), self.paint_state())
            self.redraw()
        self._finish(self.tool_label(self.tool))

    def _show_hover(self, row, column):
        size = self.brush.value() if self.tool in TOOL_PEN else 1
        half = size // 2
        height = self.map.shape[0]
        self.hover.setRect(QtCore.QRectF(column - half, height - (row - half + size), size, size))
        self.hover.show()
        inside = 0 <= row < self.map.shape[0] and 0 <= column < self.map.shape[1]
        x, y = self.map.world(row, column)
        state = self.tr(STATES[[OCCUPIED, FREE, UNKNOWN].index(int(self.map.cells[row, column]))][1]) if inside else "—"
        self.status(self.tr("grid_hover", c=column, r=row, x=x, y=y, state=state), 0)

    def clear_speckles(self):
        before = self.map.snapshot()
        cells, groups = self.map.clear_speckles(self.speckle.value())
        self.map.commit(before)
        self.redraw()
        self.status(self.tr("status_speckles", n=cells, m=groups), 10000)

    def trim(self):
        before = self.map.snapshot()
        if self.map.trim():
            self.map.commit(before)
            self.redraw()
            self.sync_panel()
            self.fit()
            self.status(self.tr("status_trimmed", w=self.map.shape[1], h=self.map.shape[0]))
        else:
            self.status(self.tr("status_trim_none"))

    def apply_info(self):
        before = self.map.snapshot()
        self.map.resolution = self.resolution.value()
        self.map.origin = (self.origin_x.value(), self.origin_y.value(), self.origin_yaw.value())
        if self.map.commit(before):
            self._draw_axes()
            self.changed()

    def to_voxels(self):
        answer = ask_numbers(self.window, self.tr("extrude_title"), [(self.tr("wall_height"), 1.0, 1e-3, RANGE_LIMIT, 3)])
        if answer is None:
            return None
        return VOXEL, convert.grid_to_voxels(self.map, answer[0])
