"""Editable point cloud: points are only ever removed, so every field of every survivor is kept."""
import numpy as np

EMPTY = np.zeros(0, np.int64)


class PointCloud:
    def __init__(self, xyz, table=None):
        self.xyz = np.ascontiguousarray(xyz, np.float64).reshape(-1, 3)
        self.table = table
        self.alive = np.all(np.isfinite(self.xyz), axis=1)
        self.saved = self.alive.copy()
        self.touched = EMPTY
        self._undo, self._redo = [], []

    def __len__(self):
        return int(self.alive.sum())

    def ids(self):
        return np.flatnonzero(self.alive)

    def remove(self, ids):
        ids = np.asarray(ids, np.int64)
        ids = ids[self.alive[ids]]
        if not len(ids):
            return 0
        self.alive[ids] = False
        self.touched = ids
        self._undo.append(ids)
        self._redo.clear()
        return len(ids)

    def undo_depth(self):
        return len(self._undo)

    def squash(self, depth):
        """Merge the removals recorded since `depth` into one undo step (a brush stroke)."""
        if len(self._undo) - depth > 1:
            self._undo[depth:] = [np.concatenate(self._undo[depth:])]

    def undo(self):
        if not self._undo:
            return False
        ids = self._undo.pop()
        self.alive[ids] = True
        self.touched = ids
        self._redo.append(ids)
        return True

    def redo(self):
        if not self._redo:
            return False
        ids = self._redo.pop()
        self.alive[ids] = False
        self.touched = ids
        self._undo.append(ids)
        return True

    @property
    def dirty(self):
        return not np.array_equal(self.alive, self.saved)

    def mark_saved(self):
        self.saved = self.alive.copy()

    def removed(self):
        return int((self.saved & ~self.alive).sum())

    def surviving(self):
        """(xyz, record array or None) of the points that are still alive."""
        return self.xyz[self.alive], (None if self.table is None else self.table[self.alive])


def statistical_outliers(points, neighbours=16, ratio=2.0):
    """Indices of points whose mean neighbour distance is unusually large."""
    from scipy.spatial import cKDTree
    if len(points) <= neighbours:
        return EMPTY
    distances, _ = cKDTree(points).query(points, k=neighbours + 1)
    mean = distances[:, 1:].mean(axis=1)
    return np.flatnonzero(mean > mean.mean() + ratio * mean.std())


def sparse_points(points, radius=0.1, minimum=4):
    """Indices of points with fewer than `minimum` other points within `radius`."""
    from scipy.spatial import cKDTree
    if not len(points):
        return EMPTY
    tree = cKDTree(points)
    counts = tree.query_ball_point(points, radius, return_length=True) - 1
    return np.flatnonzero(counts < minimum)


def downsample_surplus(points, leaf):
    """Indices of every point except the first one found in each cubic cell of size `leaf`."""
    if not len(points):
        return EMPTY
    cells = np.floor(points / leaf).astype(np.int64)
    _, first = np.unique(cells, axis=0, return_index=True)
    keep = np.zeros(len(points), bool)
    keep[first] = True
    return np.flatnonzero(~keep)


def pick_along_ray(origin, direction, points, angle):
    """Index of the nearest point lying within `angle` (radians) of a ray, or None."""
    if not len(points):
        return None
    offset = points - origin
    along = offset @ direction
    off_axis = np.sqrt(np.maximum(np.einsum("ij,ij->i", offset, offset) - along * along, 0.0))
    hits = np.flatnonzero((along > 0) & (off_axis <= along * angle))
    if not len(hits):
        return None
    return int(hits[np.argmin(along[hits])])


class PointChunks:
    """Fixed spatial partition of a cloud into grid cells, so work can be limited to the cells it concerns.

    Each chunk lists its points in a fixed random order, so any leading part of the list is an even sample of it.
    """

    TARGET = 40_000

    def __init__(self, xyz, alive):
        ids = np.flatnonzero(alive)
        self.of = np.full(len(xyz), -1, np.int32)
        self.ids, self.low, self.high = [], np.zeros((0, 3)), np.zeros((0, 3))
        if not len(ids):
            return
        points = xyz[ids]
        low, high = points.min(axis=0), points.max(axis=0)
        per_axis = int(np.clip(round(2 * (len(ids) / self.TARGET) ** (1 / 3)), 1, 64))
        cell = max(float((high - low).max()) / per_axis, 1e-9)
        index = np.minimum(((points - low) / cell).astype(np.int64), per_axis - 1)
        code = (index[:, 0] * per_axis + index[:, 1]) * per_axis + index[:, 2]
        order = np.argsort(code, kind="stable")
        starts = np.concatenate([[0], np.flatnonzero(np.diff(code[order])) + 1, [len(order)]])
        lows, highs = [], []
        shuffle = np.random.default_rng(0)
        for number, (start, end) in enumerate(zip(starts[:-1], starts[1:])):
            members = shuffle.permutation(ids[order[start:end]])
            self.ids.append(members)
            self.of[members] = number
            inside = xyz[members]
            lows.append(inside.min(axis=0))
            highs.append(inside.max(axis=0))
        self.low, self.high = np.array(lows), np.array(highs)

    def __len__(self):
        return len(self.ids)

    def touched(self, ids):
        """Chunk numbers that hold any of the given points."""
        return set(np.unique(self.of[ids]).tolist()) - {-1}

    def near(self, centre, radius):
        """Chunk numbers whose box comes within `radius` of a point."""
        gap = np.maximum(np.maximum(self.low - centre, centre - self.high), 0.0)
        return np.flatnonzero(np.einsum("ij,ij->i", gap, gap) <= radius * radius)

    def overlapping(self, low, high):
        return np.flatnonzero(np.all((self.high >= low) & (self.low <= high), axis=1))
