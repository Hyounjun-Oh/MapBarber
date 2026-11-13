"""Voxel index packing and the editable voxel set."""
import numpy as np

DEPTH = 16
OFFSET = 1 << (DEPTH - 1)
EMPTY = np.zeros(0, np.int64)


def pack(ijk):
    """Pack integer cell indices (N, 3) into sortable int64 keys."""
    k = np.asarray(ijk, np.int64).reshape(-1, 3) + OFFSET
    if len(k) and (k.min() < 0 or k.max() > 0xFFFF):
        raise ValueError(f"cell index outside the supported range of ±{OFFSET} cells per axis; use a larger voxel size")
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
    if not resolution > 0:
        raise ValueError("the voxel size must be greater than zero")
    points = np.asarray(points, np.float64).reshape(-1, 3)
    points = points[np.all(np.isfinite(points), axis=1)]
    ijk = np.floor(points / resolution + 1e-9).astype(np.int64)
    return np.unique(pack(ijk[in_range(ijk)]))


CHUNK_BITS = 6
CHUNK = 1 << CHUNK_BITS
_LOCAL_BITS = 3 * CHUNK_BITS
_AXIS_BITS = DEPTH - CHUNK_BITS
_AXIS_OFFSET = 1 << (_AXIS_BITS - 1)


class KeySet:
    """A set of cells stored in cubic chunks of 64 cells, so changes touch only the chunks they affect.

    Each chunk holds the sorted local indices (x | y << 6 | z << 12) of its cells.
    """

    def __init__(self, keys=EMPTY):
        self.chunks = {}
        self.count = 0
        self.add(np.asarray(keys, np.int64))

    def __len__(self):
        return self.count

    @staticmethod
    def split(keys):
        """Keys -> (chunk key per cell, local index per cell)."""
        cells = unpack(keys)
        local = cells & (CHUNK - 1)
        index = (local[:, 0] | (local[:, 1] << CHUNK_BITS) | (local[:, 2] << (2 * CHUNK_BITS))).astype(np.int32)
        chunk = (cells >> CHUNK_BITS) + _AXIS_OFFSET
        return (chunk[:, 0] << (2 * _AXIS_BITS)) | (chunk[:, 1] << _AXIS_BITS) | chunk[:, 2], index

    @staticmethod
    def chunk_origin(chunk_key):
        """First cell (x, y, z) of a chunk."""
        mask = (1 << _AXIS_BITS) - 1
        chunk = np.array([chunk_key >> (2 * _AXIS_BITS), (chunk_key >> _AXIS_BITS) & mask, chunk_key & mask], np.int64)
        return (chunk - _AXIS_OFFSET) << CHUNK_BITS

    def _groups(self, keys):
        """Yield (chunk key, sorted unique local indices) for a set of keys."""
        if not len(keys):
            return
        chunk, local = self.split(keys)
        code = (chunk << _LOCAL_BITS) | local
        code.sort()
        code = code[np.concatenate([[True], code[1:] != code[:-1]])]
        chunk, local = code >> _LOCAL_BITS, (code & ((1 << _LOCAL_BITS) - 1)).astype(np.int32)
        cuts = np.flatnonzero(np.diff(chunk)) + 1
        for start, end in zip(np.concatenate([[0], cuts]), np.concatenate([cuts, [len(chunk)]])):
            yield int(chunk[start]), local[start:end]

    def add(self, keys):
        """Insert keys; returns the chunk keys that changed."""
        touched = set()
        for chunk_key, local in self._groups(keys):
            current = self.chunks.get(chunk_key)
            merged = local if current is None else np.union1d(current, local)
            grown = len(merged) - (0 if current is None else len(current))
            if grown:
                self.chunks[chunk_key] = merged
                self.count += grown
                touched.add(chunk_key)
        return touched

    def remove(self, keys):
        """Delete keys; returns the chunk keys that changed."""
        touched = set()
        for chunk_key, local in self._groups(keys):
            current = self.chunks.get(chunk_key)
            if current is None:
                continue
            left = np.setdiff1d(current, local, assume_unique=True)
            if len(left) == len(current):
                continue
            self.count -= len(current) - len(left)
            if len(left):
                self.chunks[chunk_key] = left
            else:
                del self.chunks[chunk_key]
            touched.add(chunk_key)
        return touched

    def clear(self):
        """Empty the set; returns the chunk keys that held something."""
        touched = set(self.chunks)
        self.chunks, self.count = {}, 0
        return touched

    def cells(self, chunk_key, local=None):
        """Cell indices (N, 3) of a chunk's occupied cells, or of the given local indices."""
        local = self.chunks[chunk_key] if local is None else local
        mask = CHUNK - 1
        offsets = np.stack([local & mask, (local >> CHUNK_BITS) & mask, (local >> (2 * CHUNK_BITS)) & mask], axis=1)
        return offsets.astype(np.int64) + self.chunk_origin(chunk_key)

    def keys(self, chunk_key):
        return pack(self.cells(chunk_key))

    @property
    def occupied(self):
        """Every occupied key, sorted. Costs a pass over the whole map; meant for saving and conversion."""
        if not self.chunks:
            return EMPTY
        return np.sort(np.concatenate([self.keys(chunk_key) for chunk_key in self.chunks]))

    def contains(self, keys):
        """Boolean mask: which of the keys are occupied."""
        keys = np.asarray(keys, np.int64)
        found = np.zeros(len(keys), bool)
        if not len(keys):
            return found
        chunk, local = self.split(keys)
        order = np.argsort(chunk, kind="stable")
        cuts = np.flatnonzero(np.diff(chunk[order])) + 1
        for start, end in zip(np.concatenate([[0], cuts]), np.concatenate([cuts, [len(order)]])):
            rows = order[start:end]
            stored = self.chunks.get(int(chunk[rows[0]]))
            if stored is not None:
                found[rows] = np.isin(local[rows], stored)
        return found


    def bounds(self):
        """(lowest cell, highest cell) over the whole map, or None when it is empty."""
        if not self.chunks:
            return None
        low = np.array([np.iinfo(np.int64).max] * 3)
        high = -low
        for chunk_key in self.chunks:
            cells = self.cells(chunk_key)
            low, high = np.minimum(low, cells.min(axis=0)), np.maximum(high, cells.max(axis=0))
        return low, high


class VoxelMap(KeySet):
    """Occupied cells on a regular grid with undo/redo and a record of what changed since the last save."""

    def __init__(self, keys=EMPTY, resolution=0.05):
        super().__init__(keys)
        self.resolution = float(resolution)
        self.leaves = None
        self.added, self.removed = EMPTY, EMPTY
        self.last_added = EMPTY
        self.touched = set()
        self._undo, self._redo = [], []

    @property
    def saved(self):
        """Keys as they were at the last save."""
        return np.union1d(np.setdiff1d(self.occupied, self.added, assume_unique=True), self.removed)

    def _change(self, add, remove):
        """Add and remove keys that are known to be absent and present; records the touched chunk keys."""
        self.touched = self.remove(remove) | self.add(add)
        again = np.intersect1d(add, self.removed)
        gone = np.intersect1d(remove, self.added)
        self.added = np.setdiff1d(np.union1d(self.added, np.setdiff1d(add, again, assume_unique=True)), gone)
        self.removed = np.setdiff1d(np.union1d(self.removed, np.setdiff1d(remove, gone, assume_unique=True)), again)

    def apply(self, add=None, remove=None):
        """Apply an edit and return (added, removed) counts of cells that actually changed."""
        add = EMPTY if add is None else np.unique(np.asarray(add, np.int64))
        remove = EMPTY if remove is None else np.unique(np.asarray(remove, np.int64))
        add = add[~self.contains(add)]
        remove = remove[self.contains(remove)]
        self.touched = set()
        self.last_added = add
        if not len(add) and not len(remove):
            return 0, 0
        self._change(add, remove)
        self._undo.append((add, remove))
        self._redo.clear()
        return len(add), len(remove)

    def undo(self):
        if not self._undo:
            return False
        add, remove = self._undo.pop()
        self._change(remove, add)
        self._redo.append((add, remove))
        return True

    def redo(self):
        if not self._redo:
            return False
        add, remove = self._redo.pop()
        self._change(add, remove)
        self._undo.append((add, remove))
        return True

    def undo_depth(self):
        return len(self._undo)

    def squash(self, depth):
        """Merge the removals recorded since `depth` into one undo step (a brush stroke)."""
        steps = self._undo[depth:]
        if len(steps) > 1 and all(not len(add) for add, _ in steps):
            self._undo[depth:] = [(EMPTY, np.unique(np.concatenate([remove for _, remove in steps])))]
            return True
        return False

    @property
    def dirty(self):
        return bool(len(self.added) or len(self.removed))

    def mark_saved(self):
        self.added, self.removed = EMPTY, EMPTY

    def changes(self):
        """(added, removed) cell counts relative to the last saved state."""
        return len(self.added), len(self.removed)

    def islands(self, max_size):
        """Keys of 26-connected components with at most max_size cells -> (keys, component count).

        Components are found inside each chunk first and then joined across chunk borders, so the
        size of the map does not matter.
        """
        from scipy import ndimage
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        if not self.chunks:
            return EMPTY, 0
        structure = np.ones((3, 3, 3), bool)
        mask = CHUNK - 1
        chunk_keys = list(self.chunks)
        coords, labels, offsets, sizes = {}, {}, {}, []
        total = 0
        for chunk_key in chunk_keys:
            local = self.chunks[chunk_key]
            xyz = np.stack([local & mask, (local >> CHUNK_BITS) & mask, (local >> (2 * CHUNK_BITS)) & mask], axis=1)
            grid = np.zeros((CHUNK, CHUNK, CHUNK), bool)
            grid[xyz[:, 0], xyz[:, 1], xyz[:, 2]] = True
            labelled, count = ndimage.label(grid, structure=structure)
            mine = labelled[xyz[:, 0], xyz[:, 1], xyz[:, 2]] - 1
            coords[chunk_key], labels[chunk_key], offsets[chunk_key] = xyz, mine + total, total
            sizes.append(np.bincount(mine, minlength=count))
            total += count
        sizes = np.concatenate(sizes)

        def border(chunk_key, direction, far_side):
            """Component ids on the face, edge or corner of a chunk that looks along `direction`."""
            xyz, ids = coords[chunk_key], labels[chunk_key]
            keep = np.ones(len(xyz), bool)
            free = []
            for axis, step in enumerate(direction):
                if step == 0:
                    free.append(axis)
                else:
                    keep &= xyz[:, axis] == (mask if (step > 0) == far_side else 0)
            image = np.full((CHUNK,) * len(free), -1, np.int64)
            if free:
                image[tuple(xyz[keep][:, axis] for axis in free)] = ids[keep]
            elif keep.any():
                image[()] = ids[keep][0]
            return image

        axis_mask = (1 << _AXIS_BITS) - 1
        first, second = [], []
        directions = [d for d in np.ndindex(3, 3, 3) if d > (1, 1, 1)]
        for chunk_key in chunk_keys:
            base = np.array([chunk_key >> (2 * _AXIS_BITS), (chunk_key >> _AXIS_BITS) & axis_mask, chunk_key & axis_mask])
            for direction in directions:
                step = np.array(direction) - 1
                other = base + step
                if (other < 0).any() or (other > axis_mask).any():
                    continue
                other_key = int((other[0] << (2 * _AXIS_BITS)) | (other[1] << _AXIS_BITS) | other[2])
                if other_key not in coords:
                    continue
                here, there = border(chunk_key, step, True), border(other_key, step, False)
                for shift in np.ndindex(*(3,) * here.ndim):
                    a = tuple(slice(max(0, 1 - s), CHUNK - max(0, s - 1)) for s in shift)
                    b = tuple(slice(max(0, s - 1), CHUNK - max(0, 1 - s)) for s in shift)
                    touching = (here[a] >= 0) & (there[b] >= 0)
                    if touching.any():
                        first.append(here[a][touching])
                        second.append(there[b][touching])
        if first:
            rows, columns = np.concatenate(first), np.concatenate(second)
            graph = coo_matrix((np.ones(len(rows), np.int8), (rows, columns)), shape=(total, total))
            groups, root = connected_components(graph, directed=False)
        else:
            groups, root = total, np.arange(total)
        whole = np.bincount(root, weights=sizes, minlength=groups)
        small = whole[root] <= max_size
        keys = [pack(self.cells(chunk_key)[small[labels[chunk_key]]]) for chunk_key in chunk_keys]
        return np.sort(np.concatenate(keys)), int((whole <= max_size).sum())


def ray_boxes(origin, direction, low, high):
    """Entry distances of a ray into axis-aligned boxes -> (indices of the boxes hit, entry distance of each)."""
    d = np.where(np.abs(direction) < 1e-12, 1e-12, direction)
    t1, t2 = (low - origin) / d, (high - origin) / d
    t_in = np.minimum(t1, t2).max(axis=1)
    t_out = np.maximum(t1, t2).min(axis=1)
    hits = np.flatnonzero(t_out >= np.maximum(t_in, 0.0))
    return hits, t_in[hits]


def ray_pick(origin, direction, box_centers, half, with_distance=False):
    """First axis-aligned cube hit by a ray -> (index, face axis, outward sign[, distance]) or None."""
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
    hit = (int(i), axis, (-1 if d[axis] > 0 else 1))
    return hit + (float(t_in[i]),) if with_distance else hit
