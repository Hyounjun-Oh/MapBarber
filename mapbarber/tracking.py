"""Following boxed objects from one LiDAR frame to the next: box overlap first, then point alignment, as one score."""
import numpy as np

from . import boxes as box_labels
from .labels import components


def footprint(box):
    """The four ground-plane corners of a box, counter-clockwise."""
    return box_labels.corners(box)[:4, :2]


def _clip(polygon, a, b):
    """The part of a convex polygon on the left of the line a -> b."""
    out = []
    edge = b - a
    for index in range(len(polygon)):
        p, q = polygon[index], polygon[(index + 1) % len(polygon)]
        side_p = edge[0] * (p[1] - a[1]) - edge[1] * (p[0] - a[0])
        side_q = edge[0] * (q[1] - a[1]) - edge[1] * (q[0] - a[0])
        if side_p >= 0:
            out.append(p)
        if side_p * side_q < 0:
            out.append(p + (q - p) * (side_p / (side_p - side_q)))
    return out


def _area(polygon):
    if len(polygon) < 3:
        return 0.0
    points = np.asarray(polygon)
    x, y = points[:, 0], points[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def iou(one, other):
    """Overlap of two upright boxes: shared volume over joint volume (0..1)."""
    shared = list(footprint(one))
    corners = footprint(other)
    for index in range(4):
        shared = _clip(shared, corners[index], corners[(index + 1) % 4])
        if not shared:
            return 0.0
    low = max(one["center"][2] - one["size"][2] / 2, other["center"][2] - other["size"][2] / 2)
    high = min(one["center"][2] + one["size"][2] / 2, other["center"][2] + other["size"][2] / 2)
    common = _area(shared) * max(high - low, 0.0)
    total = float(np.prod(one["size"]) + np.prod(other["size"])) - common
    return common / total if total > 0 else 0.0


def extent(box, points):
    """The box with the heading of `box` that just holds `points`: what of the object is really there."""
    c, s = np.cos(box["yaw"]), np.sin(box["yaw"])
    offset = np.asarray(points, np.float64) - np.asarray(box["center"])
    local = np.column_stack([c * offset[:, 0] + s * offset[:, 1], -s * offset[:, 0] + c * offset[:, 1], offset[:, 2]])
    low, high = local.min(axis=0), local.max(axis=0)
    middle = (low + high) / 2
    centre = np.asarray(box["center"]) + [c * middle[0] - s * middle[1], s * middle[0] + c * middle[1], middle[2]]
    return dict(box, center=[float(v) for v in centre], size=[float(max(v, 1e-3)) for v in high - low])


def align(source, target, reach, rounds=25):
    """Fit `source` points onto `target` points the way an upright object moves: a turn about z and a shift.

    Each round pairs every source point with its nearest target point within `reach` and solves for the turn
    and shift that bring the pairs together. Returns (4x4 transform, fitness, rms): fitness is the share of
    source points that end with a partner within `reach`, rms their mean distance.
    """
    from scipy.spatial import cKDTree
    source, target = np.asarray(source, np.float64), np.asarray(target, np.float64)
    total = np.eye(4)
    if len(source) < 3 or len(target) < 3:
        return total, 0.0, np.inf
    tree = cKDTree(target)
    moved = source.copy()
    for _ in range(rounds):
        distance, index = tree.query(moved, distance_upper_bound=reach)
        paired = np.isfinite(distance)
        if paired.sum() < 3:
            break
        a, b = moved[paired], target[index[paired]]
        centre_a, centre_b = a.mean(axis=0), b.mean(axis=0)
        da, db = a[:, :2] - centre_a[:2], b[:, :2] - centre_b[:2]
        turn = float(np.arctan2((da[:, 0] * db[:, 1] - da[:, 1] * db[:, 0]).sum(), (da * db).sum()))
        c, s = np.cos(turn), np.sin(turn)
        step = np.eye(4)
        step[:2, :2] = [[c, -s], [s, c]]
        step[:3, 3] = centre_b - step[:3, :3] @ centre_a
        moved = moved @ step[:3, :3].T + step[:3, 3]
        total = step @ total
        if abs(turn) < 1e-4 and np.linalg.norm(step[:3, 3] - (centre_a - step[:3, :3] @ centre_a)) < 1e-4:
            break
    distance, _ = tree.query(moved, distance_upper_bound=reach)
    paired = np.isfinite(distance)
    fitness = float(paired.mean())
    rms = float(np.sqrt(np.mean(distance[paired] ** 2))) if paired.any() else np.inf
    return total, fitness, rms


def follow(box, points, scene, reach=1.5, gap=0.5, least=5, weight=0.5, shift=None):
    """Carry one boxed object into the next frame.

    box, points: the object's box and points in the earlier frame, in world coordinates.
    scene: the later frame's points that may belong to an object (ground removed), in world coordinates.
    shift: how far the object moved between the two frames before (its speed), used to look in the right place.

    Step 1, overlap: scene points near where the object should be are grouped into candidates; each
    candidate's own box is compared with the object's box by IoU, and the best one is taken.
    Step 2, alignment: the object's points are fitted onto the candidate; the box moves with them and keeps
    its size, so a partly hidden object does not shrink.

    Returns None when nothing overlaps, else a dict: box (moved), members (indices into scene: the points in
    the moved box), iou (of the moved box with the space those points really fill, so a half-hidden object
    scores lower), fitness (share of the object's points that found a partner), score
    (weight * iou + (1 - weight) * fitness) and shift (the motion found).
    """
    scene = np.asarray(scene, np.float64)
    expected = dict(box)
    if shift is not None:
        expected["center"] = [float(v) for v in np.asarray(box["center"]) + shift]
    search = dict(expected, size=[expected["size"][0] + 2 * reach, expected["size"][1] + 2 * reach,
                                  expected["size"][2] + reach])
    near = np.flatnonzero(box_labels.inside(search, scene))
    if len(near) < least:
        return None
    group = components(scene[near], gap)
    best, best_overlap = None, 0.0
    for number in np.flatnonzero(np.bincount(group) >= least):
        members = near[group == number]
        overlap = iou(expected, box_labels.fit(scene[members]))
        if overlap > best_overlap:
            best, best_overlap = members, overlap
    if best is None:
        return None
    # Start from where the candidate's own box sits, then fit coarsely and finely: a plain fit from the old
    # place would pair the wrong sides of an object that moved further than the points are apart.
    jump = np.asarray(box_labels.fit(scene[best])["center"]) - np.asarray(expected["center"])
    start = np.asarray(points, np.float64) + (0.0 if shift is None else shift) + jump
    coarse, _, _ = align(start, scene[best], reach=max(2 * gap, 1.0))
    fine, fitness, _ = align(start @ coarse[:3, :3].T + coarse[:3, 3], scene[best], reach=max(gap / 2, 0.2))
    transform = fine @ coarse
    transform[:3, 3] += transform[:3, :3] @ jump
    moved = box_labels.moved(expected, transform)
    inside = near[box_labels.inside(dict(moved, size=[v + 0.2 for v in moved["size"]]), scene[near])]
    members = inside if fitness >= 0.3 and len(inside) >= least else best
    overlap = iou(moved, extent(moved, scene[members]))
    motion = np.asarray(moved["center"]) - np.asarray(box["center"])
    return {"box": moved, "members": members, "iou": float(overlap), "fitness": float(fitness),
            "score": float(weight * overlap + (1.0 - weight) * fitness), "shift": motion}
