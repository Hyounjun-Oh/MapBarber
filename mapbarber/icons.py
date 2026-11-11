"""Small line icons drawn with QPainter, so they follow the palette and need no image files."""
from .qt import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
P, L, R = QtCore.QPointF, QtCore.QLineF, QtCore.QRectF

BLUE, PINK, AMBER, GOLD, RED, GREEN, TEAL, VIOLET = ("#4f9cf7", "#ff4fc8", "#f2b632", "#ffd126", "#ef5350", "#4cc26a",
                                                    "#35c2b0", "#9b7bf0")
ACCENTS = {
    "brush": BLUE, "paint_with": BLUE, "rectangle": PINK, "islands": PINK, "noise_filters": PINK, "box": AMBER,
    "ruler": GOLD, "slice": VIOLET, "visible_range": TEAL, "display": TEAL, "downsample": RED, "speckles": RED,
    "map_info": GREEN,
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


_DRAW = {
    "brush": _brush, "rectangle": _marquee, "islands": _islands, "box": _box, "ruler": _ruler, "slice": _slice,
    "visible_range": _range, "display": _eye, "noise_filters": _funnel, "downsample": _thin, "paint_with": _states,
    "speckles": _speckles, "map_info": _info,
    "tool_view": _move, "tool_select": _cursor, "tool_delete": _eraser, "tool_add": _plus, "tool_measure": _ruler,
    "tool_pen": _pencil, "tool_line": _line, "tool_rectangle": _rect, "tool_fill": _drop,
    "open": _folder, "save": _floppy, "undo": _undo, "redo": _redo,
    "role_danger": _trash, "role_add": _plus_bare, "role_select": _cursor,
}


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
