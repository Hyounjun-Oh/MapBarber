"""Voxel index packing and the editable voxel set."""
import numpy as np

DEPTH = 16
OFFSET = 1 << (DEPTH - 1)
EMPTY = np.zeros(0, np.int64)


def pack(ijk):
    """Pack integer cell indices (N, 3) into sortable int64 keys."""
    k = np.asarray(ijk, np.int64).reshape(-1, 3) + OFFSET
    return (k[:, 0] << 32) | (k[:, 1] << 16) | k[:, 2]


def unpack(keys):
    k = np.asarray(keys, np.int64)
    return np.stack([(k >> 32) & 0xFFFF, (k >> 16) & 0xFFFF, k & 0xFFFF], axis=1) - OFFSET


def in_range(ijk):
    ijk = np.asarray(ijk, np.int64).reshape(-1, 3)
    return np.all((ijk >= -OFFSET) & (ijk < OFFSET), axis=1)


def centers(keys, resolution):
    return (unpack(keys) + 0.5) * resolution


def voxelize(points, resolution):
    """Points (N, 3) -> unique keys of the cells that contain them."""
    points = np.asarray(points, np.float64).reshape(-1, 3)
    points = points[np.all(np.isfinite(points), axis=1)]
    ijk = np.floor(points / resolution + 1e-9).astype(np.int64)
    return np.unique(pack(ijk[in_range(ijk)]))


class VoxelMap:
    """A set of occupied cells on a regular grid, with undo/redo."""

    def __init__(self, keys=EMPTY, resolution=0.05):
        self.resolution = float(resolution)
        self.occupied = np.unique(np.asarray(keys, np.int64))
        self.saved = self.occupied.copy()
        self._undo, self._redo = [], []

    def __len__(self):
        return len(self.occupied)

    def apply(self, add=None, remove=None):
        """Apply an edit and return (added, removed) counts of cells that actually changed."""
        add = EMPTY if add is None else np.setdiff1d(np.asarray(add, np.int64), self.occupied)
        remove = EMPTY if remove is None else np.intersect1d(np.asarray(remove, np.int64), self.occupied)
        if not len(add) and not len(remove):
            return 0, 0
        self.occupied = np.union1d(np.setdiff1d(self.occupied, remove, assume_unique=True), add)
        self._undo.append((add, remove))
        self._redo.clear()
        return len(add), len(remove)

    def undo(self):
        if not self._undo:
            return False
        add, remove = self._undo.pop()
        self.occupied = np.union1d(np.setdiff1d(self.occupied, add, assume_unique=True), remove)
        self._redo.append((add, remove))
        return True

    def redo(self):
        if not self._redo:
            return False
        add, remove = self._redo.pop()
        self.occupied = np.union1d(np.setdiff1d(self.occupied, remove, assume_unique=True), add)
        self._undo.append((add, remove))
        return True

    @property
    def dirty(self):
        return not np.array_equal(self.occupied, self.saved)

    def mark_saved(self):
        self.saved = self.occupied.copy()

    def changes(self):
        """(added, removed) cell counts relative to the last saved state."""
        return (len(np.setdiff1d(self.occupied, self.saved, assume_unique=True)),
                len(np.setdiff1d(self.saved, self.occupied, assume_unique=True)))

    def islands(self, max_size):
        """Keys of 26-connected components with at most max_size cells -> (keys, component count)."""
        from scipy import ndimage
        if not len(self.occupied):
            return EMPTY, 0
        ijk = unpack(self.occupied)
        low = ijk.min(axis=0)
        dims = ijk.max(axis=0) - low + 1
        if float(np.prod(dims.astype(np.float64))) > 4e8:
            raise MemoryError("map extent is too large for connected-component analysis")
        grid = np.zeros(dims, bool)
        rel = ijk - low
        grid[rel[:, 0], rel[:, 1], rel[:, 2]] = True
        labels, _ = ndimage.label(grid, structure=np.ones((3, 3, 3), bool))
        sizes = np.bincount(labels.ravel())
        mine = labels[rel[:, 0], rel[:, 1], rel[:, 2]]
        small = sizes[mine] <= max_size
        return self.occupied[small], int(len(np.unique(mine[small])))


def ray_pick(origin, direction, box_centers, half):
    """First axis-aligned cube hit by a ray -> (index, face axis, outward sign) or None."""
    if not len(box_centers):
        return None
    d = np.where(np.abs(direction) < 1e-12, 1e-12, direction)
    t1 = (box_centers - half - origin) / d
    t2 = (box_centers + half - origin) / d
    near = np.minimum(t1, t2)
    t_in = near.max(axis=1)
    t_out = np.maximum(t1, t2).min(axis=1)
    hits = np.flatnonzero(t_out >= np.maximum(t_in, 0.0))
    if not len(hits):
        return None
    i = hits[np.argmin(t_in[hits])]
    axis = int(np.argmax(near[i]))
    return int(i), axis, (-1 if d[axis] > 0 else 1)
