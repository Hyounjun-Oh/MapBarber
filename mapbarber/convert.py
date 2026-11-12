"""Conversions between voxel maps, point clouds and 2D occupancy grids."""
import numpy as np

from .grid import OCCUPIED, UNKNOWN, GridMap
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
    cells = np.floor(np.asarray(xyz, np.float64) / resolution + 1e-9).astype(np.int64)
    keys = pack(cells)
    kept = voxel_map.contains(keys)
    covered = np.unique(keys[kept])
    occupied = voxel_map.occupied
    fresh = centers(occupied[~np.isin(occupied, covered, assume_unique=True)], resolution)
    points = np.vstack([xyz[kept], fresh])
    if table is None:
        return points, None
    rows = np.zeros(len(points), table.dtype)
    rows[:int(kept.sum())] = table[kept]
    for axis, name in enumerate("xyz"):
        rows[name][int(kept.sum()):] = fresh[:, axis]
    return points, rows


def voxels_to_grid(keys, resolution, z_low=-np.inf, z_high=np.inf, empty=UNKNOWN):
    """Project the voxels of a height band onto the ground plane.

    A voxel map records obstacles only, so cells without one are unknown by default. Pass empty=FREE
    only when the whole area is known to have been observed.
    """
    cells = unpack(keys)
    z = (cells[:, 2] + 0.5) * resolution
    cells = cells[(z >= z_low) & (z <= z_high)]
    if not len(cells):
        raise ValueError("no voxels inside the height band")
    low = cells[:, :2].min(axis=0)
    size = cells[:, :2].max(axis=0) - low + 1
    grid = np.full((size[1], size[0]), empty, np.uint8)
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
