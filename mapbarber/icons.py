"""Small line icons drawn with QPainter, so they follow the palette and need no image files."""
from .qt import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
P, L, R = QtCore.QPointF, QtCore.QLineF, QtCore.QRectF

BLUE, PINK, AMBER, GOLD, RED, GREEN, TEAL, VIOLET = ("#4f9cf7", "#ff4fc8", "#f2b632", "#ffd126", "#ef5350", "#4cc26a",
                                                    "#35c2b0", "#9b7bf0")
ACCENTS = {
    "brush": BLUE, "paint_with": BLUE, "rectangle": PINK, "islands": PINK, "noise_filters": PINK, "box": AMBER,
    "ruler": GOLD, "slice": VIOLET, "visible_range": TEAL, "display": TEAL, "downsample": RED, "speckles": RED,
    "map_info": GREEN, "labels": GREEN, "smart": VIOLET, "review": GOLD, "instances": AMBER, "frames": BLUE,
    "tool_label": GREEN, "tool_smart": VIOLET, "ground": GREEN, "bbox": AMBER, "kind_voxel": AMBER, "kind_cloud": TEAL, "kind_grid": BLUE,
    "tool_view": BLUE, "tool_select": PINK, "tool_delete": RED, "tool_add": GREEN, "tool_measure": GOLD,
    "tool_pen": BLUE, "tool_line": BLUE, "tool_rectangle": BLUE, "tool_fill": GREEN,
    "open": AMBER, "save": BLUE, "undo": TEAL, "redo": TEAL,
    "role_danger": RED, "role_add": GREEN, "role_select": PINK,
}


def _poly(points):
    return QtGui.QPolygonF([P(x, y) for x, y in points])


def _brush(p, c, a):
    p.drawLine(L(20, 3, 11, 12))
    p.setBrush(a)
    p.drawEllipse(R(3, 12, 9, 9))


def _marquee(p, c, a):
    pen = QtGui.QPen(a, 2, Qt.DashLine)
    p.setPen(pen)
    p.drawRect(R(3.5, 5, 17, 14))


def _islands(p, c, a):
    p.drawRect(R(3, 10, 10, 10))
    p.setPen(Qt.NoPen)
    p.setBrush(a)
    for x, y, s in ((15, 3, 4), (18, 11, 3), (9, 3, 3), (16, 17, 4)):
        p.drawRect(R(x, y, s, s))


def _box(p, c, a):
    p.setPen(QtGui.QPen(a, 2))
    p.drawRect(R(3, 9, 12, 12))
    p.drawPolyline(_poly([(3, 9), (9, 3), (21, 3), (21, 15), (15, 21)]))
    p.drawLine(L(15, 9, 21, 3))


def _ruler(p, c, a):
    p.save()
    p.translate(12, 12)
    p.rotate(-35)
    p.setPen(QtGui.QPen(a, 2))
    p.drawRect(R(-10, -4, 20, 8))
    for x in (-6, -2, 2, 6):
        p.drawLine(L(x, -4, x, 0 if x in (-2, 6) else -1.5))
    p.restore()


def _slice(p, c, a):
    p.drawRect(R(6, 3, 12, 7))
    p.setPen(QtGui.QPen(c, 2, Qt.DotLine))
    p.drawRect(R(6, 14, 12, 7))
    p.setPen(QtGui.QPen(a, 2.5))
    p.drawLine(L(2, 12, 22, 12))


def _range(p, c, a):
    p.drawLine(L(4, 5, 4, 19))
    p.drawLine(L(20, 5, 20, 19))
    p.setPen(QtGui.QPen(a, 2))
    p.drawLine(L(7, 12, 17, 12))
    p.drawPolyline(_poly([(10, 9), (7, 12), (10, 15)]))
    p.drawPolyline(_poly([(14, 9), (17, 12), (14, 15)]))


def _eye(p, c, a):
    path = QtGui.QPainterPath(P(2, 12))
    path.quadTo(P(12, 2), P(22, 12))
    path.quadTo(P(12, 22), P(2, 12))
    p.drawPath(path)
    p.setBrush(a)
    p.setPen(Qt.NoPen)
    p.drawEllipse(P(12, 12), 3.5, 3.5)


def _funnel(p, c, a):
    p.setPen(QtGui.QPen(a, 2))
    p.drawPolygon(_poly([(3, 4), (21, 4), (14, 12), (14, 19), (10, 21), (10, 12)]))


def _thin(p, c, a):
    p.setPen(Qt.NoPen)
    for row in range(3):
        for column in range(3):
            keep = (row + column) % 2 == 0
            color = QtGui.QColor(a if keep else c)
            color.setAlphaF(1.0 if keep else 0.3)
            p.setBrush(color)
            p.drawEllipse(P(5 + 7 * column, 5 + 7 * row), 2.4, 2.4)


def _states(p, c, a):
    p.setBrush(c)
    p.drawRect(R(3, 8, 6, 8))
    p.setBrush(Qt.NoBrush)
    p.drawRect(R(9, 8, 6, 8))
    grey = QtGui.QColor(c)
    grey.setAlphaF(0.45)
    p.setBrush(grey)
    p.drawRect(R(15, 8, 6, 8))


def _speckles(p, c, a):
    p.setPen(Qt.NoPen)
    p.setBrush(a)
    for x, y, r in ((5, 6, 1.6), (12, 4, 1.2), (18, 8, 1.8), (8, 13, 1.3), (15, 15, 1.5), (5, 19, 1.4), (19, 19, 1.2)):
        p.drawEllipse(P(x, y), r, r)


def _info(p, c, a):
    p.setPen(QtGui.QPen(a, 2))
    p.drawEllipse(P(12, 12), 9, 9)
    p.drawLine(L(12, 11, 12, 17))
    p.setBrush(a)
    p.drawEllipse(P(12, 7.5), 0.8, 0.8)


def _move(p, c, a):
    p.drawLine(L(12, 3, 12, 21))
    p.drawLine(L(3, 12, 21, 12))
    for points in (((9, 6), (12, 3), (15, 6)), ((9, 18), (12, 21), (15, 18)), ((6, 9), (3, 12), (6, 15)),
                   ((18, 9), (21, 12), (18, 15))):
        p.drawPolyline(_poly(points))


def _cursor(p, c, a):
    p.setBrush(a)
    p.setPen(QtGui.QPen(c, 1.4))
    p.drawPolygon(_poly([(5, 3), (5, 19), (9.5, 15), (12.5, 21.5), (15, 20.3), (12, 14), (18, 14)]))


def _eraser(p, c, a):
    p.setBrush(a)
    p.drawPolygon(_poly([(3, 14), (8, 19), (13, 19), (9, 8)]))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(_poly([(9, 8), (14, 3), (21, 10), (13, 19), (8, 19), (3, 14)]))
    p.drawLine(L(8, 21, 21, 21))


def _plus(p, c, a):
    p.drawRoundedRect(R(3, 3, 18, 18), 3, 3)
    p.setPen(QtGui.QPen(a, 2.6))
    p.drawLine(L(12, 7, 12, 17))
    p.drawLine(L(7, 12, 17, 12))


def _pencil(p, c, a):
    p.drawPolygon(_poly([(4, 20), (6, 14), (16, 4), (20, 8), (10, 18)]))
    p.setBrush(a)
    p.setPen(Qt.NoPen)
    p.drawPolygon(_poly([(4, 20), (6, 14), (10, 18)]))


def _line(p, c, a):
    p.drawLine(L(5, 19, 19, 5))
    p.setBrush(a)
    p.setPen(Qt.NoPen)
    p.drawEllipse(P(5, 19), 2.6, 2.6)
    p.drawEllipse(P(19, 5), 2.6, 2.6)


def _rect(p, c, a):
    fill = QtGui.QColor(a)
    fill.setAlphaF(0.45)
    p.setBrush(fill)
    p.drawRect(R(3.5, 6, 17, 12))


def _drop(p, c, a):
    path = QtGui.QPainterPath(P(12, 3))
    path.cubicTo(P(6, 10), P(5, 13), P(5, 15))
    path.cubicTo(P(5, 23), P(19, 23), P(19, 15))
    path.cubicTo(P(19, 13), P(18, 10), P(12, 3))
    p.setBrush(a)
    p.drawPath(path)


def _folder(p, c, a):
    p.setPen(QtGui.QPen(a, 2))
    p.drawPolygon(_poly([(3, 6), (9, 6), (11, 8), (21, 8), (21, 19), (3, 19)]))


def _floppy(p, c, a):
    p.drawPolygon(_poly([(4, 4), (17, 4), (20, 7), (20, 20), (4, 20)]))
    p.setBrush(a)
    p.drawRect(R(8, 13, 8, 7))
    p.drawLine(L(8, 4, 8, 9))
    p.drawLine(L(8, 9, 15, 9))
    p.drawLine(L(15, 9, 15, 4))


def _undo(p, c, a, flip=False):
    if flip:
        p.translate(24, 0)
        p.scale(-1, 1)
    p.setPen(QtGui.QPen(a, 2))
    path = QtGui.QPainterPath(P(5, 10))
    path.lineTo(P(14, 10))
    path.cubicTo(P(22, 10), P(22, 19), P(14, 19))
    path.lineTo(P(8, 19))
    p.drawPath(path)
    p.drawPolyline(_poly([(9, 6), (5, 10), (9, 14)]))


def _redo(p, c, a):
    _undo(p, c, a, flip=True)


def _trash(p, c, a):
    p.setPen(QtGui.QPen(a, 2))
    p.drawLine(L(4, 7, 20, 7))
    p.drawLine(L(9, 7, 10, 4))
    p.drawLine(L(10, 4, 14, 4))
    p.drawLine(L(14, 4, 15, 7))
    p.drawPolygon(_poly([(6, 7), (7, 21), (17, 21), (18, 7)]))
    p.drawLine(L(10, 11, 10, 17))
    p.drawLine(L(14, 11, 14, 17))


def _plus_bare(p, c, a):
    p.setPen(QtGui.QPen(a, 3))
    p.drawLine(L(12, 4, 12, 20))
    p.drawLine(L(4, 12, 20, 12))


def _tag(p, c, a):
    p.drawPolygon(_poly([(3, 4), (12, 4), (21, 13), (13, 21), (3, 11)]))
    p.setBrush(a)
    p.setPen(Qt.NoPen)
    p.drawEllipse(P(8, 9), 2.2, 2.2)


def _wand(p, c, a):
    p.drawLine(L(4, 20, 14, 10))
    p.setPen(QtGui.QPen(a, 2))
    for x0, y0, x1, y1 in ((17, 2, 17, 6), (15, 4, 19, 4), (20, 9, 20, 13), (18, 11, 22, 11), (9, 3, 9, 5), (8, 4, 10, 4)):
        p.drawLine(L(x0, y0, x1, y1))


def _check(p, c, a):
    p.drawRect(R(3, 3, 18, 18))
    p.setPen(QtGui.QPen(a, 2.4))
    p.drawPolyline(_poly([(7, 12), (11, 16), (17, 8)]))


def _cubes(p, c, a):
    p.drawRect(R(3, 11, 9, 9))
    p.setBrush(a)
    p.drawRect(R(12, 4, 9, 9))


def _film(p, c, a):
    for x in (3, 9.5, 16):
        p.drawRect(R(x, 6, 5, 12))
    p.setPen(QtGui.QPen(a, 2))
    p.drawLine(L(3, 21, 21, 21))


def _bbox(p, c, a):
    p.drawPolygon(_poly([(3, 9), (13, 5), (21, 8), (21, 17), (11, 21), (3, 17)]))
    p.setPen(QtGui.QPen(a, 2))
    p.drawPolyline(_poly([(3, 9), (11, 12), (21, 8)]))
    p.drawLine(L(11, 12, 11, 21))


def _ground(p, c, a):
    p.drawPolyline(_poly([(9, 15), (12, 6), (15, 15)]))
    p.drawRect(R(14, 9, 6, 6))
    p.setPen(QtGui.QPen(a, 2.4))
    p.drawLine(L(2, 18, 22, 18))
    for x in (5, 10, 15, 20):
        p.drawLine(L(x, 18, x - 3, 22))


def _voxels(p, c, a):
    p.drawRect(R(3, 12, 8, 8))
    p.drawRect(R(11, 12, 8, 8))
    p.setBrush(a)
    p.drawRect(R(7, 4, 8, 8))


def _dots(p, c, a):
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    for x, y, r in ((5, 15, 1.6), (9, 10, 1.6), (13, 17, 1.6), (17, 8, 1.6), (19, 15, 1.6), (7, 20, 1.3), (14, 5, 1.3)):
        p.drawEllipse(P(x, y), r, r)
    p.setBrush(a)
    for x, y in ((11, 14), (16, 12), (9, 16)):
        p.drawEllipse(P(x, y), 2.2, 2.2)


def _cells(p, c, a):
    for i in range(3):
        for j in range(3):
            if (i, j) in ((0, 0), (1, 0), (2, 1)):
                p.save()
                p.setBrush(a)
                p.drawRect(R(3 + 6 * i, 3 + 6 * j, 6, 6))
                p.restore()
            else:
                p.drawRect(R(3 + 6 * i, 3 + 6 * j, 6, 6))


def _cube(p, x, y, size, pen=None, fill=None):
    """A small box drawn in perspective with its front face at (x, y)."""
    d = size * 0.4
    if pen is not None:
        p.setPen(pen)
    if fill is not None:
        p.save()
        p.setBrush(fill)
        p.drawRect(R(x, y + d, size, size))
        p.restore()
    p.drawRect(R(x, y + d, size, size))
    p.drawPolyline(_poly([(x, y + d), (x + d, y), (x + size + d, y), (x + size + d, y + size), (x + size, y + size + d)]))
    p.drawLine(L(x + size, y + d, x + size + d, y))


def _dot(p, colour, x, y, r=1.6, hollow=False):
    p.save()
    if hollow:
        p.setPen(QtGui.QPen(colour, 1.2))
        p.setBrush(Qt.NoBrush)
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(colour)
    p.drawEllipse(P(x, y), r, r)
    p.restore()


def _cross(p, colour, x, y, r=3.5, width=2.2):
    p.save()
    p.setPen(QtGui.QPen(colour, width, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(L(x - r, y - r, x + r, y + r))
    p.drawLine(L(x - r, y + r, x + r, y - r))
    p.restore()


def _arrow(p, colour, x0, y0, x1, y1, head=3.5, width=2.0):
    import math
    p.save()
    p.setPen(QtGui.QPen(colour, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(L(x0, y0, x1, y1))
    angle = math.atan2(y1 - y0, x1 - x0)
    for side in (2.5, -2.5):
        p.drawLine(L(x1, y1, x1 - head * math.cos(angle + side / 4 * math.pi / 2.2),
                     y1 - head * math.sin(angle + side / 4 * math.pi / 2.2)))
    p.restore()


def _small_tag(p, x, y, s=1.0):
    p.drawPolygon(_poly([(x, y), (x + 7 * s, y), (x + 12 * s, y + 5 * s), (x + 7 * s, y + 10 * s), (x, y + 10 * s)]))


def _i_clear_selection(p, c, a):
    p.setPen(QtGui.QPen(a, 2, Qt.DashLine))
    p.drawRect(R(3, 4, 15, 13))
    _cross(p, c, 17, 17, 3.5)


def _i_box_fit(p, c, a):
    for x, y in ((8, 10), (12, 8), (15, 13), (10, 15), (13, 16)):
        _dot(p, a, x, y, 1.5)
    for (x, y), (dx, dy) in (((3, 3), (1, 1)), ((21, 3), (-1, 1)), ((3, 21), (1, -1)), ((21, 21), (-1, -1))):
        p.drawLine(L(x, y, x + 5 * dx, y))
        p.drawLine(L(x, y, x, y + 5 * dy))


def _i_box_select(p, c, a):
    _cube(p, 3, 4, 13)
    for x, y in ((7, 13), (10, 16), (12, 12), (8, 18)):
        _dot(p, a, x, y, 1.6)


def _i_box_erase_in(p, c, a):
    _cube(p, 3, 4, 13)
    _cross(p, a, 9.5, 15, 3)


def _i_box_erase_out(p, c, a):
    _cube(p, 6, 6, 10)
    for x, y in ((3, 3), (21, 3), (3, 21), (21, 21)):
        _cross(p, a, x, y, 1.8, 1.6)


def _i_box_fill(p, c, a):
    _cube(p, 3, 4, 13, fill=a)


def _i_ruler_clear(p, c, a):
    p.save()
    p.translate(10, 12)
    p.rotate(-35)
    p.drawRect(R(-8, -3, 16, 6))
    p.restore()
    _cross(p, a, 18, 18, 3.2)


def _i_show_all(p, c, a):
    p.drawRect(R(9, 9, 6, 6))
    for x0, y0, x1, y1 in ((8, 8, 3, 3), (16, 8, 21, 3), (8, 16, 3, 21), (16, 16, 21, 21)):
        _arrow(p, a, x0, y0, x1, y1, 3)


def _i_ground_select(p, c, a):
    p.drawRect(R(9, 4, 6, 8))
    p.setPen(Qt.NoPen)
    p.setBrush(a)
    p.drawRect(R(2, 15, 20, 6))


def _i_ground_others(p, c, a):
    p.setPen(Qt.NoPen)
    p.setBrush(a)
    p.drawRect(R(8, 3, 8, 11))
    p.setPen(QtGui.QPen(c, 2))
    p.drawLine(L(2, 18, 22, 18))
    for x in (5, 10, 15, 20):
        p.drawLine(L(x, 18, x - 3, 22))


def _i_outliers(p, c, a):
    for x, y in ((5, 15), (8, 12), (9, 17), (12, 14), (7, 19), (11, 10)):
        _dot(p, c, x, y, 1.4)
    _dot(p, a, 19, 5, 2.2)
    p.setPen(QtGui.QPen(a, 1.4))
    p.drawEllipse(P(19, 5), 4, 4)


def _i_sparse(p, c, a):
    p.setPen(QtGui.QPen(a, 1.4, Qt.DashLine))
    p.drawEllipse(P(12, 12), 9, 9)
    for x, y in ((8, 9), (15, 14), (10, 16)):
        _dot(p, a, x, y, 1.8)


def _i_thin_out(p, c, a):
    for i in range(3):
        for j in range(3):
            x, y = 5 + 7 * i, 5 + 7 * j
            _dot(p, a if (i + j) % 2 == 0 else c, x, y, 2.0, hollow=(i + j) % 2 == 1)


def _i_islands_pick(p, c, a):
    p.drawRect(R(3, 10, 9, 10))
    p.setPen(Qt.NoPen)
    p.setBrush(a)
    for x, y, size in ((16, 4, 3), (19, 12, 3), (14, 17, 3)):
        p.drawRect(R(x, y, size, size))
    p.setPen(QtGui.QPen(a, 1.4, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(P(17.5, 10.5), 6, 8)


def _i_speckles_clear(p, c, a):
    for x, y in ((4, 5), (9, 3), (6, 10), (13, 7), (3, 15)):
        p.drawRect(R(x, y, 2, 2))
    p.save()
    p.translate(15, 15)
    p.rotate(-40)
    p.setPen(QtGui.QPen(a, 2))
    p.drawRect(R(-6, -3, 12, 6))
    p.restore()


def _i_apply(p, c, a):
    p.setPen(QtGui.QPen(a, 2.6))
    p.drawPolyline(_poly([(4, 13), (10, 19), (20, 6)]))


def _i_trim(p, c, a):
    p.drawPolyline(_poly([(6, 2), (6, 18), (22, 18)]))
    p.drawPolyline(_poly([(2, 6), (18, 6), (18, 22)]))
    p.setPen(QtGui.QPen(a, 2))
    p.drawRect(R(9, 9, 6, 6))


def _i_class_edit(p, c, a):
    _small_tag(p, 2, 4, 1.0)
    p.setPen(QtGui.QPen(a, 2.2))
    p.drawLine(L(10, 21, 21, 10))
    p.drawLine(L(10, 21, 9, 22))


def _i_class_remove(p, c, a):
    _small_tag(p, 2, 3, 1.1)
    p.setPen(QtGui.QPen(a, 2.6))
    p.drawLine(L(13, 19, 22, 19))


def _i_list_save(p, c, a):
    for y in (5, 10, 15):
        p.drawLine(L(3, y, 12, y))
    p.drawPolyline(_poly([(14, 15), (14, 21), (22, 21), (22, 15)]))
    _arrow(p, a, 18, 3, 18, 15, 3)


def _i_tag_clear(p, c, a):
    _small_tag(p, 2, 3, 1.1)
    _cross(p, a, 18, 18, 3.2)


def _i_solo(p, c, a):
    p.drawPath(_eye_path())
    _dot(p, a, 12, 12, 3.2)


def _eye_path():
    path = QtGui.QPainterPath()
    path.moveTo(2, 12)
    path.quadTo(12, 2, 22, 12)
    path.quadTo(12, 22, 2, 12)
    return path


def _i_select_class(p, c, a):
    p.setPen(QtGui.QPen(a, 2, Qt.DashLine))
    p.drawRect(R(2, 2, 20, 20))
    p.setPen(QtGui.QPen(c, 2))
    _small_tag(p, 6, 7, 0.9)


def _i_labels_open(p, c, a):
    p.drawPolyline(_poly([(2, 19), (2, 6), (8, 6), (10, 8), (20, 8), (20, 19), (2, 19)]))
    p.setPen(QtGui.QPen(a, 2))
    _small_tag(p, 8, 11, 0.6)


def _i_labels_save(p, c, a):
    p.drawPolyline(_poly([(3, 14), (3, 21), (21, 21), (21, 14)]))
    _arrow(p, a, 12, 3, 12, 16, 3.5)
    _dot(p, a, 17, 6, 1.8)


def _i_export(p, c, a):
    p.drawPolyline(_poly([(3, 12), (3, 21), (21, 21), (21, 12)]))
    _arrow(p, a, 12, 17, 12, 3, 3.5)


def _i_export_boxes(p, c, a):
    _cube(p, 2, 9, 10)
    _arrow(p, a, 13, 13, 21, 4, 3.5)


def _i_frames_show(p, c, a):
    for x in (2, 16):
        p.drawRect(R(x, 7, 6, 10))
    p.save()
    p.setPen(QtGui.QPen(a, 2))
    p.setBrush(QtGui.QColor(a.red(), a.green(), a.blue(), 90))
    p.drawRect(R(9, 5, 6, 14))
    p.restore()


def _i_poses(p, c, a):
    path = QtGui.QPainterPath()
    path.moveTo(3, 19)
    path.cubicTo(8, 4, 14, 22, 20, 6)
    p.save()
    p.setPen(QtGui.QPen(a, 2))
    p.drawPath(path)
    p.restore()
    for x, y in ((3, 19), (11.5, 13), (20, 6)):
        _dot(p, c, x, y, 2.0)


def _i_poses_off(p, c, a):
    path = QtGui.QPainterPath()
    path.moveTo(3, 19)
    path.cubicTo(8, 4, 14, 22, 20, 6)
    p.drawPath(path)
    p.setPen(QtGui.QPen(a, 2.4))
    p.drawLine(L(4, 4, 20, 20))


def _i_propagate(p, c, a):
    p.drawRect(R(2, 6, 7, 12))
    _dot(p, a, 5.5, 12, 2)
    _arrow(p, a, 10, 12, 15, 12, 3)
    p.drawRect(R(16, 4, 5, 7))
    p.drawRect(R(16, 13, 5, 7))


def _i_conflict(p, c, a):
    p.drawRect(R(2, 3, 11, 14))
    p.drawRect(R(7, 7, 11, 14))
    p.setPen(QtGui.QPen(a, 2.6))
    p.drawLine(L(20, 3, 20, 12))
    p.drawPoint(P(20, 17))


def _i_next_area(p, c, a):
    p.setPen(QtGui.QPen(c, 2, Qt.DashLine))
    p.drawRect(R(12, 5, 9, 14))
    _arrow(p, a, 2, 12, 10, 12, 3.5)


def _i_doubt(p, c, a):
    _small_tag(p, 2, 7, 1.0)
    p.setPen(QtGui.QPen(a, 2.2))
    path = QtGui.QPainterPath()
    path.moveTo(15, 6)
    path.cubicTo(15, 2, 22, 2, 22, 6)
    path.cubicTo(22, 9, 18.5, 9, 18.5, 12)
    p.drawPath(path)
    p.drawPoint(P(18.5, 16))


def _i_label_islands(p, c, a):
    _small_tag(p, 2, 8, 1.0)
    p.setPen(Qt.NoPen)
    p.setBrush(a)
    for x, y in ((17, 3), (20, 10), (16, 18)):
        p.drawEllipse(P(x, y), 2, 2)


def _i_fill_gaps(p, c, a):
    for i in range(3):
        for j in range(3):
            x, y = 5 + 7 * i, 5 + 7 * j
            gap = (i, j) in ((1, 1), (2, 1), (1, 2))
            _dot(p, a if gap else c, x, y, 2.0, hollow=gap)


def _i_accept_all(p, c, a):
    p.setPen(QtGui.QPen(a, 2.4))
    p.drawPolyline(_poly([(2, 13), (6, 17), (13, 8)]))
    p.drawPolyline(_poly([(9, 15), (11, 17), (21, 6)]))


def _i_reject_all(p, c, a):
    p.drawEllipse(P(12, 12), 9, 9)
    _cross(p, a, 12, 12, 4)


def _i_split(p, c, a):
    p.drawRect(R(2, 7, 8, 10))
    p.drawRect(R(14, 7, 8, 10))
    _arrow(p, a, 10, 3, 4, 3, 2.5, 1.6)
    _arrow(p, a, 14, 3, 20, 3, 2.5, 1.6)
    p.setPen(QtGui.QPen(a, 1.6, Qt.DashLine))
    p.drawLine(L(12, 6, 12, 21))


def _i_merge(p, c, a):
    p.drawRect(R(2, 4, 7, 7))
    p.drawRect(R(2, 13, 7, 7))
    _arrow(p, a, 10, 7.5, 15, 11, 2.5, 1.6)
    _arrow(p, a, 10, 16.5, 15, 13, 2.5, 1.6)
    p.save()
    p.setBrush(a)
    p.drawRect(R(16, 8, 6, 8))
    p.restore()


def _i_unsplit(p, c, a):
    p.drawRect(R(2, 3, 7, 7))
    p.drawRect(R(2, 13, 7, 7))
    _arrow(p, a, 10, 12, 13, 12, 2.5, 1.6)
    p.setPen(QtGui.QPen(a, 2))
    _small_tag(p, 13, 7, 0.75)


def _i_auto_box(p, c, a):
    _cube(p, 2, 8, 11)
    p.setPen(QtGui.QPen(a, 2))
    for x0, y0, x1, y1 in ((18, 2, 18, 8), (15, 5, 21, 5), (21, 11, 21, 15), (19, 13, 23, 13)):
        p.drawLine(L(x0, y0, x1, y1))


def _i_box_around_selection(p, c, a):
    _cube(p, 2, 3, 15)
    p.setPen(QtGui.QPen(a, 1.6, Qt.DashLine))
    p.drawRect(R(5, 12, 8, 7))


def _i_boxes_all(p, c, a):
    _cube(p, 2, 12, 7)
    _cube(p, 12, 12, 7)
    _cube(p, 7, 2, 7, pen=QtGui.QPen(a, 2))


def _i_refit(p, c, a):
    _cube(p, 6, 7, 9)
    for x0, y0, x1, y1 in ((1, 15, 5, 15), (23, 12, 18.5, 12), (10, 1, 10, 5)):
        _arrow(p, a, x0, y0, x1, y1, 2.5, 1.6)


def _i_box_delete(p, c, a):
    _cube(p, 2, 3, 12)
    _cross(p, a, 18, 18, 3.5)


def _track(p, c, a, flip):
    p.save()
    if flip:
        p.translate(24, 0)
        p.scale(-1, 1)
    _cube(p, 11, 6, 9)
    p.setPen(QtGui.QPen(a, 2))
    for y in (11, 15, 19):
        p.drawLine(L(2, y, 8, y))
    p.restore()


def _i_track_forward(p, c, a):
    _track(p, c, a, False)


def _i_track_backward(p, c, a):
    _track(p, c, a, True)


def _i_retrack(p, c, a):
    _cube(p, 7, 8, 8)
    p.setPen(QtGui.QPen(a, 2))
    p.drawArc(R(2, 2, 20, 20), 40 * 16, 260 * 16)
    _arrow(p, a, 19.8, 6.0, 20.5, 2.0, 2.5, 1.8)


def _i_strays(p, c, a):
    _cube(p, 5, 6, 10)
    for x, y in ((3, 3), (21, 5), (21, 21), (2, 20)):
        _dot(p, a, x, y, 1.8)


def _i_leftovers(p, c, a):
    _cube(p, 2, 6, 11)
    for x, y in ((18, 11), (20, 15), (18, 19)):
        _dot(p, a, x, y, 1.9, hollow=True)


def _i_absorb(p, c, a):
    _cube(p, 2, 6, 11)
    _dot(p, a, 21, 9, 2.0)
    _arrow(p, a, 21, 13, 15, 16, 2.5, 1.6)


def _i_mixed(p, c, a):
    _cube(p, 3, 4, 13)
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(a)
    p.drawPolygon(_poly([(3, 9.2), (16, 9.2), (3, 22.2)]))
    p.restore()


_BUTTONS = {
    "clear_selection": (_i_clear_selection, PINK), "box_fit": (_i_box_fit, AMBER), "box_select": (_i_box_select, PINK),
    "box_erase_in": (_i_box_erase_in, RED), "box_erase_out": (_i_box_erase_out, RED), "box_fill": (_i_box_fill, GREEN),
    "ruler_clear": (_i_ruler_clear, GOLD), "show_all": (_i_show_all, TEAL), "ground_select": (_i_ground_select, PINK),
    "ground_others": (_i_ground_others, PINK), "outliers": (_i_outliers, PINK), "sparse": (_i_sparse, PINK),
    "thin_out": (_i_thin_out, RED), "islands_pick": (_i_islands_pick, PINK), "speckles_clear": (_i_speckles_clear, RED),
    "apply": (_i_apply, GREEN), "trim": (_i_trim, RED), "class_edit": (_i_class_edit, BLUE),
    "class_remove": (_i_class_remove, RED), "list_save": (_i_list_save, BLUE), "tag_clear": (_i_tag_clear, RED),
    "solo": (_i_solo, TEAL), "select_class": (_i_select_class, PINK), "labels_open": (_i_labels_open, AMBER),
    "labels_save": (_i_labels_save, BLUE), "export": (_i_export, BLUE), "export_boxes": (_i_export_boxes, BLUE),
    "frames_show": (_i_frames_show, PINK), "poses": (_i_poses, BLUE), "poses_off": (_i_poses_off, RED),
    "propagate": (_i_propagate, GREEN), "conflict": (_i_conflict, PINK), "next_area": (_i_next_area, PINK),
    "doubt": (_i_doubt, PINK), "label_islands": (_i_label_islands, PINK), "fill_gaps": (_i_fill_gaps, GREEN),
    "accept_all": (_i_accept_all, GREEN), "reject_all": (_i_reject_all, RED), "split": (_i_split, AMBER),
    "merge": (_i_merge, AMBER), "unsplit": (_i_unsplit, AMBER), "auto_box": (_i_auto_box, GREEN),
    "box_around_selection": (_i_box_around_selection, AMBER), "boxes_all": (_i_boxes_all, AMBER),
    "refit": (_i_refit, AMBER), "box_delete": (_i_box_delete, RED), "track_forward": (_i_track_forward, GREEN),
    "track_backward": (_i_track_backward, GREEN), "retrack": (_i_retrack, AMBER), "strays": (_i_strays, PINK),
    "leftovers": (_i_leftovers, PINK), "absorb": (_i_absorb, GREEN), "mixed": (_i_mixed, PINK),
}


_DRAW = {
    "ground": _ground, "bbox": _bbox, "kind_voxel": _voxels, "kind_cloud": _dots, "kind_grid": _cells,
    "labels": _tag, "smart": _wand, "review": _check, "instances": _cubes, "frames": _film,
    "tool_label": _tag, "tool_smart": _wand,
    "brush": _brush, "rectangle": _marquee, "islands": _islands, "box": _box, "ruler": _ruler, "slice": _slice,
    "visible_range": _range, "display": _eye, "noise_filters": _funnel, "downsample": _thin, "paint_with": _states,
    "speckles": _speckles, "map_info": _info,
    "tool_view": _move, "tool_select": _cursor, "tool_delete": _eraser, "tool_add": _plus, "tool_measure": _ruler,
    "tool_pen": _pencil, "tool_line": _line, "tool_rectangle": _rect, "tool_fill": _drop,
    "open": _folder, "save": _floppy, "undo": _undo, "redo": _redo,
    "role_danger": _trash, "role_add": _plus_bare, "role_select": _cursor,
}


for _name, (_draw, _colour) in _BUTTONS.items():
    _DRAW["button_" + _name] = _draw
    ACCENTS["button_" + _name] = _colour


def accent(name):
    return ACCENTS.get(name, BLUE)


def pixmap(name, size=18):
    """Icon as a pixmap of `size` logical pixels (None for unknown names)."""
    draw = _DRAW.get(name)
    if draw is None:
        return None
    app = QtWidgets.QApplication.instance()
    ratio = app.devicePixelRatio() if app else 1.0
    image = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.scale(size / 24.0, size / 24.0)
    main = (app.palette() if app else QtGui.QPalette()).color(QtGui.QPalette.WindowText)
    pen = QtGui.QPen(main, 2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    draw(painter, main, QtGui.QColor(accent(name)))
    painter.end()
    return image


def icon(name, size=18):
    image = pixmap(name, size)
    return QtGui.QIcon(image) if image is not None else QtGui.QIcon()
