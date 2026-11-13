"""Generate the usability demo set in demo/ from simulated sensors (deterministic).

    python tools/make_demo.py            # demo/ (committed files)
    python tools/make_demo.py --large    # also demo/large/ for performance checks (not committed)
"""
import math
import os
import shutil
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapbarber import formats, grid, octree  # noqa: E402
from mapbarber.grid import FREE, OCCUPIED, UNKNOWN, GridMap  # noqa: E402
from mapbarber.voxels import OFFSET, pack, unpack, voxelize  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "demo")
RES = 0.05
rng = np.random.default_rng(7)

MATERIALS = {  # rgb, reflectivity, dropout probability
    "floor": ((150, 146, 136), 0.55, 0.0), "ceiling": ((228, 228, 224), 0.8, 0.0), "wall": ((214, 206, 190), 0.75, 0.0),
    "wood": ((150, 100, 60), 0.5, 0.0), "metal": ((120, 130, 140), 0.9, 0.05), "concrete": ((170, 170, 165), 0.6, 0.0),
    "fabric": ((60, 80, 140), 0.35, 0.02), "black": ((25, 25, 28), 0.08, 0.995), "person": ((200, 120, 90), 0.4, 0.05),
}


def office_boxes(with_person):
    b = [(0, 8, 0, 6, -0.05, 0, "floor"), (0, 8, 0, 6, 3.0, 3.05, "ceiling"),
         (-0.1, 0, 0, 6, 0, 3, "wall"), (8, 8.1, 0, 6, 0, 3, "wall"),
         (0, 1.0, -0.1, 0, 0, 3, "wall"), (2.0, 8, -0.1, 0, 0, 3, "wall"), (1.0, 2.0, -0.1, 0, 2.1, 3, "wall"),
         (0, 3.0, 6, 6.1, 0, 3, "wall"), (5.0, 8, 6, 6.1, 0, 3, "wall"),
         (3.0, 5.0, 6, 6.1, 0, 1.0, "wall"), (3.0, 5.0, 6, 6.1, 2.2, 3, "wall"),
         (2.0, 3.6, 3.0, 3.8, 0.72, 0.75, "wood"), (2.6, 3.0, 3.6, 3.65, 0.75, 1.1, "black"),
         (6.8, 7.9, 0.3, 2.3, 0, 2.0, "metal"), (0.1, 0.7, 4.5, 5.9, 0, 1.1, "wood"),
         (4.2, 4.6, 2.6, 3.0, 0, 3.0, "concrete"), (3.0, 3.5, 2.3, 2.8, 0.42, 0.47, "fabric"),
         (3.0, 3.5, 2.25, 2.3, 0.47, 0.95, "fabric")]
    for x, y in ((2.03, 3.03), (3.52, 3.03), (2.03, 3.72), (3.52, 3.72)):
        b.append((x, x + 0.05, y, y + 0.05, 0, 0.72, "wood"))
    if with_person:
        b.append((5.2, 5.5, 4.0, 4.3, 0, 1.75, "person"))
    return b


CAMERA_POSES = [(1.5, 1.5, 30, -15), (1.5, 1.5, 90, -15), (4.0, 1.2, 60, -12), (4.0, 1.2, 120, -12),
                (6.0, 2.5, 20, -15), (6.0, 3.5, 90, -10), (6.0, 4.5, 180, -15), (4.0, 4.6, 220, -12),
                (2.0, 4.8, 270, -15), (1.5, 3.0, 0, -10), (4.0, 3.0, 300, -20), (6.5, 1.5, 240, -15),
                (2.5, 2.0, 45, 25), (5.5, 4.0, 225, 25)]
PERSON_POSES = {5, 6}
WIDTH, HEIGHT, FOV_X = 320, 240, math.radians(70)


def cast(origin, directions, boxes):
    """First box hit along each ray -> (range, box index, face normal), inf where nothing is hit."""
    lo = np.array([[b[0], b[2], b[4]] for b in boxes], float)
    hi = np.array([[b[1], b[3], b[5]] for b in boxes], float)
    ranges = np.full(len(directions), np.inf)
    index = np.full(len(directions), -1)
    normal = np.zeros((len(directions), 3))
    for start in range(0, len(directions), 8192):
        d = directions[start:start + 8192]
        inverse = 1.0 / np.where(np.abs(d) < 1e-12, 1e-12, d)
        t1 = (lo[None] - origin) * inverse[:, None]
        t2 = (hi[None] - origin) * inverse[:, None]
        near = np.minimum(t1, t2)
        t_in = near.max(axis=2)
        t_out = np.maximum(t1, t2).min(axis=2)
        t = np.where((t_out >= t_in) & (t_in > 1e-6), t_in, np.inf)
        best = np.argmin(t, axis=1)
        rows = np.arange(len(d))
        ranges[start:start + 8192] = t[rows, best]
        index[start:start + 8192] = best
        axis = np.argmax(near[rows, best], axis=1)
        n = np.zeros((len(d), 3))
        n[rows, axis] = -np.sign(d[rows, axis])
        normal[start:start + 8192] = n
    index[~np.isfinite(ranges)] = -1
    return ranges, index, normal


def camera_frame(pose):
    """One simulated depth frame -> dict with organized optical-frame points, world points, colours, intensity."""
    x, y, yaw, pitch = pose
    origin = np.array([x, y, 1.1])
    yaw, pitch = math.radians(yaw), math.radians(pitch)
    forward = np.array([math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch)])
    right = np.array([math.sin(yaw), -math.cos(yaw), 0.0])
    down = np.cross(forward, right)
    focal = (WIDTH / 2) / math.tan(FOV_X / 2)
    u, v = np.meshgrid(np.arange(WIDTH), np.arange(HEIGHT))
    xc, yc = (u.ravel() - WIDTH / 2 + 0.5) / focal, (v.ravel() - HEIGHT / 2 + 0.5) / focal
    rays = xc[:, None] * right + yc[:, None] * down + forward
    rays /= np.linalg.norm(rays, axis=1, keepdims=True)
    boxes = office_boxes(CAMERA_POSES.index(pose) in PERSON_POSES)
    ranges, index, normal = cast(origin, rays, boxes)
    cos_axis = rays @ forward
    depth = ranges * cos_axis
    names = np.array([b[6] for b in boxes] + ["none"])
    material = names[index]
    dropout = np.array([MATERIALS.get(m, ((0, 0, 0), 0, 1.0))[2] for m in material])
    depth[(rng.random(len(depth)) < dropout) | (rng.random(len(depth)) < 0.004)] = np.nan
    depth[(depth < 0.3) | (depth > 5.0)] = np.nan
    depth = depth + rng.normal(0, 1, len(depth)) * (0.002 + 0.0025 * np.nan_to_num(depth) ** 2)
    image = depth.reshape(HEIGHT, WIDTH)
    for a, b in ((image[:, 1:], image[:, :-1]), (image[1:, :], image[:-1, :])):
        jump = np.abs(a - b) > 0.25
        chosen = jump & (rng.random(jump.shape) < 0.6)
        near, far = np.fmin(a, b), np.fmax(a, b)
        mixed = near + rng.random(jump.shape) * (far - near)
        a[chosen & (a >= b)] = mixed[chosen & (a >= b)]
        b[chosen & (b > a)] = mixed[chosen & (b > a)]
    speckle = rng.random(image.shape) < 0.0006
    image[speckle] *= rng.uniform(0.3, 0.9, speckle.sum())
    depth = image.ravel()
    optical = np.stack([xc * depth, yc * depth, depth], axis=1)
    world = origin + rays * (depth / cos_axis)[:, None]
    rgb = np.array([MATERIALS.get(m, ((0, 0, 0), 0, 0))[0] for m in material], float)
    rgb = np.clip(rgb + rng.normal(0, 6, rgb.shape), 0, 255).astype(np.uint8)
    reflect = np.array([MATERIALS.get(m, ((0, 0, 0), 0, 0))[1] for m in material])
    intensity = np.clip(reflect * np.abs(np.einsum("ij,ij->i", normal, rays)) * 255 + rng.normal(0, 4, len(rays)), 0, 255)
    return {"origin": origin, "rays": rays, "depth": depth, "cos": cos_axis, "optical": optical, "world": world,
            "rgb": rgb, "intensity": intensity}


def pack_rgb(rgb):
    value = (rgb[:, 0].astype(np.uint32) << 16) | (rgb[:, 1].astype(np.uint32) << 8) | rgb[:, 2].astype(np.uint32)
    return value.view(np.float32)


def cloud_table(xyz, fields):
    dtype = [("x", "f4"), ("y", "f4"), ("z", "f4")] + [(name, values.dtype.str) for name, values in fields]
    table = np.zeros(len(xyz), np.dtype(dtype))
    for i, axis in enumerate("xyz"):
        table[axis] = xyz[:, i]
    for name, values in fields:
        table[name] = values
    return table


def write_bt_with_free(path, occupied, free, resolution):
    """Binary octree holding occupied and free leaves, like a map saved from a live mapping node."""
    keys = np.concatenate([occupied, free])
    labels = np.concatenate([np.full(len(occupied), 2, np.uint8), np.full(len(free), 1, np.uint8)])
    codes = octree.morton_encode(unpack(keys) + OFFSET)
    order = np.argsort(codes)
    codes, labels = codes[order], labels[order]
    body, count = bytearray(), [0]

    def node(low, high, level):
        count[0] += 1
        states, inner = 0, []
        for octant, a, b, solid in octree._octants(codes, low, high, level):
            uniform = labels[a] if labels[a:b].min() == labels[a:b].max() else 0
            if solid and uniform:
                states |= int(uniform) << (2 * octant)
                count[0] += 1
            else:
                states |= 3 << (2 * octant)
                inner.append((a, b, level - 1))
        body.extend(bytes((states & 0xFF, states >> 8)))
        for args in inner:
            node(*args)

    node(0, len(codes), octree.DEPTH)
    with open(path, "wb") as f:
        f.write(b"# Octomap OcTree binary file\n")
        f.write(f"id OcTree\nsize {count[0]}\nres {resolution:g}\ndata\n".encode())
        f.write(body)


def write_color_ot(path, keys, colours, resolution, log_odds=2.0):
    """Full ColorOcTree: every node stores log-odds, an RGB colour and a child mask."""
    codes = octree.morton_encode(unpack(keys) + OFFSET)
    order = np.argsort(codes)
    codes, colours = codes[order], colours[order].astype(np.float64)
    body, count = bytearray(), [0]
    value = struct.pack("<f", log_odds)

    def node(low, high, level):
        count[0] += 1
        start = len(body)
        body.extend(value + b"\0\0\0\0")
        if level == 0:
            body[start + 4:start + 7] = bytes(int(c) for c in colours[low])
            return colours[low]
        children = list(octree._octants(codes, low, high, level))
        body[start + 7] = sum(1 << octant for octant, *_ in children)
        mean = np.mean([node(a, b, level - 1) for _, a, b, _ in children], axis=0)
        body[start + 4:start + 7] = bytes(int(c) for c in mean)
        return mean

    sys.setrecursionlimit(10000)
    node(0, len(codes), octree.DEPTH)
    with open(path, "wb") as f:
        f.write(b"# Octomap OcTree file\n")
        f.write(f"id ColorOcTree\nsize {count[0]}\nres {resolution:g}\ndata\n".encode())
        f.write(body)


def make_office(out):
    frames = [camera_frame(pose) for pose in CAMERA_POSES]
    world = np.vstack([f["world"] for f in frames])
    rgb = np.vstack([f["rgb"] for f in frames])
    intensity = np.concatenate([f["intensity"] for f in frames]).astype(np.float32)
    valid = np.all(np.isfinite(world), axis=1)
    world, rgb, intensity = world[valid], rgb[valid], intensity[valid]

    occupied = voxelize(world, RES)
    octree.write_bt(os.path.join(out, "office_octomap.bt"), occupied, RES)
    shutil.copy(os.path.join(out, "office_octomap.bt"), os.path.join(out, "office_octomap.bt.bak_20250101_090000"))
    formats.save_voxels(os.path.join(out, "office_voxels.npz"), occupied, RES)

    samples = []
    for f in frames:
        pick = np.flatnonzero(np.isfinite(f["depth"]))[::9]
        ranges = f["depth"][pick] / f["cos"][pick]
        steps = np.arange(0, 5.0, RES / 2)
        for start in range(0, len(pick), 4000):
            r, d = ranges[start:start + 4000], f["rays"][pick[start:start + 4000]]
            mask = steps[None, :] < (r[:, None] - RES)
            points = f["origin"] + d[:, None, :] * steps[None, :, None]
            samples.append(points[mask])
    free = np.setdiff1d(voxelize(np.vstack(samples), RES), occupied, assume_unique=True)
    write_bt_with_free(os.path.join(out, "office_octomap_with_free.bt"), occupied, free, RES)

    cells = np.floor(world / RES + 1e-9).astype(np.int64)
    keys = pack(cells)
    unique, inverse = np.unique(keys, return_inverse=True)
    colour = np.zeros((len(unique), 3))
    np.add.at(colour, inverse, rgb)
    colour /= np.bincount(inverse, minlength=len(unique))[:, None]
    write_color_ot(os.path.join(out, "office_color.ot"), unique, colour.astype(np.uint8), RES)

    pick = rng.choice(len(world), 120_000, replace=False)
    formats.save_cloud(os.path.join(out, "map_cloud.pcd"), world[pick],
                       cloud_table(world[pick], [("intensity", intensity[pick]), ("rgb", pack_rgb(rgb[pick]))]))

    frame = frames[9]
    organized = cloud_table(frame["optical"], [("rgb", pack_rgb(frame["rgb"]))])
    write_organized_pcd(os.path.join(out, "depth_frame.pcd"), organized, WIDTH, HEIGHT)
    return len(occupied), len(free), len(unique)


def write_organized_pcd(path, table, width, height):
    header = ("# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\nFIELDS x y z rgb\nSIZE 4 4 4 4\nTYPE F F F F\n"
              f"COUNT 1 1 1 1\nWIDTH {width}\nHEIGHT {height}\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {width * height}\n"
              "DATA binary\n")
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(np.ascontiguousarray(table).tobytes())


def make_lidar(out):
    boxes = office_boxes(True)
    origin = np.array([4.0, 2.0, 0.8])
    elevations = np.radians(np.arange(-15, 16, 2))
    azimuths = np.radians(np.arange(0, 360, 0.2))
    el, az = np.meshgrid(elevations, azimuths, indexing="ij")
    rays = np.stack([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)], axis=-1).reshape(-1, 3)
    ranges, index, normal = cast(origin, rays, boxes)
    ranges = ranges + rng.normal(0, 0.02, len(ranges))
    dust = rng.random(len(ranges)) < 0.012
    ranges[dust] = rng.uniform(0.4, 3.0, dust.sum())
    keep = np.isfinite(ranges) & (ranges < 30)
    points = origin + rays * ranges[:, None]
    names = np.array([b[6] for b in boxes] + ["none"])
    reflect = np.array([MATERIALS.get(m, ((0, 0, 0), 0.1, 0))[1] for m in names[index]])
    intensity = np.clip(reflect * np.abs(np.einsum("ij,ij->i", normal, rays)) * 100 + rng.normal(0, 3, len(rays)), 0, 255)
    intensity[dust] = rng.uniform(0, 8, dust.sum())
    ring = np.repeat(np.arange(len(elevations), dtype=np.uint16), len(azimuths))
    time = np.tile(np.arange(len(azimuths)) / len(azimuths) * 0.1, len(elevations))
    table = cloud_table(points[keep], [("intensity", intensity[keep].astype(np.float32)), ("ring", ring[keep]),
                                       ("time", time[keep].astype(np.float64))])
    formats.save_cloud(os.path.join(out, "lidar_sweep.ply"), points[keep], table)

    survey = np.array([[x, y, 0.0] for x in np.arange(0.5, 8, 0.5) for y in np.arange(0.5, 6, 0.5)])
    survey[:, 2] = rng.normal(0, 0.004, len(survey))
    with open(os.path.join(out, "survey_points.csv"), "w") as f:
        f.write("x,y,z,label\n")
        for i, (x, y, z) in enumerate(survey):
            f.write(f"{x:.4f},{y:.4f},{z:.4f},P{i:03d}\n")
    shelf = points[keep][(points[keep][:, 0] > 6.6) & (points[keep][:, 1] < 2.5)]
    colours = np.clip(80 + shelf[:, 2:3] * 60 + rng.normal(0, 5, (len(shelf), 3)), 0, 255).astype(int)
    with open(os.path.join(out, "colored_points.xyz"), "w") as f:
        for p, c in zip(shelf, colours):
            f.write(f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f} {c[0]} {c[1]} {c[2]}\n")
    np.save(os.path.join(out, "cloud_points.npy"), points[keep][::4].astype(np.float32))
    return int(keep.sum())


def rect(cells, resolution, x0, x1, y0, y1, value=True):
    cells[int(round(y0 / resolution)):int(round(y1 / resolution)), int(round(x0 / resolution)):int(round(x1 / resolution))] = value


def lidar_slam(truth, resolution, path, beams=360, max_range=25.0):
    """Ray-cast a 2D scanner along a path over a ground-truth obstacle grid -> occupancy states."""
    height, width = truth.shape
    hits = np.zeros(truth.shape, np.int32)
    misses = np.zeros(truth.shape, np.int32)
    angles = np.linspace(0, 2 * np.pi, beams, endpoint=False)
    steps = (np.arange(int(max_range / resolution)) + 0.5) * resolution
    for x, y in path:
        jitter = angles + rng.normal(0, 0.002, beams)
        px = x + np.cos(jitter)[:, None] * steps[None, :]
        py = y + np.sin(jitter)[:, None] * steps[None, :]
        cx, cy = np.floor(px / resolution).astype(int), np.floor(py / resolution).astype(int)
        inside = (cx >= 0) & (cx < width) & (cy >= 0) & (cy < height)
        blocked = np.zeros(cx.shape, bool)
        blocked[inside] = truth[cy[inside], cx[inside]]
        first = np.where(blocked.any(axis=1), blocked.argmax(axis=1), cx.shape[1])
        before = (np.arange(cx.shape[1])[None, :] < first[:, None]) & inside
        np.add.at(misses, (cy[before], cx[before]), 1)
        hit_rows = np.flatnonzero(first < cx.shape[1])
        np.add.at(hits, (cy[hit_rows, first[hit_rows]], cx[hit_rows, first[hit_rows]]), 1)
    cells = np.full(truth.shape, UNKNOWN, np.uint8)
    cells[misses > 0] = FREE
    cells[(hits > 0) & (hits >= 0.25 * (hits + misses))] = OCCUPIED
    return cells


def polyline(points, spacing):
    out = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        n = max(int(math.hypot(x1 - x0, y1 - y0) / spacing), 1)
        out += [(x0 + (x1 - x0) * t / n, y0 + (y1 - y0) * t / n) for t in range(n)]
    return out + [points[-1]]


def make_warehouse(out, scale=1):
    res = RES
    width_m, height_m = 50.0 * scale, 40.0 * scale
    truth = np.zeros((int(height_m / res), int(width_m / res)), bool)
    rect(truth, res, 1, width_m - 1, 1, 1.2)
    rect(truth, res, 1, width_m - 1, height_m - 1.2, height_m - 1)
    rect(truth, res, 1, 1.2, 1, height_m - 1)
    rect(truth, res, width_m - 1.2, width_m - 1, 1, 15)
    rect(truth, res, width_m - 1.2, width_m - 1, 20, height_m - 1)
    racks = [6 + 5 * k for k in range(int((width_m - 16) / 5))]
    for x0 in racks:
        rect(truth, res, x0, x0 + 1.2, 6, height_m - 10)
    for x in range(5, int(width_m) - 3, 8):
        rect(truth, res, x, x + 0.4, height_m - 6.2, height_m - 5.8)
    office_x = width_m - 12
    rect(truth, res, office_x, office_x + 0.15, height_m - 10, height_m - 7)
    rect(truth, res, office_x, office_x + 0.15, height_m - 5.8, height_m - 1)
    rect(truth, res, office_x, office_x + 3, height_m - 10, height_m - 9.85)
    rect(truth, res, office_x + 8, width_m - 1, height_m - 10, height_m - 9.85)
    aisles = [x0 + 1.2 + 1.9 for x0 in racks]
    route = [(3.5, 3.5), (width_m - 5, 3.5), (width_m - 5, height_m - 7.5), (3.5, height_m - 7.5), (3.5, 3.5)]
    for i, x in enumerate(aisles):
        route += [(x, 3.5), (x, height_m - 7.5)] if i % 2 == 0 else [(x, height_m - 7.5), (x, 3.5)]
    route += [(office_x - 2, height_m - 6.4), (office_x + 4, height_m - 6.4), (office_x + 6, height_m - 3)]
    cells = lidar_slam(truth, res, polyline(route, 1.0))

    free = np.argwhere(cells == FREE)
    for r, c in free[rng.choice(len(free), 220 * scale * scale, replace=False)]:
        cells[r:r + rng.integers(1, 3), c:c + rng.integers(1, 3)] = OCCUPIED
    for t in np.linspace(0, 1, 30):
        x, y = aisles[1] + 0.5 * math.sin(t * 9), 8 + t * 18
        rect(cells, res, x, x + 0.1, y, y + 0.1, OCCUPIED)
    ghost_x = racks[2] + 1.2 + 0.4
    ghost = np.zeros_like(truth)
    rect(ghost, res, ghost_x, ghost_x + res, 10, 22)
    cells[ghost & (cells == FREE)] = OCCUPIED
    rect(cells, res, 20, 24, 1.9, 4.6, UNKNOWN)
    suffix = "" if scale == 1 else "_large"
    grid.save(os.path.join(out, f"warehouse_map{suffix}.yaml"), GridMap(cells, res, (-width_m / 2, -height_m / 2, 0.0)))
    return cells.shape


def make_lab(out):
    res = RES
    truth = np.zeros((240, 300), bool)
    rect(truth, res, 0.5, 14.5, 0.5, 0.6)
    rect(truth, res, 0.5, 14.5, 11.4, 11.5)
    rect(truth, res, 0.5, 0.6, 0.5, 11.5)
    rect(truth, res, 14.4, 14.5, 0.5, 11.5)
    rect(truth, res, 8.0, 8.1, 0.5, 4.5)
    rect(truth, res, 8.0, 8.1, 5.7, 11.5)
    rect(truth, res, 2.0, 5.0, 8.0, 9.0)
    rect(truth, res, 10.5, 13.0, 2.0, 3.0)
    cells = lidar_slam(truth, res, polyline([(3, 3), (6, 5), (9, 5.1), (12, 7), (12, 10), (5, 10.5), (2, 6)], 0.5))
    free = np.argwhere(cells == FREE)
    for r, c in free[rng.choice(len(free), 40, replace=False)]:
        cells[r, c] = OCCUPIED
    meta = {"negate": 1, "occupied_thresh": 0.65, "free_thresh": 0.25}
    grid.save(os.path.join(out, "lab_map.png"), GridMap(cells, res, (-2.0, -3.0, 0.35), meta))

    mask = np.full((150, 200), FREE, np.uint8)
    rect(mask, res, 0, 10, 0, 0.5, UNKNOWN)
    rect(mask, res, 1.0, 3.0, 2.0, 4.0, OCCUPIED)
    rect(mask, res, 6.0, 9.0, 4.5, 6.0, OCCUPIED)
    rect(mask, res, 4.0, 4.5, 0.5, 7.5, OCCUPIED)
    grid.save(os.path.join(out, "keepout_mask.yaml"), GridMap(mask, res, (-5.0, -3.75, 0.0), {"mode": "raw"}))


def make_broken(out):
    with open(os.path.join(out, "office_octomap.bt"), "rb") as f:
        data = f.read()
    with open(os.path.join(out, "broken_truncated.bt"), "wb") as f:
        f.write(data[:len(data) * 3 // 5])
    with open(os.path.join(out, "not_a_map.yaml"), "w") as f:
        f.write("# controller parameters, not a map description\nmax_speed: 0.5\nacceleration: 1.2\n")
    with open(os.path.join(out, "not_points.txt"), "w") as f:
        f.write("Meeting notes\n- order new camera bracket\n- recalibrate on Friday\n")


STREET_CLASSES = ((1, "road", "free", False), (2, "sidewalk", "free", False), (3, "building", "obstacle", False),
                  (4, "parked car", "obstacle", False), (5, "pole", "obstacle", False),
                  (6, "vegetation", "obstacle", False), (7, "person", "ignore", True), (8, "moving car", "ignore", False))
STREET_REFLECT = {1: 0.25, 2: 0.4, 3: 0.6, 4: 0.85, 5: 0.7, 6: 0.3, 7: 0.35, 8: 0.85}


def street_boxes(frame):
    """Boxes of a street at one moment: (x0, x1, y0, y1, z0, z1, class)."""
    b = [(-30, 90, -4, 4, -0.05, 0, 1), (-30, 90, 4, 7, -0.05, 0.12, 2), (-30, 90, -7, -4, -0.05, 0.12, 2),
         (-30, 24, 7, 7.5, 0, 9, 3), (28, 90, 7, 7.5, 0, 12, 3), (-30, 90, -7.5, -7, 0, 8, 3),
         (10, 14.5, 2.2, 3.9, 0, 1.5, 4), (31, 35.5, -3.9, -2.2, 0, 1.6, 4), (44, 48.5, 2.2, 3.9, 0, 1.4, 4)]
    for x in range(4, 60, 12):
        b.append((x, x + 0.2, 6.4, 6.6, 0.12, 4.5, 5))
    for x in (18, 38, 52):
        b += [(x, x + 0.3, -5.8, -5.5, 0.12, 2.4, 6), (x - 1.1, x + 1.4, -6.9, -4.4, 2.4, 4.6, 6)]
    walker = 9 + 0.45 * frame
    b.append((walker, walker + 0.4, 5.2, 5.6, 0.12, 1.75, 7))
    car = 70 - 2.2 * frame
    b.append((car, car + 4.4, -3.6, -1.9, 0, 1.5, 8))
    return b


def make_drive(out, frames=16):
    """KITTI-style sequence: velodyne/*.bin in the sensor frame, poses.txt, a class list and noisy predictions."""
    folder = os.path.join(out, "drive")
    shutil.rmtree(folder, ignore_errors=True)
    for name in ("velodyne", "predictions"):
        os.makedirs(os.path.join(folder, name))
    elevations = np.radians(np.linspace(-15, 10, 16))
    azimuths = np.radians(np.arange(-180, 180, 0.5))
    el, az = np.meshgrid(elevations, azimuths, indexing="ij")
    local_rays = np.stack([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)], axis=-1).reshape(-1, 3)
    poses, total = [], 0
    for frame in range(frames):
        yaw = 0.015 * frame
        turn = np.array([[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]])
        origin = np.array([1.2 * frame, 0.25 * math.sin(frame / 4), 1.73])
        boxes = street_boxes(frame)
        rays = local_rays @ turn.T
        ranges, index, normal = cast(origin, rays, boxes)
        ranges = ranges + rng.normal(0, 0.015, len(ranges))
        keep = np.isfinite(ranges) & (ranges > 1.0) & (ranges < 45)
        classes = np.array([b[6] for b in boxes] + [0])[index][keep]
        world = origin + rays[keep] * ranges[keep, None]
        local = (world - origin) @ turn
        reflect = np.array([STREET_REFLECT[c] for c in classes])
        intensity = np.clip(reflect * np.abs(np.einsum("ij,ij->i", normal[keep], rays[keep])) + rng.normal(0, 0.02, len(classes)), 0, 1)
        name = f"{frame:06d}"
        np.column_stack([local, intensity]).astype("<f4").tofile(os.path.join(folder, "velodyne", name + ".bin"))
        guess = classes.astype(np.uint16).copy()
        moving = np.isin(guess, (7, 8))
        if frame % 2:
            guess[moving & (guess == 8)] = 4
        edge = (np.abs(np.abs(world[:, 1]) - 4.0) < 0.35) & np.isin(guess, (1, 2))
        flip = edge & (rng.random(len(guess)) < 0.4)
        guess[flip] = np.where(guess[flip] == 1, 2, 1)
        stray = rng.random(len(guess)) < 0.02
        guess[stray] = rng.choice([1, 2, 3, 4, 5, 6], int(stray.sum()))
        guess.astype("<u4").tofile(os.path.join(folder, "predictions", name + ".label"))
        pose = np.eye(4)[:3]
        pose[:, :3], pose[:, 3] = turn, origin
        poses.append(" ".join(f"{v:.9g}" for v in pose.ravel()))
        total += len(classes)
    with open(os.path.join(folder, "poses.txt"), "w") as f:
        f.write("\n".join(poses) + "\n")
    from mapbarber.labels import ClassList
    classes = ClassList()
    for number, name, role, wins in STREET_CLASSES:
        classes.set(number, name, role=role, wins=wins)
    classes.save(os.path.join(folder, "labels.yaml"))
    return total


def make_large(out):
    os.makedirs(out, exist_ok=True)
    x, y, z = np.meshgrid(np.arange(0, 400), np.arange(0, 300), np.arange(0, 60), indexing="ij")
    shell = (x % 40 == 0) | (y % 30 == 0) | (z == 0)
    keys = pack(np.stack([x[shell], y[shell], z[shell]], axis=1))
    noise = pack(rng.integers([0, 0, 1], [400, 300, 60], size=(20000, 3)))
    octree.write_bt(os.path.join(out, "big_octomap.bt"), np.union1d(keys, noise), RES)
    points = rng.uniform([0, 0, 0], [60, 40, 3], size=(3_000_000, 3))
    points[:, 2] = np.where(rng.random(len(points)) < 0.7, rng.normal(0, 0.01, len(points)), points[:, 2])
    formats.save_cloud(os.path.join(out, "big_cloud.pcd"), points,
                       cloud_table(points, [("intensity", rng.uniform(0, 100, len(points)).astype(np.float32))]))
    make_warehouse(out, scale=4)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    voxels, free, coloured = make_office(OUT)
    lidar_points = make_lidar(OUT)
    shape = make_warehouse(OUT)
    make_lab(OUT)
    make_broken(OUT)
    drive_points = make_drive(OUT)
    print(f"drive: {drive_points} points in 16 frames")
    print(f"office: {voxels} occupied, {free} free voxels, {coloured} coloured voxels; lidar {lidar_points} points; "
          f"warehouse {shape[1]}x{shape[0]} cells")
    if "--large" in sys.argv:
        make_large(os.path.join(OUT, "large"))
    for name in sorted(os.listdir(OUT)):
        path = os.path.join(OUT, name)
        if os.path.isfile(path):
            print(f"{name:42} {os.path.getsize(path):>10,} bytes")
