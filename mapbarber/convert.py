"""Conversions between voxel maps, point clouds and 2D occupancy grids."""
import numpy as np

from . import labels
from .grid import FREE, OCCUPIED, UNKNOWN, GridMap
from .voxels import centers, pack, unpack, voxelize


def voxels_to_points(keys, resolution):
    return centers(keys, resolution)


def points_to_voxels(points, resolution):
    return voxelize(points, resolution)


def restore_points(xyz, table, resolution, voxel_map):
    """Points of a cloud that was turned into voxels, as they come back from the (possibly edited) voxel map.

    Every original point whose voxel still exists returns at its exact original position with all its fields.
    Voxels that hold no original point (added in the voxel editor) contribute their centre as a new point.
    """
    restored = restore(xyz, table, resolution, voxel_map)
    return restored["xyz"], restored["table"]


def restore(xyz, table, resolution, voxel_map, cls=None, inst=None, voxel_labels=None, outside=None):
    """Like restore_points, with labels. Returns a dict with xyz, table, cls, inst and the counts of what happened.

    Points keep their own class and instance, whatever class their voxel won by vote. Only voxels whose
    class was changed in the voxel editor pass that class on to all their points (and clear the
    instance). Points that were left out of the voxel map (`outside`) come back exactly as they were.
    New voxels become points at their centre carrying the voxel's class.
    """
    xyz = np.asarray(xyz, np.float64)
    keys = point_keys(xyz, resolution)
    outside = np.zeros(len(xyz), bool) if outside is None else np.asarray(outside, bool)
    present = voxel_map.contains(keys)
    kept = present | outside
    covered = np.unique(keys[present & ~outside])
    occupied = voxel_map.occupied
    fresh_keys = occupied[~np.isin(occupied, covered, assume_unique=True)]
    fresh = centers(fresh_keys, resolution)
    count = int(kept.sum())
    points = np.vstack([xyz[kept], fresh])
    out = {"xyz": points, "table": None, "cls": None, "inst": None, "relabelled": 0, "relabelled_voxels": 0,
           "dropped": int((~kept).sum()), "added": len(fresh)}
    if table is not None:
        rows = np.zeros(len(points), table.dtype)
        rows[:count] = table[kept]
        for axis, name in enumerate("xyz"):
            rows[name][count:] = fresh[:, axis]
        out["table"] = rows
    if cls is None and (voxel_labels is None or not voxel_labels.any):
        return out
    own_cls = np.zeros(len(xyz), np.uint16) if cls is None else np.asarray(cls, np.uint16)
    own_inst = np.zeros(len(xyz), np.uint32) if inst is None else np.asarray(inst, np.uint32)
    new_cls, new_inst = own_cls[kept].copy(), own_inst[kept].copy()
    if voxel_labels is not None:
        changed_keys, changed_cls = voxel_labels.edited()
        if len(changed_keys):
            kept_keys = keys[kept]
            hit = ~outside[kept] & np.isin(kept_keys, changed_keys)
            slot = np.searchsorted(changed_keys, kept_keys[hit])
            new_cls[hit], new_inst[hit] = changed_cls[slot], 0
            out["relabelled"] = int(hit.sum())
            out["relabelled_voxels"] = int(np.isin(changed_keys, kept_keys[hit]).sum())
        fresh_cls = voxel_labels.get(fresh_keys)
    else:
        fresh_cls = np.zeros(len(fresh_keys), np.uint16)
    out["cls"] = np.concatenate([new_cls, fresh_cls]).astype(np.uint16)
    out["inst"] = np.concatenate([new_inst, np.zeros(len(fresh_keys), np.uint32)])
    return out


def point_keys(xyz, resolution):
    """Key of the voxel each point falls into (one per point, unlike voxelize)."""
    return pack(np.floor(np.asarray(xyz, np.float64) / resolution + 1e-9).astype(np.int64))


def vote_voxels(xyz, cls, resolution, classes):
    """(keys, class, purity) of the voxels that labelled points fall into, decided by labels.vote with the class rules."""
    return labels.vote(point_keys(xyz, resolution), cls, priority=classes.priority(), dominant=classes.dominant())


def split_by_role(keys, cls, classes):
    """Voxel keys split by what their class means for a map: (obstacles, free surface).

    Unlabelled voxels count as obstacles; voxels of classes marked 'ignore' are left out.
    """
    role = np.array([labels.OBSTACLE if number == labels.UNLABELED else classes.role(number)
                     for number in range(int(np.max(cls, initial=0)) + 1)])[np.asarray(cls, np.int64)]
    return keys[role == labels.OBSTACLE], keys[role == labels.FREE_ROLE]


def voxels_by_role(xyz, cls, resolution, classes):
    """Voxels of labelled points split by role, each voxel taking the class its points vote for."""
    keys, winner, _ = vote_voxels(xyz, cls, resolution, classes)
    return split_by_role(keys, winner, classes)


def voxels_to_grid(keys, resolution, z_low=-np.inf, z_high=np.inf, empty=UNKNOWN, free_keys=None):
    """Project the voxels of a height band onto the ground plane.

    A voxel map records obstacles only, so cells without one are unknown by default. Pass empty=FREE
    only when the whole area is known to have been observed. `free_keys` are voxels known to be
    traversable surface (a labelled floor): their cells become free at any height, unless an obstacle
    stands in the band above them.
    """
    cells = unpack(keys)
    z = (cells[:, 2] + 0.5) * resolution
    cells = cells[(z >= z_low) & (z <= z_high)]
    ground = unpack(free_keys)[:, :2] if free_keys is not None and len(free_keys) else np.zeros((0, 2), np.int64)
    if not len(cells) and not len(ground):
        raise ValueError("no voxels inside the height band")
    footprint = np.vstack([cells[:, :2], ground])
    low = footprint.min(axis=0)
    size = footprint.max(axis=0) - low + 1
    grid = np.full((size[1], size[0]), empty, np.uint8)
    grid[ground[:, 1] - low[1], ground[:, 0] - low[0]] = FREE
    grid[cells[:, 1] - low[1], cells[:, 0] - low[0]] = OCCUPIED
    return GridMap(grid, resolution, (low[0] * resolution, low[1] * resolution, 0.0))


_SAMPLES = 4


def grid_to_voxels(grid, height):
    """Extrude occupied cells into walls of the given height -> (keys, resolution).

    A grid whose origin is rotated does not line up with the voxel grid, so each of its cells is
    sampled at several points across its area: every voxel a cell reaches into is filled, which keeps
    thin walls closed at any angle.
    """
    if not height > 0:
        raise ValueError("the wall height must be greater than zero")
    rows, columns = np.nonzero(grid.cells == OCCUPIED)
    if grid.origin[2] % (np.pi / 2):
        offsets = (np.arange(_SAMPLES) + 0.5) / _SAMPLES - 0.5
        rows = (rows[:, None, None] + offsets[:, None]).repeat(_SAMPLES, axis=2).ravel()
        columns = (columns[:, None, None] + offsets[None, :]).repeat(_SAMPLES, axis=1).ravel()
    x, y = grid.world(rows, columns)
    layers = max(int(round(height / grid.resolution)), 1)
    base = np.stack([np.floor(x / grid.resolution + 1e-9), np.floor(y / grid.resolution + 1e-9)], axis=1).astype(np.int64)
    base = np.unique(base, axis=0)
    cells = np.concatenate([np.column_stack([base, np.full(len(base), layer)]) for layer in range(layers)])
    return np.unique(pack(cells)), grid.resolution
