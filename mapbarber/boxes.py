"""Upright 3D box labels: fitting them to points, their corners, and their files."""
import json

import numpy as np

from .labels import oriented_box
from .safeio import replacing

EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))


def fit(points, cls=0, instance=0):
    """A box around points: centre, size (length along its heading, width, height) and yaw in radians."""
    centre, size, yaw = oriented_box(points)
    if size[1] > size[0]:
        size = np.array([size[1], size[0], size[2]])
        yaw += np.pi / 2
    yaw = float((yaw + np.pi) % (2 * np.pi) - np.pi)
    return {"class": int(cls), "instance": int(instance), "center": [float(v) for v in centre],
            "size": [float(max(v, 1e-3)) for v in size], "yaw": yaw, "points": int(len(points))}


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
    keys = ("class", "instance", "center", "size", "yaw", "points", "score", "left")
    return [{key: row[key] for key in keys if key in row} for row in rows
            if all(key in row for key in ("center", "size", "yaw"))]
