"""Generate the synthetic example maps in examples/ (deterministic)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapbarber import formats, grid  # noqa: E402
from mapbarber.grid import FREE, OCCUPIED, UNKNOWN  # noqa: E402
from mapbarber.voxels import pack  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
rng = np.random.default_rng(2024)


def box(x0, x1, y0, y1, z0, z1, size):
    axes = [np.arange(int(round(a / size)), int(round(b / size))) for a, b in ((x0, x1), (y0, y1), (z0, z1))]
    return np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)


def room_cells(size):
    parts = [box(0, 6, 0, 4, 0, size, size),
             box(0, 6, 0, size, 0, 2.4, size), box(0, 6, 4 - size, 4, 0, 2.4, size),
             box(0, size, 0, 4, 0, 2.4, size), box(6 - size, 6, 0, 4, 0, 2.4, size),
             box(2.0, 3.4, 1.4, 2.4, 0.70, 0.75, size)]
    for x, y in ((2.05, 1.45), (3.30, 1.45), (2.05, 2.30), (3.30, 2.30)):
        parts.append(box(x, x + 0.05, y, y + 0.05, 0, 0.70, size))
    parts += [box(4.6, 5.0, 2.8, 3.95, 0, 1.8, size), box(1.0, 1.3, 3.0, 3.3, 0, 2.4, size)]
    cells = np.unique(np.vstack(parts), axis=0)
    door = (cells[:, 1] == 0) & (cells[:, 0] >= int(0.8 / size)) & (cells[:, 0] < int(1.7 / size)) & (cells[:, 2] < int(2.0 / size))
    gap = (cells[:, 0] == int(6 / size) - 1) & (cells[:, 1] >= int(1.6 / size)) & (cells[:, 1] < int(2.0 / size)) \
        & (cells[:, 2] >= int(0.9 / size)) & (cells[:, 2] < int(1.3 / size))
    return cells[~door & ~gap]


def voxel_example(size=0.05):
    cells = [room_cells(size)]
    for _ in range(60):
        seed = np.array([rng.uniform(0.3, 5.7), rng.uniform(0.3, 3.7), rng.uniform(0.2, 2.2)]) / size
        cells.append((seed + rng.integers(0, 2, size=(rng.integers(1, 4), 3))).astype(np.int64))
    cells.append(box(3.6, 4.0, 0.8, 1.1, 1.5, 1.65, size))
    formats.save_voxels(os.path.join(OUT, "room.bt"), np.unique(pack(np.vstack(cells))), size)


def surface(x0, x1, y0, y1, z0, z1, count):
    return np.column_stack([rng.uniform(x0, x1, count), rng.uniform(y0, y1, count), rng.uniform(z0, z1, count)])


def cloud_example():
    parts = [surface(0, 6, 0, 4, 0, 0, 18000), surface(0, 6, 0, 0, 0, 2.4, 6000), surface(0, 6, 4, 4, 0, 2.4, 6000),
             surface(0, 0, 0, 4, 0, 2.4, 4000), surface(6, 6, 0, 4, 0, 2.4, 4000), surface(2.0, 3.4, 1.4, 2.4, 0.75, 0.75, 2500),
             surface(4.6, 5.0, 2.8, 2.8, 0, 1.8, 1500), surface(4.6, 4.6, 2.8, 3.95, 0, 1.8, 1500)]
    xyz = np.vstack(parts) + rng.normal(0, 0.006, size=(sum(len(p) for p in parts), 3))
    strays = np.column_stack([rng.uniform(0, 6, 350), rng.uniform(0, 4, 350), rng.uniform(0, 2.4, 350)])
    streak = np.linspace([3.0, 0.5, 0.4], [4.2, 1.8, 2.0], 220) + rng.normal(0, 0.015, size=(220, 3))
    xyz = np.vstack([xyz, strays, streak])
    table = np.zeros(len(xyz), np.dtype([("x", "f4"), ("y", "f4"), ("z", "f4"), ("intensity", "f4"), ("rgb", "f4")]))
    for i, axis in enumerate("xyz"):
        table[axis] = xyz[:, i]
    table["intensity"] = np.clip(60 + 40 * np.sin(xyz[:, 0] * 2.1) + rng.normal(0, 8, len(xyz)), 0, 255)
    shade = (120 + 100 * (xyz[:, 2] / 2.4)).clip(0, 255).astype(np.uint32)
    packed = (shade << 16) | ((200 - shade // 2) << 8) | (255 - shade)
    table["rgb"] = packed.astype(np.uint32).view(np.float32)
    formats.save_cloud(os.path.join(OUT, "scan.pcd"), xyz, table)


def grid_example():
    cells = np.full((300, 420), UNKNOWN, np.uint8)
    cells[30:270, 30:390] = FREE
    for r0, r1, c0, c1 in ((28, 31, 28, 392), (269, 272, 28, 392), (28, 272, 28, 31), (28, 272, 389, 392),
                           (28, 272, 200, 203), (150, 153, 30, 200), (150, 153, 203, 390)):
        cells[r0:r1, c0:c1] = OCCUPIED
    for r0, r1, c0, c1 in ((90, 110, 200, 203), (200, 222, 200, 203), (150, 153, 100, 122), (150, 153, 290, 312)):
        cells[r0:r1, c0:c1] = FREE
    cells[150:153, 330:352] = FREE
    free = np.argwhere(cells == FREE)
    for r, c in free[rng.choice(len(free), 260, replace=False)]:
        cells[r:r + rng.integers(1, 3), c:c + rng.integers(1, 3)] = OCCUPIED
    cells[60:70, 60:75] = UNKNOWN
    grid.save(os.path.join(OUT, "floor.yaml"), grid.GridMap(cells, 0.05, (-1.5, -1.5, 0.0)))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    voxel_example()
    cloud_example()
    grid_example()
    for name in sorted(os.listdir(OUT)):
        print(f"{name:12} {os.path.getsize(os.path.join(OUT, name)):>9} bytes")
