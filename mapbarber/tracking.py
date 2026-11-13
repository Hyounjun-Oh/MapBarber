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


def padded(box, least):
    """The box with every side at least `least` long, so a single flat face still has a volume to overlap."""
    return dict(box, size=[max(float(v), least) for v in box["size"]])


def extent(box, points):
    """The box with the heading of `box` that just holds `points`: what of the object is really there."""
    c, s = np.cos(box["yaw"]), np.sin(box["yaw"])
    offset = np.asarray(points, np.float64) - np.asarray(box["center"])
    local = np.column_stack([c * offset[:, 0] + s * offset[:, 1], -s * offset[:, 0] + c * offset[:, 1], offset[:, 2]])
    low, high = local.min(axis=0), local.max(axis=0)
    middle = (low + high) / 2
    centre = np.asarray(box["center"]) + [c * middle[0] - s * middle[1], s * middle[0] + c * middle[1], middle[2]]
    return dict(box, center=[float(v) for v in centre], size=[float(max(v, 1e-3)) for v in high - low])


def align(source, target, reach, rounds=60, turn_limit=None):
    """Fit `source` points onto `target` points the way an upright object moves: a turn about z and a shift.

    Each round pairs every source point with its nearest target point within `reach`, keeps the pairs that
    choose each other (a part of the object that the target does not show yet would otherwise all cling to
    the nearest edge and drag the fit), and solves for the turn and shift that bring the pairs together.
    `turn_limit` (radians) caps the total turn: between two frames an object cannot spin far.
    Returns (4x4 transform, fitness, rms): fitness is the share of source points that end with a partner
    within `reach`, rms their mean distance.
    """
    from scipy.spatial import cKDTree
    source, target = np.asarray(source, np.float64), np.asarray(target, np.float64)
    total = np.eye(4)
    if len(source) < 3 or len(target) < 3:
        return total, 0.0, np.inf
    tree = cKDTree(target)
    moved = source.copy()
    spun = 0.0
    for _ in range(rounds):
        distance, index = tree.query(moved, distance_upper_bound=reach)
        paired = np.flatnonzero(np.isfinite(distance))
        if len(paired) < 3:
            break
        back = cKDTree(moved[paired]).query(target[index[paired]])[1]
        mutual = paired[back == np.arange(len(paired))]
        if len(mutual) >= 3:
            paired = mutual
        a, b = moved[paired], target[index[paired]]
        centre_a, centre_b = a.mean(axis=0), b.mean(axis=0)
        da, db = a[:, :2] - centre_a[:2], b[:, :2] - centre_b[:2]
        turn = float(np.arctan2((da[:, 0] * db[:, 1] - da[:, 1] * db[:, 0]).sum(), (da * db).sum()))
        if turn_limit is not None:
            turn = float(np.clip(spun + turn, -turn_limit, turn_limit) - spun)
        spun += turn
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


LOST = 0.25
TURN_LIMIT = np.radians(12.0)


def pose_of(box):
    """4x4 transform from a box's own frame (origin at its centre, x along its heading) to the world."""
    c, s = np.cos(box["yaw"]), np.sin(box["yaw"])
    pose = np.eye(4)
    pose[:2, :2] = [[c, -s], [s, c]]
    pose[:3, 3] = box["center"]
    return pose


def to_local(pose, points):
    return (np.asarray(points, np.float64) - pose[:3, 3]) @ pose[:3, :3]


def thin(points, cell):
    """One point per cubic cell, so a model gathered over many frames stays small."""
    if not len(points):
        return points
    _, first = np.unique(np.floor(points / cell).astype(np.int64), axis=0, return_index=True)
    return points[np.sort(first)]


class Track:
    """One object followed through frames.

    Its points are gathered in the object's own frame as the view of it changes, so the model (and with it
    the box) grows to the whole object even when no single frame shows all of it. For every frame the track
    keeps where the object was (`poses`) and what was found there (`results`).
    An object that changes shape (rigid=False, a walking person) is not gathered: its model is always the
    previous frame, and its box is fitted again in every frame.
    """

    def __init__(self, box, points, rigid=True, cell=0.05, margin=None):
        """`margin`: points further than this outside the box are strays and stay out of the model."""
        self.cls, self.instance, self.rigid, self.cell = int(box.get("class", 0)), int(box.get("instance", 0)), rigid, cell
        pose = pose_of(box)
        local = to_local(pose, points)
        half = np.asarray(box["size"], np.float64) / 2.0
        if margin is not None:
            near = np.all(np.abs(local) <= half + margin, axis=1)
            if near.sum() >= 3:
                local = local[near]
        self.low, self.high = np.minimum(-half, local.min(axis=0)), np.maximum(half, local.max(axis=0))
        self.model = thin(local, cell)
        self.first = pose
        self.poses, self.results, self.extents = {}, {}, {}

    def box(self, pose, low=None, high=None):
        """The object's box at a pose, in world coordinates."""
        low, high = (self.low if low is None else low), (self.high if high is None else high)
        centre = pose[:3, :3] @ ((low + high) / 2.0) + pose[:3, 3]
        return {"class": self.cls, "instance": self.instance, "center": [float(v) for v in centre],
                "size": [float(max(v, 1e-3)) for v in high - low], "yaw": float(np.arctan2(pose[1, 0], pose[0, 0]))}

    def box_in(self, frame):
        """The final box of a frame: one size for a rigid object, the frame's own size for one that changes shape.

        The longer side becomes the length, and an object that travelled points the way it went.
        """
        low, high = (self.low, self.high) if self.rigid else self.extents[frame]
        box = self.box(self.poses[frame], low, high)
        if box["size"][1] > box["size"][0]:
            box["size"] = [box["size"][1], box["size"][0], box["size"][2]]
            box["yaw"] += np.pi / 2.0
        ordered = sorted(self.poses)
        travel = self.poses[ordered[-1]][:3, 3] - self.poses[ordered[0]][:3, 3]
        if np.linalg.norm(travel[:2]) > 1.0 and np.cos(box["yaw"]) * travel[0] + np.sin(box["yaw"]) * travel[1] < 0:
            box["yaw"] += np.pi
        box["yaw"] = float((box["yaw"] + np.pi) % (2 * np.pi) - np.pi)
        return box

    def follow(self, guess, scene, reach=1.5, gap=0.5, least=5, weight=0.5, learn=True, blind=True):
        """Find the object in a frame, starting from where it is expected (`guess`, a 4x4 pose).

        Step 1, overlap: scene points near the expected box are grouped, and the group whose own box overlaps
        the expected box most (IoU, after closing up to `reach` of the distance between them) is the candidate.
        Step 2, alignment: the candidate's points are fitted onto the model (ICP); the pose follows.
        The object takes the candidate's points that lie within `gap` of what the model already covers, so it
        can grow where a new side comes into view. A candidate that reaches far beyond the object has merged
        with something else; then only the points inside the box are taken and the rest is counted as `left`.

        `blind` says that nothing is known about the object's motion yet (the first step of a track): only
        then may the fit start from the candidate's own position instead of the expected one.

        Returns None when nothing overlaps, else a dict: pose, members (indices into scene), iou (of the box
        where it was expected with the box where alignment put it), fitness (share of the candidate's points
        the model explains), score (weight * iou + (1 - weight) * fitness), left (points of the same group that
        were not taken) and merged (the group reaches far beyond the object).
        """
        scene = np.asarray(scene, np.float64)
        expected = self.box(guess)
        search = dict(expected, size=[expected["size"][0] + 2 * (reach + gap), expected["size"][1] + 2 * (reach + gap),
                                      expected["size"][2] + reach + gap])
        near = np.flatnonzero(box_labels.inside(search, scene))
        if len(near) < least:
            return None
        group = components(scene[near], gap)
        best, best_overlap = None, 0.0
        for number in np.flatnonzero(np.bincount(group) >= least):
            members = near[group == number]
            candidate = extent(expected, scene[members])
            # The object may have moved up to `reach`: compare the boxes with that much of the gap closed, and
            # prefer the nearer of two equally good candidates.
            apart = np.asarray(candidate["center"]) - np.asarray(expected["center"])
            distance = float(np.linalg.norm(apart))
            closer = dict(expected, center=[float(v) for v in np.asarray(expected["center"])
                                            + apart * min(1.0, reach / max(distance, 1e-9))])
            overlap = iou(padded(closer, gap), padded(candidate, gap)) * (1.0 - 0.2 * min(distance / reach, 1.0))
            if overlap > best_overlap:
                best, best_overlap = members, overlap
        if best is None:
            return None

        # Fit the candidate onto the model, starting from where the object is expected. Without any knowledge of
        # its motion a second start from the candidate's own position is tried, for an object that jumped far;
        # later that start would mislead, because a newly visible side shifts the candidate's centre.
        seen = to_local(guess, scene[best])
        jump = np.zeros(3)
        jump[:2] = ((self.low + self.high) / 2.0 - (seen.min(axis=0) + seen.max(axis=0)) / 2.0)[:2]
        fits = []
        for start in ((np.zeros(3), jump) if blind else (np.zeros(3),)):
            coarse, _, _ = align(seen + start, self.model, reach=max(2 * gap, 1.0), turn_limit=TURN_LIMIT)
            fine, fitness, rms = align((seen + start) @ coarse[:3, :3].T + coarse[:3, 3], self.model,
                                       reach=max(gap / 2.0, 0.2), turn_limit=TURN_LIMIT / 3.0)
            move = fine @ coarse
            move[:3, 3] += move[:3, :3] @ start
            fits.append((fitness, -rms, move))
        fitness, _, move = max(fits, key=lambda item: (round(item[0], 2), item[1]))
        move = self._settle(seen, move)
        pose = guess @ np.linalg.inv(move)

        local = to_local(pose, scene[near])
        tight = np.all((local >= self.low - 0.2) & (local <= self.high + 0.2), axis=1)
        allowed = np.all((local >= self.low - gap) & (local <= self.high + gap), axis=1)
        in_group = np.isin(near, best)
        spill = to_local(pose, scene[best])
        merged = bool(((spill.min(axis=0) < self.low - 3 * gap) | (spill.max(axis=0) > self.high + 3 * gap)).any())
        # A group that reaches far past the object has run into something else (a wall, a hedge, another
        # car): then only what lies in the box is taken, or the object would creep along its neighbour.
        taken = tight if merged else tight | (in_group & allowed)
        members = near[taken]
        if len(members) < least:
            return None
        overlap = iou(padded(expected, gap), padded(self.box(pose), gap))
        result = {"pose": pose, "members": members, "iou": float(overlap), "fitness": float(fitness),
                  "score": float(weight * overlap + (1.0 - weight) * fitness),
                  "left": int((in_group & ~taken).sum()), "merged": merged}
        if learn:
            mine = local[taken]
            # Only the body of what was taken shapes the model: a stray point at the edge would otherwise widen
            # the box a little in every frame.
            mine = mine[box_labels.body(mine, gap)]
            if self.rigid:
                self.model = thin(np.vstack([self.model, mine]), self.cell)
                self.low, self.high = np.minimum(self.low, mine.min(axis=0)), np.maximum(self.high, mine.max(axis=0))
            else:
                self.model = thin(mine, self.cell)
                self.low, self.high = mine.min(axis=0), mine.max(axis=0)
        return result

    def _settle(self, seen, move, tolerance=0.05):
        """Undo a slide along a flat side that point pairs cannot feel.

        Points on a flat face find partners wherever the face overlaps the model, so the fit has no say along
        the face. The ends tell: when what is seen sticks out past the model at one end and falls short by
        about as much at the other, it has slid, and is moved back by the smaller of the two. Sticking out at
        one end only is a side of the object coming into view, and is left alone.
        """
        placed = seen @ move[:3, :3].T + move[:3, 3]
        if len(placed) < 20 or len(self.model) < 20:
            return move
        settled = move.copy()
        for axis in (0, 1):
            low, high = np.percentile(placed[:, axis], [1, 99])
            model_low, model_high = np.percentile(self.model[:, axis], [1, 99])
            out, short = high - model_high, low - model_low
            if out > tolerance and short > tolerance:
                settled[axis, 3] -= min(out, short)
            elif out < -tolerance and short < -tolerance:
                settled[axis, 3] -= max(out, short)
        return settled

    def run(self, frames, start, scene_of, reach=1.5, gap=0.5, least=5, weight=0.5, lost=LOST):
        """Follow the object through `frames` (in order) from the frame `start`, forwards and then backwards.

        Going forwards the model gathers what each frame shows. Going backwards every frame, the first one
        included, is fitted again against the finished model, and frames before `start` are tried too.
        scene_of(frame) gives (ids, points) of the points that may belong to this object in that frame;
        afterwards `poses[frame]` and `results[frame]` (with `ids` of the members) hold what was found.
        """
        settings = {"reach": reach, "gap": gap, "least": least, "weight": weight}
        at = frames.index(start)
        self.poses, self.results, self.extents = {start: self.first}, {}, {}

        def step(frame, guess, learn=True, blind=False):
            ids, points = scene_of(frame)
            found = self.follow(guess, points, learn=learn, blind=blind, **settings) if len(ids) else None
            if found is None or found["score"] < lost:
                return False
            found["ids"] = ids[found["members"]]
            self.poses[frame], self.results[frame] = found["pose"], found
            self.extents[frame] = (self.low.copy(), self.high.copy())
            return True

        def ahead(pose, shift):
            guess = pose.copy()
            guess[:3, 3] += shift
            return guess

        pose, shift, last = self.first, np.zeros(3), at
        for index in range(at + 1, len(frames)):
            if not step(frames[index], ahead(pose, shift), blind=index == at + 1):
                break
            shift, pose, last = self.poses[frames[index]][:3, 3] - pose[:3, 3], self.poses[frames[index]], index
        pose, shift = self.poses[frames[last]], np.zeros(3)
        for index in range(last, -1, -1):
            frame = frames[index]
            known = frame in self.poses
            guess = self.poses[frame] if known else ahead(pose, shift)
            before = pose
            if not step(frame, guess, learn=not known or not self.rigid):
                if known and frame != start:
                    self.poses.pop(frame, None)
                    self.results.pop(frame, None)
                if not known:
                    break
                continue
            pose = self.poses[frame]
            if index < last:
                shift = pose[:3, 3] - before[:3, 3]
        return self
