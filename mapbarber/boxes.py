"""Upright 3D box labels: fitting them to points, their corners, and their files."""
import json

import numpy as np

from .labels import components, oriented_box
from .safeio import replacing

EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))


TAIL_SHARE = 0.02
GROUP_SHARE = 0.02
OUTSIDE_SHARE = 0.05
FEW = 3
TAIL_LEAST = 20


def heading(flat):
    """Yaw (radians, 0..pi/2) of the upright rectangle that the ground-plane points sit against best.

    Angles are tried in two passes, coarse and then fine: the rectangle holding the middle 98 % of the points
    is drawn at each angle, and the angle where the points lie closest to its sides wins. Unlike the main
    axis of the points, this stays with the object's faces when two of them are seen at once, and a few far
    points do not turn it.
    """
    flat = np.asarray(flat, np.float64)
    if len(flat) < 3:
        return 0.0
    flat = flat[:: max(1, len(flat) // 1500)]

    def best(degrees):
        angles = np.radians(degrees)
        c, s = np.cos(angles)[:, None], np.sin(angles)[:, None]
        away = None
        for values in (c * flat[:, 0] + s * flat[:, 1], -s * flat[:, 0] + c * flat[:, 1]):
            low, high = np.percentile(values, [1, 99], axis=1)
            side = np.minimum(np.abs(values - low[:, None]), np.abs(high[:, None] - values))
            away = side if away is None else np.minimum(away, side)
        return float(degrees[int(np.argmin(away.mean(axis=1)))])

    coarse = best(np.arange(0.0, 90.0, 3.0))
    return float(np.radians(best(coarse + np.arange(-2.5, 2.6, 0.5)) % 90.0))


def _spacing(points):
    """Typical distance from a point to its nearest neighbour (sampled)."""
    from scipy.spatial import cKDTree
    sample = points[:: max(1, len(points) // 2000)]
    return float(np.median(cKDTree(points).query(sample, k=2)[0][:, 1]))


def body(points, gap):
    """Mask of the points that make up an object's body, leaving out the few that would spoil its box.

    Two kinds of points are left out, both judged against how far apart the object's own points lie, so a
    thinly scanned object is not taken apart:
    - small groups standing apart from the main body: further than `gap` (or three times the usual point
      spacing), each of at most 2 % of the points (or three), together 5 % at most, smallest first;
    - seen along each side of the box, a thin tail: at most 2 % of the points (or three) lying beyond an
      empty stretch of half a `gap` that is also three times wider than any inside the body. Objects of
      fewer than 20 points are too thin to judge this way.
    Both together never take more than those 5 %; an object with more loose points than that is ragged, or
    has parts the scan saw only thinly, and is left whole. These are typically slips of the brush or points of a neighbour.
    """
    points = np.asarray(points, np.float64)
    keep = np.ones(len(points), bool)
    if len(points) < 8:
        return keep
    group = components(points, max(gap, 3.0 * _spacing(points)))
    sizes = np.bincount(group)
    budget = max(OUTSIDE_SHARE * len(points), FEW)
    for number in np.argsort(sizes, kind="stable"):
        if sizes[number] > max(GROUP_SHARE * len(points), FEW) or sizes[number] > budget or sizes[number] == sizes.max():
            break
        budget -= sizes[number]
        keep[group == number] = False
    for _ in range(2):
        yaw = heading(points[keep, :2])
        c, s = np.cos(yaw), np.sin(yaw)
        local = np.column_stack([c * points[:, 0] + s * points[:, 1], -s * points[:, 0] + c * points[:, 1], points[:, 2]])
        members = np.flatnonzero(keep)
        allowed = max(FEW, int(TAIL_SHARE * len(members)))
        if len(members) < TAIL_LEAST:
            break
        cut = np.zeros(len(points), bool)
        for axis in range(3):
            order = members[np.argsort(local[members, axis])]
            jumps = np.diff(local[order, axis])
            limit = max(gap / 2.0, 3.0 * jumps[allowed:len(jumps) - allowed].max())
            low = np.flatnonzero(jumps[:allowed] > limit)
            high = np.flatnonzero(jumps[len(jumps) - allowed:] > limit)
            if len(low):
                cut[order[:low[-1] + 1]] = True
            if len(high):
                cut[order[len(order) - allowed + high[0]:]] = True
        # More than a few such points means the object is simply ragged: then nothing is a tail.
        if not cut.any() or (cut & keep).sum() > budget:
            break
        budget -= (cut & keep).sum()
        keep &= ~cut
    return keep


def fit(points, cls=0, instance=0, gap=None):
    """A box around points: centre, size (length along its heading, width, height) and yaw in radians.

    With `gap` the box is fitted to the body of the points only (see body()) and turned to the rectangle the
    body sits against best. Points that end up more than half a `gap` outside it are counted as `stray`.
    """
    points = np.asarray(points, np.float64)
    if gap is not None and len(points) >= 8:
        used = body(points, gap)
        inner = points[used]
        yaw = heading(inner[:, :2])
        c, s = np.cos(yaw), np.sin(yaw)
        turned = np.column_stack([c * inner[:, 0] + s * inner[:, 1], -s * inner[:, 0] + c * inner[:, 1], inner[:, 2]])
        low, high = turned.min(axis=0), turned.max(axis=0)
        middle = (low + high) / 2.0
        centre = np.array([c * middle[0] - s * middle[1], s * middle[0] + c * middle[1], middle[2]])
        box = _upright(centre, high - low, yaw, cls, instance, len(points))
        stray = int((~inside(dict(box, size=[v + gap for v in box["size"]]), points)).sum())
        box["points"] = len(points) - stray
        if stray:
            box["stray"] = stray
        return box
    centre, size, yaw = oriented_box(points)
    return _upright(centre, size, yaw, cls, instance, len(points))


def _upright(centre, size, yaw, cls, instance, count):
    if size[1] > size[0]:
        size = np.array([size[1], size[0], size[2]])
        yaw += np.pi / 2
    yaw = float((yaw + np.pi) % (2 * np.pi) - np.pi)
    return {"class": int(cls), "instance": int(instance), "center": [float(v) for v in centre],
            "size": [float(max(v, 1e-3)) for v in size], "yaw": yaw, "points": int(count)}


def corners(box):
    """The eight corners of a box (bottom four, then top four)."""
    length, width, height = box["size"]
    c, s = np.cos(box["yaw"]), np.sin(box["yaw"])
    local = np.array([[sx * length / 2, sy * width / 2, sz * height / 2]
                      for sz in (-1, 1) for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))])
    turned = np.column_stack([c * local[:, 0] - s * local[:, 1], s * local[:, 0] + c * local[:, 1], local[:, 2]])
    return turned + np.asarray(box["center"])


def inside(box, points):
    """Mask of points within a box."""
    offset = np.asarray(points, np.float64) - np.asarray(box["center"])
    c, s = np.cos(box["yaw"]), np.sin(box["yaw"])
    along = c * offset[:, 0] + s * offset[:, 1]
    across = -s * offset[:, 0] + c * offset[:, 1]
    half = np.asarray(box["size"]) / 2 + 1e-9
    return (np.abs(along) <= half[0]) & (np.abs(across) <= half[1]) & (np.abs(offset[:, 2]) <= half[2])


def moved(box, pose):
    """The box carried by a 4x4 pose (only the heading of the pose turns an upright box)."""
    out = dict(box)
    out["center"] = [float(v) for v in pose[:3, :3] @ np.asarray(box["center"]) + pose[:3, 3]]
    heading = pose[:3, :3] @ np.array([np.cos(box["yaw"]), np.sin(box["yaw"]), 0.0])
    out["yaw"] = float(np.arctan2(heading[1], heading[0]))
    return out


def save(path, boxes, classes, frame=None):
    rows = [dict(box, name=classes.name(box["class"])) for box in boxes]
    document = {"frame": frame, "boxes": rows} if frame is not None else {"boxes": rows}
    with replacing(path) as part, open(part, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=1, ensure_ascii=False)


def load(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f).get("boxes", [])
    keys = ("class", "instance", "center", "size", "yaw", "points", "score", "left", "key", "accepted")
    return [{key: row[key] for key in keys if key in row} for row in rows
            if all(key in row for key in ("center", "size", "yaw"))]
