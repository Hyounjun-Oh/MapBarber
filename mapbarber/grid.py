"""Editable 2D occupancy grid in the map_server layout (YAML description plus an image)."""
import math
import os

import numpy as np

FREE, OCCUPIED, UNKNOWN = 0, 1, 2
DEFAULT_META = {"negate": 0, "occupied_thresh": 0.65, "free_thresh": 0.196, "mode": "trinary"}
RAW_UNKNOWN = 255


def _parse_yaml(text):
    """Flat `key: value` reader, enough for map description files."""
    meta = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if value.startswith("["):
            meta[key] = [float(v) for v in value.strip("[]").split(",") if v.strip()]
            continue
        value = value.strip("\"'")
        try:
            meta[key] = int(value)
        except ValueError:
            try:
                meta[key] = float(value)
            except ValueError:
                meta[key] = value
    return meta


def read_pgm(path):
    with open(path, "rb") as f:
        data = f.read()
    tokens, pos = [], 0
    while len(tokens) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            pos = data.index(b"\n", pos) + 1
            continue
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        tokens.append(data[pos:end])
        pos = end
    magic, width, height, peak = tokens[0], int(tokens[1]), int(tokens[2]), int(tokens[3])
    if magic == b"P5":
        dtype = np.dtype(">u2") if peak > 255 else np.uint8
        pixels = np.frombuffer(data, dtype, count=width * height, offset=pos + 1).reshape(height, width)
    elif magic == b"P2":
        pixels = np.array(data[pos:].split(), np.int64).reshape(height, width)
    else:
        raise ValueError("only greyscale PGM images (P2, P5) are supported")
    return (pixels.astype(np.float64) * (255.0 / peak)).round().astype(np.uint8)


def write_pgm(path, pixels):
    with open(path, "wb") as f:
        f.write(f"P5\n# written by MapBarber\n{pixels.shape[1]} {pixels.shape[0]}\n255\n".encode())
        f.write(np.ascontiguousarray(pixels, np.uint8).tobytes())


def _read_image(path):
    if path.lower().endswith(".pgm"):
        return read_pgm(path)
    from .qt import QtGui
    image = QtGui.QImage(path)
    if image.isNull():
        raise ValueError(f"cannot read image: {path}")
    image = image.convertToFormat(QtGui.QImage.Format_Grayscale8)
    buffer = image.constBits()
    if hasattr(buffer, "setsize"):
        buffer.setsize(image.sizeInBytes())
    rows = np.frombuffer(buffer, np.uint8).reshape(image.height(), image.bytesPerLine())
    return rows[:, :image.width()].copy()


def _write_image(path, pixels):
    if path.lower().endswith(".pgm"):
        return write_pgm(path, pixels)
    from .qt import QtGui
    pixels = np.ascontiguousarray(pixels, np.uint8)
    image = QtGui.QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.shape[1], QtGui.QImage.Format_Grayscale8)
    if not image.save(path):
        raise ValueError(f"cannot write image: {path}")


class GridMap:
    """Cells are stored with row 0 at the bottom, so cell (row, column) sits at origin + (column, row) * resolution."""

    def __init__(self, cells, resolution=0.05, origin=(0.0, 0.0, 0.0), meta=None):
        self.cells = np.ascontiguousarray(cells, np.uint8)
        self.resolution = float(resolution)
        self.origin = tuple(float(v) for v in origin)
        self.meta = dict(DEFAULT_META, **(meta or {}))
        self._saved = self.snapshot()
        self._undo, self._redo = [], []

    @property
    def shape(self):
        return self.cells.shape

    def counts(self):
        return [int(v) for v in np.bincount(self.cells.ravel(), minlength=3)[:3]]

    def snapshot(self):
        return self.cells.copy(), self.origin, self.resolution

    def commit(self, before):
        """Record the change since `before` (from snapshot()); returns the number of changed cells."""
        cells, origin, resolution = before
        if cells.shape != self.cells.shape:
            changed = max(cells.size, self.cells.size)
        else:
            changed = int(np.count_nonzero(cells != self.cells))
            if not changed and origin == self.origin and resolution == self.resolution:
                return 0
        self._undo.append(before)
        self._redo.clear()
        return changed

    def _swap(self, source, target):
        if not source:
            return False
        target.append(self.snapshot())
        self.cells, self.origin, self.resolution = source.pop()
        return True

    def undo(self):
        return self._swap(self._undo, self._redo)

    def redo(self):
        return self._swap(self._redo, self._undo)

    @property
    def dirty(self):
        cells, origin, resolution = self._saved
        return (origin != self.origin or resolution != self.resolution or cells.shape != self.cells.shape
                or not np.array_equal(cells, self.cells))

    def mark_saved(self):
        self._saved = self.snapshot()

    def cell_at(self, x, y):
        """Map coordinates -> (row, column) of the containing cell, possibly outside the grid."""
        c, s = np.cos(self.origin[2]), np.sin(self.origin[2])
        dx, dy = x - self.origin[0], y - self.origin[1]
        return int(np.floor((-s * dx + c * dy) / self.resolution)), int(np.floor((c * dx + s * dy) / self.resolution))

    def world(self, row, column):
        """Centre of a cell in map coordinates, honouring the yaw of the origin."""
        x, y = (column + 0.5) * self.resolution, (row + 0.5) * self.resolution
        c, s = np.cos(self.origin[2]), np.sin(self.origin[2])
        return self.origin[0] + c * x - s * y, self.origin[1] + s * x + c * y

    def stamp(self, row, column, size, value):
        """Paint a square brush of `size` cells centred on a cell."""
        half = size // 2
        r0, c0 = max(row - half, 0), max(column - half, 0)
        self.cells[r0:max(row - half + size, 0), c0:max(column - half + size, 0)] = value

    def line(self, start, end, size, value):
        steps = int(max(abs(end[0] - start[0]), abs(end[1] - start[1]))) + 1
        for row, column in zip(np.linspace(start[0], end[0], steps).round().astype(int),
                               np.linspace(start[1], end[1], steps).round().astype(int)):
            self.stamp(int(row), int(column), size, value)

    def rectangle(self, start, end, value):
        r0, r1 = sorted((start[0], end[0]))
        c0, c1 = sorted((start[1], end[1]))
        self.cells[max(r0, 0):max(r1 + 1, 0), max(c0, 0):max(c1 + 1, 0)] = value

    def flood(self, row, column, value):
        """Recolour the 4-connected region of equal state around a cell."""
        from scipy import ndimage
        if not (0 <= row < self.shape[0] and 0 <= column < self.shape[1]):
            return
        labels, _ = ndimage.label(self.cells == self.cells[row, column])
        self.cells[labels == labels[row, column]] = value

    def clear_speckles(self, max_size, value=FREE):
        """Turn 8-connected occupied groups of at most max_size cells into `value` -> (cells, groups)."""
        from scipy import ndimage
        labels, count = ndimage.label(self.cells == OCCUPIED, structure=np.ones((3, 3), bool))
        sizes = np.bincount(labels.ravel())
        small = (sizes <= max_size)
        small[0] = False
        mask = small[labels]
        self.cells[mask] = value
        return int(mask.sum()), int(small.sum())

    def trim(self):
        """Crop away the unknown border and move the origin accordingly."""
        known = self.cells != UNKNOWN
        if not known.any():
            return False
        rows, columns = np.flatnonzero(known.any(axis=1)), np.flatnonzero(known.any(axis=0))
        r0, r1, c0, c1 = rows[0], rows[-1] + 1, columns[0], columns[-1] + 1
        if (r0, c0) == (0, 0) and (r1, c1) == self.shape:
            return False
        x, y = c0 * self.resolution, r0 * self.resolution
        c, s = np.cos(self.origin[2]), np.sin(self.origin[2])
        self.origin = (float(self.origin[0] + c * x - s * y), float(self.origin[1] + s * x + c * y), self.origin[2])
        self.cells = np.ascontiguousarray(self.cells[r0:r1, c0:c1])
        return True


def snap_angle(start, end):
    """End cell moved onto the nearest 0, 45 or 90 degree direction from the start cell."""
    dr, dc = end[0] - start[0], end[1] - start[1]
    if dr == 0 and dc == 0:
        return end
    angle = round(math.atan2(dr, dc) / (math.pi / 4)) * (math.pi / 4)
    along = dr * math.sin(angle) + dc * math.cos(angle)
    return start[0] + int(round(along * math.sin(angle))), start[1] + int(round(along * math.cos(angle)))


def shape_corners(start, end, square, centred):
    """Rectangle corners from a drag: square keeps equal sides, centred grows the shape around the start cell."""
    dr, dc = end[0] - start[0], end[1] - start[1]
    if square:
        side = max(abs(dr), abs(dc))
        dr, dc = (side if dr >= 0 else -side), (side if dc >= 0 else -side)
    if centred:
        return (start[0] - dr, start[1] - dc), (start[0] + dr, start[1] + dc)
    return start, (start[0] + dr, start[1] + dc)
DEFAULTS = {"brush": 1, "state": OCCUPIED, "speckle": 4}


def min_pool(rgb, step):
    """Shrink an image by keeping the darkest pixel of each block, so thin obstacles survive zooming out."""
    height, width = rgb.shape[0] // step * step, rgb.shape[1] // step * step
    if height == 0 or width == 0:
        return rgb
    blocks = rgb[:height, :width].reshape(height // step, step, width // step, step, 3)
    return blocks.min(axis=(1, 3))


def classify(pixels, meta):
    """Image pixels -> cell states, following the map_server conventions."""
    meta = dict(DEFAULT_META, **meta)
    cells = np.full(pixels.shape, UNKNOWN, np.uint8)
    if meta["mode"] == "raw":
        known = pixels <= 100
        occupancy = pixels.astype(np.float64) / 100.0
    else:
        known = np.ones(pixels.shape, bool)
        level = pixels.astype(np.float64) / 255.0
        occupancy = level if meta["negate"] else 1.0 - level
    cells[known & (occupancy > float(meta["occupied_thresh"]))] = OCCUPIED
    cells[known & (occupancy < float(meta["free_thresh"]))] = FREE
    return cells


def _unknown_shade(meta):
    """A grey level that reads back as unknown under the map's own thresholds."""
    low, high = float(meta["free_thresh"]), float(meta["occupied_thresh"])
    if low <= 50 / 255 <= high:
        return 205
    return int(round(255 * (1.0 - (low + high) / 2)))


def render(cells, meta=None):
    meta = dict(DEFAULT_META, **(meta or {}))
    if meta["mode"] == "raw":
        return np.array([0, 100, RAW_UNKNOWN], np.uint8)[cells]
    pixels = np.array([254, 0, _unknown_shade(meta)], np.uint8)[cells]
    return 255 - pixels if meta["negate"] else pixels


def load(path, resolution=None):
    """Map description (.yaml) or a bare image -> GridMap."""
    if os.path.splitext(path)[1].lower() in (".yaml", ".yml"):
        with open(path, "r") as f:
            meta = _parse_yaml(f.read())
        if "image" not in meta:
            raise ValueError("the YAML file has no 'image' entry, so it is not a map description")
        image = str(meta["image"])
        if not os.path.isabs(image):
            image = os.path.join(os.path.dirname(os.path.abspath(path)), image)
    else:
        companion = os.path.splitext(path)[0] + ".yaml"
        if os.path.isfile(companion):
            with open(companion, "r") as f:
                described = _parse_yaml(f.read())
            if os.path.basename(str(described.get("image", ""))) == os.path.basename(path):
                return load(companion, resolution)
        meta, image = {}, path
    pixels = _read_image(image)
    origin = (list(meta.get("origin", [])) + [0.0, 0.0, 0.0])[:3]
    return GridMap(np.flipud(classify(pixels, meta)), resolution or meta.get("resolution", 0.05), origin,
                   {key: meta[key] for key in DEFAULT_META if key in meta})


def save(path, grid):
    """Write a GridMap as image plus YAML; `path` may name either file."""
    stem, ext = os.path.splitext(path)
    image = path if ext.lower() not in (".yaml", ".yml") else stem + ".pgm"
    _write_image(image, render(np.flipud(grid.cells), grid.meta))
    with open(os.path.splitext(image)[0] + ".yaml", "w") as f:
        f.write(f"image: {os.path.basename(image)}\nmode: {grid.meta['mode']}\nresolution: {grid.resolution:g}\n"
                f"origin: [{grid.origin[0]:.6g}, {grid.origin[1]:.6g}, {grid.origin[2]:.6g}]\n"
                f"negate: {int(grid.meta['negate'])}\noccupied_thresh: {grid.meta['occupied_thresh']}\n"
                f"free_thresh: {grid.meta['free_thresh']}\n")
