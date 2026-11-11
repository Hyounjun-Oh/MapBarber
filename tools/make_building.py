"""Generate a very large multi-storey building as a voxel map, for large-map testing (not committed).

    python tools/make_building.py                    # 120 x 80 m, 12 floors, 10 cm voxels -> demo/large/building.bt
    python tools/make_building.py --voxel 0.05       # the same building at 5 cm (about 8x the voxels)
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapbarber import octree  # noqa: E402
from mapbarber.voxels import pack  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo", "large")


def building(length, width, floors, storey, size, seed=11):
    """Occupied cells (N, 3) of an office block: slabs, facade with windows, corridors, rooms, columns, cores."""
    rng = np.random.default_rng(seed)
    nx, ny, nz = int(round(length / size)), int(round(width / size)), int(round(storey / size))
    c = lambda metres: int(round(metres / size))  # noqa: E731
    wall = max(c(0.2), 1)
    plan = np.zeros((nx, ny), bool)
    plan[:wall], plan[-wall:], plan[:, :wall], plan[:, -wall:] = True, True, True, True
    corridor_low, corridor_high = ny // 2 - c(1.5), ny // 2 + c(1.5)
    thin = max(c(0.1), 1)
    plan[:, corridor_low - thin:corridor_low] = True
    plan[:, corridor_high:corridor_high + thin] = True
    doors = np.zeros((nx, ny), bool)
    for x in range(c(6), nx - c(2), c(6)):
        plan[x:x + thin, :corridor_low] = True
        plan[x:x + thin, corridor_high:] = True
        doors[x - c(2.2):x - c(1.2), corridor_low - thin:corridor_high + thin] = True
    plan[:, corridor_low:corridor_high] = False
    columns = np.zeros((nx, ny), bool)
    for x in range(c(6), nx, c(12)):
        for y in range(c(5), ny, c(10)):
            columns[x:x + c(0.6), y:y + c(0.6)] = True
    cores = np.zeros((nx, ny), bool)
    for x in (c(20), nx - c(26)):
        cores[x:x + c(6), corridor_high + thin:corridor_high + thin + c(8)] = True
        cores[x + wall:x + c(6) - wall, corridor_high + thin + wall:corridor_high + thin + c(8) - wall] = False
    windows = np.zeros((nx, ny), bool)
    for x in range(c(1.5), nx - c(3), c(3)):
        windows[x:x + c(1.8), :wall] = True
        windows[x:x + c(1.8), -wall:] = True

    parts = []
    slab = np.stack(np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij"), -1).reshape(-1, 2)
    door_top, sill, head = c(2.1), c(0.9), c(2.3)
    for floor in range(floors):
        base = floor * nz
        for layer in range(max(c(0.2), 1)):
            parts.append(np.column_stack([slab, np.full(len(slab), base + layer)]))
        for layer in range(max(c(0.2), 1), nz):
            keep = plan | columns | cores
            if layer < door_top:
                keep = keep & ~doors
            if sill <= layer < head:
                keep = keep & ~windows
            xy = np.argwhere(keep)
            parts.append(np.column_stack([xy, np.full(len(xy), base + layer)]))
    roof = floors * nz
    parts.append(np.column_stack([slab, np.full(len(slab), roof)]))
    cells = np.vstack(parts)
    specks = max(len(cells) // 2000, 100)
    noise = np.column_stack([rng.integers(1, nx - 1, specks), rng.integers(1, ny - 1, specks), rng.integers(1, roof, specks)])
    return np.vstack([cells, noise])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--length", type=float, default=120.0)
    parser.add_argument("--width", type=float, default=80.0)
    parser.add_argument("--floors", type=int, default=12)
    parser.add_argument("--storey", type=float, default=3.6)
    parser.add_argument("--voxel", type=float, default=0.10)
    parser.add_argument("--name", default="building")
    args = parser.parse_args()
    os.makedirs(OUT, exist_ok=True)
    start = time.time()
    cells = building(args.length, args.width, args.floors, args.storey, args.voxel)
    keys = np.unique(pack(cells))
    built = time.time()
    path = os.path.join(OUT, f"{args.name}.bt")
    octree.write_bt(path, keys, args.voxel)
    print(f"{len(keys):,} voxels at {args.voxel:g} m  ·  built in {built - start:.1f} s, written in {time.time() - built:.1f} s  ·  "
          f"{path} ({os.path.getsize(path) / 1e6:.1f} MB)")
