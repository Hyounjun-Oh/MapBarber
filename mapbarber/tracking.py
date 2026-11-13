"""Following boxed objects from one LiDAR frame to the next: box overlap first, then point alignment, as one score."""
from collections import deque

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


MUTUAL = True


def register(source, target, normals, reach, rounds=40, turn_limit=None, stiffness=0.02):
    """Fit `source` points onto the surface of `target` points the way an upright object moves: a turn about z
    and a shift, both measured from where the source starts.

    Each round pairs every source point with its nearest target point within `reach` (keeping the pairs that
    choose each other) and solves for the small turn and shift that bring each source point onto the surface
    of its partner, the plane through it with its normal (`normals`). Pairs far off that surface count less.
    A movement the surfaces cannot tell (sliding along a flat wall, turning a pole about its own axis) gets no
    push from the pairs; a weak pull back to the start (`stiffness`, against the pairs' total weight) keeps it
    where it started instead of letting it drift. `turn_limit` (radians) caps the total turn.
    Returns (4x4 transform, fitness, rms) like align().
    """
    from scipy.spatial import cKDTree
    source, target = np.asarray(source, np.float64), np.asarray(target, np.float64)
    if len(source) < 3 or len(target) < 3:
        return np.eye(4), 0.0, np.inf
    tree = cKDTree(target)
    centre = source.mean(axis=0)
    offset = source - centre
    shift, turn = np.zeros(3), 0.0

    def placed(turn, shift):
        c, s = np.cos(turn), np.sin(turn)
        rotated = np.column_stack([c * offset[:, 0] - s * offset[:, 1], s * offset[:, 0] + c * offset[:, 1], offset[:, 2]])
        return rotated, rotated + centre + shift

    for round_index in range(rounds):
        rotated, moved = placed(turn, shift)
        distance, index = tree.query(moved, distance_upper_bound=reach)
        paired = np.flatnonzero(np.isfinite(distance))
        if len(paired) < 3:
            break
        if MUTUAL:
            back = cKDTree(moved[paired]).query(target[index[paired]])[1]
            mutual = paired[back == np.arange(len(paired))]
            if len(mutual) >= 3:
                paired = mutual
        partner, normal = target[index[paired]], normals[index[paired]]
        residual = np.einsum("ij,ij->i", normal, moved[paired] - partner)
        lever = normal[:, 1] * rotated[paired, 0] - normal[:, 0] * rotated[paired, 1]
        jacobian = np.column_stack([normal, lever])
        # Pairs far off the surface count less, by a measure that starts wide (the fit may still be far off)
        # and narrows as it settles. It is not taken from the pairs themselves: along a direction the surfaces
        # cannot tell, most pairs are already at rest, and would make the few that still pull look like outliers.
        width = max(0.5 * reach * 0.75 ** round_index, 0.03)
        weight = 1.0 / (1.0 + (residual / width) ** 2)
        hessian = (jacobian * weight[:, None]).T @ jacobian
        gradient = (jacobian * weight[:, None]).T @ residual
        pull = stiffness * weight.sum() * np.eye(4)
        state = np.append(shift, turn)
        step = np.linalg.solve(hessian + pull, -(gradient + pull @ state))
        shift = shift + step[:3]
        turn = turn + step[3]
        if turn_limit is not None:
            turn = float(np.clip(turn, -turn_limit, turn_limit))
        if np.linalg.norm(step[:3]) < 1e-4 and abs(step[3]) < 1e-5 and width <= 0.03:
            break
    c, s = np.cos(turn), np.sin(turn)
    total = np.eye(4)
    total[:2, :2] = [[c, -s], [s, c]]
    total[:3, 3] = centre + shift - total[:3, :3] @ centre
    _, moved = placed(turn, shift)
    distance, _ = tree.query(moved, distance_upper_bound=reach)
    paired = np.isfinite(distance)
    fitness = float(paired.mean())
    rms = float(np.sqrt(np.mean(distance[paired] ** 2))) if paired.any() else np.inf
    return total, fitness, rms


LOST = 0.25
TURN_LIMIT = np.radians(12.0)
WINDOW = 2


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
    """One point per cubic cell."""
    if not len(points):
        return points
    _, first = np.unique(np.floor(points / cell).astype(np.int64), axis=0, return_index=True)
    return points[np.sort(first)]


class Track:
    """One object followed through frames, judged only by the frames just before.

    In each frame the object is found by box overlap and fitted onto the points it had in the previous one or
    two frames, and its box is fitted to what this frame and those two show of it. Nothing older is used, so a
    point taken by mistake leaves the box again within two frames, and no frame is shaped by the whole history
    of the track. An object that changes shape (rigid=False, a walking person) is fitted onto the previous frame
    only and gets a box from its own frame.

    The frame the track starts from is the reference: points that stood beside the object there without
    belonging to it (`aside`, world coordinates: labelled as something else, or left out) are not taken later.
    `margin`: points of the start frame further than this outside the box are strays and are not used.
    `fixed`: the box already has the right size (corrected by hand) and keeps it in every frame.
    For every frame the track keeps where the object was (`poses`), what was found there (`results`) and the
    extent of its box (`extents`).
    """

    def __init__(self, box, points, rigid=True, cell=0.05, margin=None, fixed=False, gap=0.2, aside=None):
        self.cls, self.instance, self.rigid, self.cell = int(box.get("class", 0)), int(box.get("instance", 0)), rigid, cell
        self.fixed, self.gap = fixed and rigid, gap
        self.window = WINDOW if rigid else 1
        pose = pose_of(box)
        local = to_local(pose, points)
        self.half = np.asarray(box["size"], np.float64) / 2.0
        if margin is not None:
            near = np.all(np.abs(local) <= self.half + margin, axis=1)
            if near.sum() >= 3:
                local = local[near]
        self.start = local
        size = np.ptp(local, axis=0) if len(local) >= 3 else 2.0 * self.half
        self.reach_of_body = np.array([0.5 * size[:2].max() + 0.15, 0.5 * size[:2].max() + 0.15, 0.5 * size[2] + 0.15])
        self.first = pose
        self.aside = self.beside = None
        if aside is not None and len(aside):
            from scipy.spatial import cKDTree
            aside = np.asarray(aside, np.float64)
            self.aside = cKDTree(aside)
            # The same points in the object's own frame: what stood right beside it and may travel with it
            # (another person walking alongside, a trailer).
            relative = to_local(pose, aside)
            close_by = np.all(np.abs(relative) <= self.half + 1.0, axis=1)
            if close_by.any():
                self.beside = cKDTree(relative[close_by])
        self.before = self.aside
        self.recent = deque([local], maxlen=self.window + 1)
        self.low, self.high = self._extent()
        self.last = None
        self.poses, self.results, self.extents = {}, {}, {}

    def _extent(self):
        """The box extent from the frames kept: this frame and up to two before (only this one when the shape changes)."""
        if self.fixed:
            return -self.half, self.half
        points = np.vstack(list(self.recent)) if self.rigid else self.recent[-1]
        if len(points) >= 8:
            points = points[box_labels.body(points, self.gap)]
        if len(points) < 3:
            return -self.half, self.half
        return points.min(axis=0), points.max(axis=0)

    def _model(self):
        """What the next frame is fitted onto: the object's points of the last frame or two, with their surface normals."""
        from scipy.spatial import cKDTree
        from .labels import normals
        model = list(self.recent)[-self.window:]
        model = thin(np.vstack(model), self.cell)
        surface = normals(model, 12)[0] if len(model) >= 3 else np.tile([0.0, 0.0, 1.0], (len(model), 1))
        return model, cKDTree(model), surface

    def explains(self, local, model):
        """Mask of points (in the object's frame) that lie on the model's surface.

        A point counts when a model point is near (within twice the object gap, half a metre at least) and the
        point lies close to the surface through it (a third of the gap, 10 cm at least): on a sparsely scanned
        side the points of a new frame fall between the earlier scan lines, not onto them.
        """
        points, tree, surface = model
        distance, index = tree.query(local, distance_upper_bound=max(2.0 * self.gap, 0.5))
        found = np.isfinite(distance)
        close = np.zeros(len(local), bool)
        off = np.abs(np.einsum("ij,ij->i", surface[index[found]], local[found] - points[index[found]]))
        close[found] = off <= max(self.gap / 3.0, 0.1)
        return close

    def box(self, pose, low=None, high=None):
        """The object's box at a pose, in world coordinates."""
        low, high = (self.low if low is None else low), (self.high if high is None else high)
        centre = pose[:3, :3] @ ((low + high) / 2.0) + pose[:3, 3]
        return {"class": self.cls, "instance": self.instance, "center": [float(v) for v in centre],
                "size": [float(max(v, 1e-3)) for v in high - low], "yaw": float(np.arctan2(pose[1, 0], pose[0, 0]))}

    def box_in(self, frame):
        """The box of a frame, from that frame and the one or two before it.

        The heading is decided once for the whole track, so the box does not turn from frame to frame even where
        a partial view is wider than long: an object that travelled points the way it went, one that stayed keeps
        the heading of its start box.
        """
        low, high = self.extents[frame]
        box = self.box(self.poses[frame], low, high)
        if self.fixed:
            return box
        ordered = sorted(self.poses)
        travel = self.poses[ordered[-1]][:3, 3] - self.poses[ordered[0]][:3, 3]
        distance = float(np.linalg.norm(travel[:2]))
        if distance > 1.0:
            along = (np.cos(box["yaw"]) * travel[0] + np.sin(box["yaw"]) * travel[1]) / distance
            if abs(along) < np.cos(np.pi / 4):
                box["size"] = [box["size"][1], box["size"][0], box["size"][2]]
                box["yaw"] += np.pi / 2.0
            if np.cos(box["yaw"]) * travel[0] + np.sin(box["yaw"]) * travel[1] < 0:
                box["yaw"] += np.pi
        box["yaw"] = float((box["yaw"] + np.pi) % (2 * np.pi) - np.pi)
        return box

    def follow(self, guess, scene, reach=1.5, gap=0.5, least=5, weight=0.5, learn=True, blind=True, trust=0.0):
        """Find the object in a frame, starting from where it is expected (`guess`, a 4x4 pose).

        Step 1, overlap: scene points near the expected box are grouped, and the group whose own box overlaps
        the expected box most (IoU, after closing up to `reach` of the distance between them) is the candidate;
        other pieces lying mostly inside the expected box join it (a sparsely scanned or partly hidden object
        falls apart into pieces).
        Step 2, alignment: the candidate's points are fitted onto the object's points of the last frame or two;
        the pose follows.
        The object takes the points that lie on its surface, and, while its group stands on its own, the rest of
        the group within `gap` of its box, where a new side comes into view; never points that stood beside it
        in the start frame. A candidate that reaches far beyond the object has merged with something else; then
        only the points on the object's surface are taken and the rest is counted as `left`.

        `blind` says that nothing is known about the object's motion yet (the first step of a track): only
        then may the fit start from the candidate's own position instead of the expected one.

        The score decides how far the frame is believed. Below `trust` the object takes only the points the
        alignment explains, and the frame does not become one of those the next frame is judged by: a doubtful
        frame cannot pass its mistakes on. Only a believed frame may take new points beyond the surface, and a
        body that changes shape never beyond its labelled size.

        Returns None when nothing overlaps, else a dict: pose, members (indices into scene), iou (of the box
        where it was expected with the box where alignment put it), fitness (share of the candidate's points
        the model explains), score (weight * iou + (1 - weight) * fitness), left (points of the same group that
        were not taken) and merged (the group reaches far beyond the object). With `learn` the frame becomes
        one of the frames the next one is judged by.
        """
        scene = np.asarray(scene, np.float64)
        expected = self.box(guess)
        search = dict(expected, size=[expected["size"][0] + 2 * (reach + gap), expected["size"][1] + 2 * (reach + gap),
                                      expected["size"][2] + reach + gap])
        near = np.flatnonzero(box_labels.inside(search, scene))
        if len(near) < least:
            return None
        group = components(scene[near], gap)
        best, best_overlap, chosen = None, 0.0, -1
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
                best, best_overlap, chosen = members, overlap, number
        if best is None:
            return None
        inside = box_labels.inside(dict(expected, size=[v + 2 * gap for v in expected["size"]]), scene[near])
        share = np.bincount(group, weights=inside) / np.bincount(group)
        pieces = np.flatnonzero(share >= 0.5)
        best = near[np.isin(group, np.union1d(pieces, [chosen]))]

        # Fit the candidate onto the model, starting from where the object is expected. Without any knowledge of
        # its motion a second start from the candidate's own position is tried, for an object that jumped far;
        # later that start would mislead, because a newly visible side shifts the candidate's centre.
        model = self._model()
        seen = to_local(guess, scene[best])
        jump = np.zeros(3)
        jump[:2] = ((self.low + self.high) / 2.0 - (seen.min(axis=0) + seen.max(axis=0)) / 2.0)[:2]
        fits = []
        for start in ((np.zeros(3), jump) if blind else (np.zeros(3),)):
            coarse, _, _ = register(seen + start, model[0], model[2], reach=max(2 * gap, 1.0), turn_limit=TURN_LIMIT)
            fine, fitness, rms = register((seen + start) @ coarse[:3, :3].T + coarse[:3, 3], model[0], model[2],
                                          reach=max(gap / 2.0, 0.2), turn_limit=TURN_LIMIT / 3.0)
            move = fine @ coarse
            move[:3, 3] += move[:3, :3] @ start
            fits.append((fitness, -rms, move))
        fitness, _, move = max(fits, key=lambda item: (round(item[0], 2), item[1]))
        pose = guess @ np.linalg.inv(move)

        local = to_local(pose, scene[near])
        snug = max(gap / 2.0, 0.1)
        allowed = np.all((local >= self.low - snug) & (local <= self.high + snug), axis=1)
        close = self.explains(local, model)
        in_group = np.isin(near, best)
        spill = to_local(pose, scene[best])
        far = max(3 * gap, reach)
        merged = bool(((spill.min(axis=0) < self.low - far) | (spill.max(axis=0) > self.high + far)).any())
        # Without knowing how the object moves, where it was expected says little: then any movement up to
        # `reach` counts as expected.
        found_box = self.box(pose)
        if blind:
            apart = np.asarray(found_box["center"]) - np.asarray(expected["center"])
            step = min(1.0, reach / max(float(np.linalg.norm(apart)), 1e-9))
            expected = dict(expected, center=[float(v) for v in np.asarray(expected["center"]) + apart * step])
        overlap = iou(padded(expected, gap), padded(found_box, gap))
        score = float(weight * overlap + (1.0 - weight) * fitness)
        believed = score >= trust

        # The object takes what the alignment explains: points on its surface, within its box. Points that merely
        # lie inside the box are never taken, nor are points that are merely joined to it.
        taken = close & allowed
        if believed and not merged:
            # A believed frame may add the rest of the object's group next to the box, where a new side comes
            # into view: as far out as the gap between objects, or as far as it moved in this frame (its view
            # changes about as fast as it moves). A moving object only takes new points that moved with it: what
            # stood at the same place in the previous frame (a parked car it passes, a wall) stays. A group that
            # reaches far past the object (further than it can move in a frame) has run into something else, and
            # adds nothing.
            moved = float(np.linalg.norm((pose[:3, 3] - (self.last if self.last is not None else guess)[:3, 3])[:2]))
            grow = max(gap, moved)
            new = in_group & ~taken & np.all((local >= self.low - grow) & (local <= self.high + grow), axis=1)
            if new.any() and self.before is not None and moved > 2 * snug:
                new[new] = ~np.isfinite(self.before.query(scene[near[new]], distance_upper_bound=snug)[0])
            taken |= new
        if self.aside is not None:
            taken &= ~np.isfinite(self.aside.query(scene[near], distance_upper_bound=snug)[0])
        if self.beside is not None and taken.any():
            taken[taken] = ~np.isfinite(self.beside.query(local[taken], distance_upper_bound=snug)[0])
        if not self.rigid:
            # A body changes its pose but hardly its size: it never takes points further out than its labelled
            # size in the start frame (plus 15 cm on every side), around where it was in the frame before.
            centre = (self.low + self.high) / 2.0
            taken &= np.all(np.abs(local - centre) <= self.reach_of_body, axis=1)
        members = near[taken]
        if len(members) < least:
            return None
        result = {"pose": pose, "members": members, "iou": float(overlap), "fitness": float(fitness), "score": score,
                  "left": int((in_group & ~taken).sum()), "merged": merged, "believed": believed}
        if learn and believed:
            from scipy.spatial import cKDTree
            mine = local[taken]
            self.recent.append(mine[box_labels.body(mine, gap)] if len(mine) >= 8 else mine)
            self.low, self.high = self._extent()
            rest = scene[near[~taken & ~in_group]]
            self.before = cKDTree(rest) if len(rest) else None
        return result

    def run(self, frames, start, scene_of, reach=1.5, gap=0.5, least=5, weight=0.5, lost=LOST, trust=0.6,
            directions=(1, -1), on_frame=None):
        """Follow the object through `frames` (in order) from the frame `start`: forwards (direction 1), backwards
        (-1), or both one after the other.

        Each way starts again from the start frame: every frame is judged only by the one or two frames next to
        it on the way from there. `on_frame()` is called after every frame tried. scene_of(frame) gives (ids, points) of the points that may belong to this object
        in that frame; afterwards `poses[frame]`, `results[frame]` (with `ids` of the members) and
        `extents[frame]` hold what was found. The start frame itself gets a pose and an extent, no result.
        """
        settings = {"reach": reach, "gap": gap, "least": least, "weight": weight, "trust": trust}
        self.gap = gap
        at = frames.index(start)
        self.recent = deque([self.start], maxlen=self.window + 1)
        self.low, self.high = self._extent()
        self.poses, self.results, self.extents = {start: self.first}, {}, {start: (self.low.copy(), self.high.copy())}
        for direction in directions:
            self.recent = deque([self.start], maxlen=self.window + 1)
            self.low, self.high = self.extents[start]
            self.before = self.aside
            pose, shift = self.first, np.zeros(3)
            index = at + direction
            while 0 <= index < len(frames):
                frame = frames[index]
                guess = pose.copy()
                guess[:3, 3] += shift
                ids, points = scene_of(frame)
                self.last = pose
                found = self.follow(guess, points, blind=index == at + direction, **settings) if len(ids) else None
                if on_frame:
                    on_frame()
                if found is None or found["score"] < lost:
                    break
                found["ids"] = ids[found["members"]]
                self.poses[frame], self.results[frame] = found["pose"], found
                self.extents[frame] = (self.low.copy(), self.high.copy())
                shift, pose = found["pose"][:3, 3] - pose[:3, 3], found["pose"]
                index += direction
        return self
