"""Point labels: the class list, the editable per-point layer, and the geometry that suggests what to label."""
import colorsys
import re

import numpy as np

UNLABELED = 0
OBSTACLE, FREE_ROLE, IGNORE = "obstacle", "free", "ignore"
ROLES = (OBSTACLE, FREE_ROLE, IGNORE)
EMPTY = np.zeros(0, np.int64)
UNLABELED_RGB = (150, 150, 150)

_LAS = {1: "unassigned", 2: "ground", 3: "low vegetation", 4: "medium vegetation", 5: "high vegetation", 6: "building",
        7: "low noise", 9: "water", 10: "rail", 11: "road surface", 13: "wire guard", 14: "wire conductor",
        15: "transmission tower", 16: "wire connector", 17: "bridge deck", 18: "high noise"}
_KITTI = {1: "outlier", 10: "car", 11: "bicycle", 13: "bus", 15: "motorcycle", 16: "on-rails", 18: "truck",
          20: "other-vehicle", 30: "person", 31: "bicyclist", 32: "motorcyclist", 40: "road", 44: "parking",
          48: "sidewalk", 49: "other-ground", 50: "building", 51: "fence", 52: "other-structure", 60: "lane-marking",
          70: "vegetation", 71: "trunk", 72: "terrain", 80: "pole", 81: "traffic-sign", 99: "other-object",
          252: "moving-car", 253: "moving-bicyclist", 254: "moving-person", 255: "moving-motorcyclist",
          256: "moving-on-rails", 257: "moving-bus", 258: "moving-truck", 259: "moving-other-vehicle"}
_INDOOR = {1: ("floor", FREE_ROLE), 2: ("wall", OBSTACLE), 3: ("ceiling", IGNORE), 4: ("door", OBSTACLE),
           5: ("furniture", OBSTACLE), 6: ("machine", OBSTACLE), 7: ("person", IGNORE), 8: ("moving object", IGNORE),
           9: ("noise", IGNORE)}
_ROLE_HINTS = {FREE_ROLE: ("ground", "road", "floor", "parking", "sidewalk", "terrain", "lane"),
               IGNORE: ("noise", "outlier", "moving", "person", "cyclist", "unassigned")}
_SOFT_HINTS = ("person", "people", "pedestrian", "cyclist", "rider", "animal", "human")
PRESETS = ("indoor", "semantickitti", "las", "blank")


def shade(number):
    """A distinct, repeatable colour for a class or instance number."""
    hue = (number * 0.6180339887) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55 + 0.4 * ((number * 7) % 3) / 2, 0.95 - 0.25 * ((number * 5) % 3) / 2)
    return int(r * 255), int(g * 255), int(b * 255)


def instance_colours(numbers):
    """RGB per instance number; 0 (no instance) is grey."""
    numbers = np.asarray(numbers, np.int64)
    unique, inverse = np.unique(numbers, return_inverse=True)
    table = np.array([UNLABELED_RGB if n == 0 else shade(int(n)) for n in unique], np.uint8).reshape(-1, 3)
    return table[inverse]


def guess_role(name):
    lowered = name.lower()
    for role, hints in _ROLE_HINTS.items():
        if any(hint in lowered for hint in hints):
            return role
    return OBSTACLE


class ClassList:
    """Label classes by number. Class 0 always exists and means 'not labeled'."""

    def __init__(self, preset="blank"):
        self.items = {}
        source = {"indoor": _INDOOR, "semantickitti": _KITTI, "las": _LAS}.get(preset, {})
        for number, entry in source.items():
            name, role = entry if isinstance(entry, tuple) else (entry, guess_role(entry))
            self.set(number, name, role=role)

    def set(self, number, name, rgb=None, role=OBSTACLE, wins=False, soft=None):
        """soft: the class changes shape while it moves (people); None decides from the name."""
        number = int(number)
        if not 0 < number < 65536:
            raise ValueError("class numbers run from 1 to 65535")
        self.items[number] = {"name": str(name), "rgb": tuple(int(v) for v in (rgb or shade(number))),
                              "role": role if role in ROLES else OBSTACLE, "wins": bool(wins),
                              "soft": any(hint in str(name).lower() for hint in _SOFT_HINTS) if soft is None else bool(soft)}

    def remove(self, number):
        self.items.pop(int(number), None)

    def numbers(self):
        return sorted(self.items)

    def __len__(self):
        return len(self.items)

    def __contains__(self, number):
        return int(number) in self.items

    def name(self, number):
        return self.items[number]["name"] if number in self.items else ("" if number == UNLABELED else str(number))

    def rgb(self, number):
        return self.items[number]["rgb"] if number in self.items else UNLABELED_RGB if number == UNLABELED else shade(number)

    def role(self, number):
        return self.items[number]["role"] if number in self.items else OBSTACLE

    def next_free(self):
        number = 1
        while number in self.items:
            number += 1
        return number

    def ensure(self, numbers):
        """Add an entry for every class number that occurs in data but is not listed yet."""
        for number in np.unique(np.asarray(numbers)).tolist():
            if number != UNLABELED and number not in self.items:
                self.set(number, f"class {number}")

    def palette(self, top):
        """RGB lookup table covering class numbers 0..top."""
        table = np.array([self.rgb(number) for number in range(int(top) + 1)], np.uint8).reshape(-1, 3)
        return table

    def with_role(self, role):
        return [number for number in self.numbers() if self.items[number]["role"] == role]

    def soft(self, number):
        return self.items[number]["soft"] if number in self.items else False

    def dominant(self):
        """Classes that take a voxel as soon as one of their points is in it (for things a map must never miss)."""
        return [number for number in self.numbers() if self.items[number]["wins"]]

    def priority(self):
        """Order that settles a tied vote: obstacles before free surface before ignored classes, then by number."""
        return sorted(self.numbers(), key=lambda number: (ROLES.index(self.role(number)), number))

    def dumps(self):
        lines = ["# MapBarber label classes", "classes:"]
        for number in self.numbers():
            item = self.items[number]
            name = item["name"].replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'  - {{id: {number}, name: "{name}", color: [{", ".join(map(str, item["rgb"]))}], '
                         f'role: {item["role"]}' + (", wins: true" if item["wins"] else "")
                         + f', soft: {"true" if item["soft"] else "false"}' + "}")
        return "\n".join(lines) + "\n"

    @classmethod
    def loads(cls, text):
        """Read a class file written by dumps(), or the `labels:` / `color_map:` sections of a SemanticKITTI config."""
        out = cls()
        entry = re.compile(r'id:\s*(\d+).*?name:\s*"((?:[^"\\]|\\.)*)"(?:.*?color:\s*\[([^\]]*)\])?(?:.*?role:\s*(\w+))?'
                           r'(?:.*?wins:\s*(\w+))?(?:.*?soft:\s*(\w+))?')
        section, colours = None, {}
        for line in text.splitlines():
            found = entry.search(line)
            if found:
                number, name, colour, role, wins, soft = found.groups()
                rgb = [int(float(v)) for v in colour.split(",")] if colour else None
                out.set(int(number), name.replace('\\"', '"').replace("\\\\", "\\"), rgb, role or OBSTACLE,
                        wins == "true", None if soft is None else soft == "true")
                continue
            head = re.match(r"^(\w+):\s*(#.*)?$", line)
            if head:
                section = head.group(1)
                continue
            pair = re.match(r"^\s+(\d+)\s*:\s*(.+?)\s*$", line.split(" #")[0])
            if pair and section == "labels" and int(pair.group(1)) != UNLABELED:
                name = pair.group(2).strip("\"'")
                out.set(int(pair.group(1)), name, role=guess_role(name))
            elif pair and section == "color_map":
                colours[int(pair.group(1))] = [int(v) for v in pair.group(2).strip("[]").split(",")][::-1]
        for number, rgb in colours.items():
            if number in out.items and len(rgb) == 3:
                out.items[number]["rgb"] = tuple(rgb)
        return out

    def save(self, path):
        from .safeio import replacing
        with replacing(path) as part, open(part, "w", encoding="utf-8") as f:
            f.write(self.dumps())

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.loads(f.read())


class LabelLayer:
    """Class and instance number per point, with undo and a record of what changed since the last save.

    `pending` marks labels that were suggested (carried over from other frames or filled in) and not yet confirmed.
    """

    def __init__(self, count, cls=None, inst=None):
        self.cls = np.zeros(count, np.uint16) if cls is None else np.ascontiguousarray(cls, np.uint16).copy()
        self.inst = np.zeros(count, np.uint32) if inst is None else np.ascontiguousarray(inst, np.uint32).copy()
        self.pending = np.zeros(count, bool)
        self.touched = EMPTY
        self._undo, self._redo = [], []
        self.mark_saved()

    def __len__(self):
        return len(self.cls)

    @property
    def any(self):
        return bool(self.cls.any() or self.inst.any())

    @property
    def dirty(self):
        return not (np.array_equal(self.cls, self._saved[0]) and np.array_equal(self.inst, self._saved[1]))

    def mark_saved(self):
        self._saved = (self.cls.copy(), self.inst.copy())

    def allowed(self, ids, rule="all", target=None, locked=()):
        """Keep the points a write may touch: rule 'all', 'unlabeled' or 'only' (points of class `target`)."""
        ids = np.asarray(ids, np.int64)
        current = self.cls[ids]
        keep = np.ones(len(ids), bool)
        if rule == "unlabeled":
            keep = current == UNLABELED
        elif rule == "only":
            keep = current == target
        if len(locked):
            keep &= ~np.isin(current, np.fromiter(locked, np.int64))
        return ids[keep]

    def assign(self, ids, cls=None, inst=None, pending=False):
        """Write a class and/or instance number (scalars or one per point); returns how many points changed."""
        ids = np.asarray(ids, np.int64)
        new_cls = self.cls[ids] if cls is None else np.broadcast_to(np.asarray(cls, np.uint16), ids.shape)
        new_inst = self.inst[ids] if inst is None else np.broadcast_to(np.asarray(inst, np.uint32), ids.shape)
        changed = (new_cls != self.cls[ids]) | (new_inst != self.inst[ids]) | (self.pending[ids] != pending)
        ids, new_cls, new_inst = ids[changed], new_cls[changed], new_inst[changed]
        if not len(ids):
            return 0
        self._undo.append((ids, self.cls[ids].copy(), self.inst[ids].copy(), self.pending[ids].copy()))
        self._redo.clear()
        self.cls[ids], self.inst[ids], self.pending[ids] = new_cls, new_inst, pending
        self.touched = ids
        return len(ids)

    def confirm(self, ids=None):
        """Accept suggested labels as they are."""
        ids = np.flatnonzero(self.pending) if ids is None else np.asarray(ids, np.int64)[self.pending[ids]]
        return self.assign(ids, self.cls[ids], self.inst[ids]) if len(ids) else 0

    def undo_depth(self):
        return len(self._undo)

    def squash(self, depth):
        """Merge the steps recorded since `depth` into one, keeping the oldest value of every point."""
        steps = self._undo[depth:]
        if len(steps) < 2:
            return
        ids = np.concatenate([step[0] for step in steps])
        _, first = np.unique(ids, return_index=True)
        self._undo[depth:] = [tuple(np.concatenate([step[i] for step in steps])[first] for i in range(4))]

    def _swap(self, source, target):
        if not source:
            return False
        ids, cls, inst, pending = source.pop()
        target.append((ids, self.cls[ids].copy(), self.inst[ids].copy(), self.pending[ids].copy()))
        self.cls[ids], self.inst[ids], self.pending[ids] = cls, inst, pending
        self.touched = ids
        return True

    def undo(self):
        return self._swap(self._undo, self._redo)

    def redo(self):
        return self._swap(self._redo, self._undo)

    def counts(self, mask=None):
        """{class number: points}, over the masked points."""
        values = self.cls if mask is None else self.cls[mask]
        found = np.bincount(values)
        return {int(number): int(found[number]) for number in np.flatnonzero(found)}

    def next_instance(self):
        return int(self.inst.max(initial=0)) + 1


def vote(groups, cls, priority=(), dominant=()):
    """Label of each group of points (for example the points of one voxel) by majority.

    Unlabeled points do not vote. Ties go to the class that comes first in `priority`, then to the
    lower number. A class listed in `dominant` wins a group as soon as one of its points is there.
    Returns (sorted unique groups, winning class per group, share of the group's labeled points that agree).
    """
    groups, cls = np.asarray(groups, np.int64), np.asarray(cls, np.int64)
    unique = np.unique(groups)
    winner, purity = np.zeros(len(unique), np.uint16), np.ones(len(unique))
    labeled = cls != UNLABELED
    if not labeled.any():
        return unique, winner, purity
    slot = np.searchsorted(unique, groups[labeled])
    top = int(cls.max()) + 1
    pair, votes = np.unique(slot * top + cls[labeled], return_counts=True)
    pair_slot, pair_cls = pair // top, pair % top
    rank = np.full(top, len(priority) + len(dominant), np.int64)
    for position, number in enumerate(list(dominant) + [n for n in priority if n not in dominant]):
        if number < top:
            rank[number] = position
    weight = np.where(np.isin(pair_cls, np.fromiter(dominant, np.int64, len(dominant))), np.iinfo(np.int64).max // 2, votes)
    order = np.lexsort((pair_cls, rank[pair_cls], -weight, pair_slot))
    first = order[np.concatenate([[True], np.diff(pair_slot[order]) != 0])]
    total = np.bincount(pair_slot, weights=votes, minlength=len(unique))
    winner[pair_slot[first]] = pair_cls[first]
    purity[pair_slot[first]] = votes[first] / total[pair_slot[first]]
    return unique, winner, purity


def components(points, gap):
    """Group number per point: points belong together when a chain of steps no longer than about `gap` joins them."""
    points = np.asarray(points, np.float64).reshape(-1, 3)
    if not len(points):
        return EMPTY
    return cell_components(np.floor((points - points.min(axis=0)) / gap).astype(np.int64))


def cell_components(cells):
    """Group number per integer cell (N, 3): cells that touch by a face, an edge or a corner belong together."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    cells = np.asarray(cells, np.int64).reshape(-1, 3)
    if not len(cells):
        return EMPTY
    cells = cells - cells.min(axis=0) + 1
    span = cells.max(axis=0) + 2
    if float(span[0]) * float(span[1]) * float(span[2]) >= 2 ** 62:
        raise ValueError("the points spread too far for this gap; use a larger value")
    code = (cells[:, 0] * span[1] + cells[:, 1]) * span[2] + cells[:, 2]
    occupied, cell_of = np.unique(code, return_inverse=True)
    rows, columns = [], []
    for dx, dy, dz in [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1) if (i, j, k) > (0, 0, 0)]:
        neighbour = occupied + (dx * span[1] + dy) * span[2] + dz
        at = np.searchsorted(occupied, neighbour)
        at[at == len(occupied)] = 0
        hit = occupied[at] == neighbour
        rows.append(np.flatnonzero(hit))
        columns.append(at[hit])
    rows, columns = np.concatenate(rows), np.concatenate(columns)
    graph = coo_matrix((np.ones(len(rows), bool), (rows, columns)), shape=(len(occupied),) * 2)
    return connected_components(graph, directed=False)[1][cell_of]


def cluster_at(points, seed, gap):
    """Indices of the points connected to points[seed]."""
    group = components(points, gap)
    return np.flatnonzero(group == group[seed])


def small_groups(points, gap, largest):
    """Indices of points in connected groups of at most `largest` points."""
    group = components(points, gap)
    return np.flatnonzero(np.bincount(group)[group] <= largest)


def plane_at(points, seed, radius, tolerance):
    """Indices of the flat patch around points[seed]: fitted near the seed, then followed as far as it stays connected."""
    points = np.asarray(points, np.float64)
    centre = points[seed]
    near = points[np.einsum("ij,ij->i", points - centre, points - centre) <= radius * radius]
    if len(near) < 3:
        return np.array([seed], np.int64)
    for attempt in range(2):
        mean = near.mean(axis=0)
        normal = np.linalg.svd(near - mean, full_matrices=False)[2][2]
        offset = float(normal @ mean)
        if attempt == 0:
            wider = (np.abs(points @ normal - offset) <= tolerance) & \
                    (np.einsum("ij,ij->i", points - centre, points - centre) <= (3.0 * radius) ** 2)
            if wider.sum() < 3:
                break
            near = points[wider]
    inliers = np.flatnonzero(np.abs(points @ normal - offset) <= tolerance)
    if seed not in inliers:
        inliers = np.append(inliers, seed)
    group = components(points[inliers], max(radius / 2.0, 2.0 * tolerance))
    return inliers[group == group[np.flatnonzero(inliers == seed)[0]]]


def normals(points, neighbours=12, index=None):
    """Per point, from its nearest neighbours: (unit surface normal with arbitrary sign, how far from flat 0..1/3)."""
    from scipy.spatial import cKDTree
    points = np.asarray(points, np.float64)
    k = min(neighbours, len(points))
    if k < 3:
        return np.tile([0.0, 0.0, 1.0], (len(points), 1)), np.zeros(len(points))
    if index is None:
        _, index = cKDTree(points).query(points, k=k, workers=-1)
    centred = points[index] - points[index].mean(axis=1, keepdims=True)
    covariance = np.einsum("nki,nkj->nij", centred, centred)
    spread, axes = np.linalg.eigh(covariance)
    return axes[:, :, 0], spread[:, 0] / np.maximum(spread.sum(axis=1), 1e-30)


def grow(points, seed, step, angle, values=None, value_tolerance=None, crease=0.03):
    """Indices of the smooth surface around points[seed].

    Two points closer than `step` are joined when their normals differ by at most `angle` degrees
    and neither sits on a crease (where the surface bends, growth stops). With `values`, only points
    within `value_tolerance` of the seed's value take part. The result is everything joined to the seed.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    points = np.asarray(points, np.float64)
    usable = np.ones(len(points), bool)
    if values is not None and value_tolerance is not None:
        values = np.asarray(values, np.float64).reshape(len(points), -1)
        usable = np.abs(values - values[seed]).max(axis=1) <= value_tolerance
    keep = np.flatnonzero(usable)
    if len(keep) < 2:
        return np.array([seed], np.int64)
    local = points[keep]
    normal, bend = normals(local)
    pairs = cKDTree(local).query_pairs(step, output_type="ndarray")
    aligned = np.abs(np.einsum("ij,ij->i", normal[pairs[:, 0]], normal[pairs[:, 1]])) >= np.cos(np.radians(angle))
    aligned &= (bend[pairs[:, 0]] <= crease) & (bend[pairs[:, 1]] <= crease)
    pairs = pairs[aligned]
    graph = coo_matrix((np.ones(len(pairs), bool), (pairs[:, 0], pairs[:, 1])), shape=(len(keep),) * 2)
    group = connected_components(graph, directed=False)[1]
    return keep[group == group[np.searchsorted(keep, seed)]]


def connected(points, seed, gap, bend=None, surface=1.5, neighbours=12, cells=None):
    """Indices of the points joined to points[seed] by steps of about `gap`.

    With `bend` (degrees), the search stops where the direction of the surface changes sharply over many
    points. A point is on a smooth stretch when nearly all points within `gap` of it face the same way;
    a stretch at least `surface` metres across only joins points of that same stretch. So an object comes
    without the floor or wall it touches, and a click on the floor gives the floor without what stands on
    it. Points that are not on such a stretch join by distance alone, and points beside a stretch that lie
    in its plane (its rim, where directions mix) count as part of it.

    For voxels pass their integer `cells`: joining by distance then means touching cells.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    points = np.asarray(points, np.float64)
    count = len(points)
    k = min(neighbours, count)
    def together(members):
        return components(points[members], gap) if cells is None else cell_components(cells[members])

    if bend is None or bend >= 90.0 or k < 4:
        group = together(np.arange(count))
        return np.flatnonzero(group == group[seed])
    distance, index = cKDTree(points).query(points, k=k, workers=-1)
    normal, _ = normals(points, index=index)
    limit = np.cos(np.radians(bend))

    # A thinned copy of the cloud stands in for "every point within gap" when asking whether directions agree.
    fine = np.floor((points - points.min(axis=0)) / (gap / 3.0)).astype(np.int64)
    span = fine.max(axis=0) + 1
    if float(span[0]) * float(span[1]) * float(span[2]) >= 2 ** 62:
        raise ValueError("the points spread too far for this gap; use a larger value")
    _, sample = np.unique((fine[:, 0] * span[1] + fine[:, 1]) * span[2] + fine[:, 2], return_index=True)
    reach, around = cKDTree(points[sample]).query(points, k=min(24, len(sample)), distance_upper_bound=gap, workers=-1)
    reach, around = reach.reshape(count, -1), around.reshape(count, -1)
    seen = np.isfinite(reach)
    around = sample[np.minimum(around, len(sample) - 1)]
    same_way = seen & (np.abs(np.einsum("nkj,nj->nk", normal[around], normal)) >= limit)
    smooth = (seen.sum(axis=1) >= 4) & (same_way.sum(axis=1) >= 0.85 * seen.sum(axis=1))

    near = index[:, 1:]
    rows = np.repeat(np.arange(count), k - 1)
    link = ((distance[:, 1:] <= gap) & (np.abs(np.einsum("nkj,nj->nk", normal[near], normal)) >= limit)).ravel()
    link &= smooth[rows] & smooth[near.ravel()]
    graph = coo_matrix((np.ones(int(link.sum()), bool), (rows[link], near.ravel()[link])), shape=(count, count))
    patch = connected_components(graph, directed=False)[1]
    order = np.argsort(patch, kind="stable")
    starts = np.flatnonzero(np.r_[True, np.diff(patch[order]) != 0])
    extent = np.linalg.norm(np.maximum.reduceat(points[order], starts) - np.minimum.reduceat(points[order], starts), axis=1)
    wide = smooth & (extent[patch] >= surface)

    home = np.where(wide, patch, -1)
    off_plane = np.abs(np.einsum("nkj,nkj->nk", points[:, None, :] - points[around], normal[around]))
    off_plane[~(seen & wide[around])] = np.inf
    nearest = np.argmin(off_plane, axis=1)
    on_rim = ~wide & (off_plane[np.arange(count), nearest] <= 0.3 * gap)
    home[on_rim] = patch[around[on_rim, nearest[on_rim]]]
    if home[seed] >= 0:
        return np.flatnonzero(home == home[seed])
    rest = np.flatnonzero(home < 0)
    group = together(rest)
    return rest[group == group[np.searchsorted(rest, seed)]]


def disagreeing(points, cls, neighbours=8, share=0.5):
    """Indices of labeled points whose label is shared by less than `share` of their labeled neighbours."""
    from scipy.spatial import cKDTree
    labeled = np.flatnonzero(np.asarray(cls) != UNLABELED)
    k = min(neighbours + 1, len(labeled))
    if k < 2:
        return EMPTY
    local = np.asarray(points, np.float64)[labeled]
    _, index = cKDTree(local).query(local, k=k)
    own = np.asarray(cls)[labeled]
    agree = (own[index[:, 1:]] == own[:, None]).mean(axis=1)
    return labeled[agree < share]


def suggest(points, cls, radius, neighbours=8):
    """For unlabeled points with labeled points within `radius`: (indices, majority class of those neighbours)."""
    from scipy.spatial import cKDTree
    cls = np.asarray(cls)
    labeled, empty = np.flatnonzero(cls != UNLABELED), np.flatnonzero(cls == UNLABELED)
    if not len(labeled) or not len(empty):
        return EMPTY, np.zeros(0, np.uint16)
    points = np.asarray(points, np.float64)
    k = min(neighbours, len(labeled))
    distance, index = cKDTree(points[labeled]).query(points[empty], k=k, distance_upper_bound=radius)
    distance, index = distance.reshape(len(empty), k), index.reshape(len(empty), k)
    found = np.isfinite(distance)
    seen = np.where(found, cls[labeled][np.minimum(index, len(labeled) - 1)], UNLABELED)
    best, best_votes = np.zeros(len(empty), np.uint16), np.zeros(len(empty), np.int64)
    for number in np.unique(seen[found]).tolist():
        votes = (seen == number).sum(axis=1)
        better = votes > best_votes
        best[better], best_votes[better] = number, votes[better]
    return empty[best_votes > 0], best[best_votes > 0]


class Transfer:
    """Hands labels from one set of points to others nearby."""

    def __init__(self, points, cls, classes=None):
        from scipy.spatial import cKDTree
        cls = np.asarray(cls)
        usable = cls != UNLABELED
        if classes is not None:
            usable &= np.isin(cls, np.fromiter(classes, np.int64))
        self.cls = cls[usable]
        self.tree = cKDTree(np.asarray(points, np.float64)[usable]) if usable.any() else None

    def to(self, points, radius):
        """Class for each point from the nearest labeled source point within `radius` (0 where there is none)."""
        out = np.zeros(len(points), np.uint16)
        if self.tree is None or not len(points):
            return out
        distance, index = self.tree.query(points, distance_upper_bound=radius)
        found = np.isfinite(distance)
        out[found] = self.cls[index[found]]
        return out


def transfer(source_points, source_cls, target_points, radius, classes=None):
    return Transfer(source_points, source_cls, classes).to(target_points, radius)


def conflicts(points, cls, frame, radius, neighbours=8):
    """Indices of labeled points that have a point of another frame within `radius` carrying a different label."""
    from scipy.spatial import cKDTree
    cls, frame = np.asarray(cls), np.asarray(frame)
    labeled = np.flatnonzero(cls != UNLABELED)
    k = min(neighbours + 1, len(labeled))
    if k < 2:
        return EMPTY
    local = np.asarray(points, np.float64)[labeled]
    distance, index = cKDTree(local).query(local, k=k, distance_upper_bound=radius)
    index = np.minimum(index, len(labeled) - 1)
    own_cls, own_frame = cls[labeled], frame[labeled]
    clash = np.isfinite(distance) & (own_cls[index] != own_cls[:, None]) & (own_frame[index] != own_frame[:, None])
    return labeled[clash.any(axis=1)]


def oriented_box(points):
    """Upright box around points: (centre xyz, size along its own x y z, yaw in radians)."""
    points = np.asarray(points, np.float64)
    flat = points[:, :2] - points[:, :2].mean(axis=0)
    yaw = 0.0
    if len(points) > 2:
        axis = np.linalg.svd(flat, full_matrices=False)[2][0]
        yaw = float(np.arctan2(axis[1], axis[0]))
    c, s = np.cos(yaw), np.sin(yaw)
    turned = points[:, :2] @ np.array([[c, -s], [s, c]])
    low = np.array([turned[:, 0].min(), turned[:, 1].min(), points[:, 2].min()])
    high = np.array([turned[:, 0].max(), turned[:, 1].max(), points[:, 2].max()])
    middle = (low + high) / 2
    centre = np.array([c * middle[0] - s * middle[1], s * middle[0] + c * middle[1], middle[2]])
    return centre, high - low, yaw


def boxes(points, cls, inst):
    """One upright box per instance: [(class, instance, centre, size, yaw, points)]."""
    out = []
    for number in np.unique(inst[inst != 0]).tolist():
        members = np.flatnonzero(inst == number)
        centre, size, yaw = oriented_box(points[members])
        out.append((int(np.bincount(cls[members]).argmax()), number, centre, size, yaw, len(members)))
    return out


def _lookup(keys, table_keys, table_values):
    """Values stored for sorted `table_keys` at `keys`, and which keys were found."""
    keys = np.asarray(keys, np.int64)
    if not len(table_keys):
        return np.zeros(len(keys), table_values.dtype), np.zeros(len(keys), bool)
    at = np.minimum(np.searchsorted(table_keys, keys), len(table_keys) - 1)
    found = table_keys[at] == keys
    return np.where(found, table_values[at], 0).astype(table_values.dtype), found


class VoxelLabels:
    """Class of each voxel: a base layer (voted from points, or read from a file) with edits on top, and undo.

    Keeping the edits apart from the base tells which voxels a person relabeled, so that turning the map
    back into points can change exactly the points of those voxels and leave every other point as it was.
    """

    def __init__(self, keys=EMPTY, values=None, purity=None):
        keys = np.asarray(keys, np.int64)
        order = np.argsort(keys, kind="stable")
        self.base_keys = keys[order]
        self.base_values = (np.zeros(len(keys), np.uint16) if values is None else np.asarray(values, np.uint16)[order])
        self.purity = None if purity is None else np.asarray(purity, np.float32)[order]
        self.edit_keys, self.edit_values = EMPTY, np.zeros(0, np.uint16)
        self.touched = EMPTY
        self._undo, self._redo = [], []
        self.mark_saved()

    @property
    def any(self):
        return bool(self.base_values.any() or self.edit_values.any())

    def base(self, keys):
        return _lookup(keys, self.base_keys, self.base_values)[0]

    def get(self, keys):
        values, _ = _lookup(keys, self.base_keys, self.base_values)
        edits, found = _lookup(keys, self.edit_keys, self.edit_values)
        values[found] = edits[found]
        return values

    def _write(self, keys, values, present):
        """Replace the edit entries of `keys`: those with `present` set get `values`, the others are dropped."""
        keep = ~np.isin(self.edit_keys, keys, assume_unique=True)
        merged_keys = np.concatenate([self.edit_keys[keep], keys[present]])
        merged_values = np.concatenate([self.edit_values[keep], values[present]])
        order = np.argsort(merged_keys, kind="stable")
        self.edit_keys, self.edit_values = merged_keys[order], merged_values[order]
        self.touched = keys

    def set(self, keys, value):
        """Give voxels a class (a scalar or one per key); returns how many voxels changed."""
        keys, index = np.unique(np.asarray(keys, np.int64), return_index=True)
        values = np.broadcast_to(np.asarray(value, np.uint16), (len(index),) if np.ndim(value) == 0 else np.shape(value))
        values = np.asarray(values)[index] if np.ndim(value) else np.asarray(values)
        changed = self.get(keys) != values
        keys, values = keys[changed], values[changed]
        if not len(keys):
            return 0
        before, had = _lookup(keys, self.edit_keys, self.edit_values)
        self._undo.append((keys, before, had))
        self._redo.clear()
        self._write(keys, values, np.ones(len(keys), bool))
        return len(keys)

    def undo_depth(self):
        return len(self._undo)

    def squash(self, depth):
        steps = self._undo[depth:]
        if len(steps) < 2:
            return
        keys = np.concatenate([step[0] for step in steps])
        keys, first = np.unique(keys, return_index=True)
        self._undo[depth:] = [(keys,) + tuple(np.concatenate([step[i] for step in steps])[first] for i in (1, 2))]

    def _swap(self, source, target):
        if not source:
            return False
        keys, values, present = source.pop()
        before, had = _lookup(keys, self.edit_keys, self.edit_values)
        target.append((keys, before, had))
        self._write(keys, values, present)
        return True

    def undo(self):
        return self._swap(self._undo, self._redo)

    def redo(self):
        return self._swap(self._redo, self._undo)

    @property
    def dirty(self):
        return not (np.array_equal(self.edit_keys, self._saved[0]) and np.array_equal(self.edit_values, self._saved[1]))

    def mark_saved(self):
        self._saved = (self.edit_keys.copy(), self.edit_values.copy())

    def edited(self):
        """(keys, classes) of voxels whose class differs from the base layer."""
        differs = self.base(self.edit_keys) != self.edit_values
        return self.edit_keys[differs], self.edit_values[differs]

    def mixed(self, keys, below):
        """Keys whose points agreed on their class less than `below` (0..1) and that nobody relabeled since."""
        if self.purity is None:
            return EMPTY
        keys = np.asarray(keys, np.int64)
        purity, found = _lookup(keys, self.base_keys, self.purity)
        edited = np.isin(keys, self.edit_keys)
        return keys[found & ~edited & (purity < below)]

    def counts(self, keys):
        found = np.bincount(self.get(keys))
        return {int(number): int(found[number]) for number in np.flatnonzero(found)}


def by_group(points, groups, function):
    """Run `function(points of one group)` for each group and put the per-point results back in place.

    Used per LiDAR frame of a merged sequence: frames whose poses disagree by a few centimetres in height
    would otherwise stack the same road in layers, and only the lowest layer would count as ground.
    """
    groups = np.asarray(groups)
    order = np.argsort(groups, kind="stable")
    starts = np.flatnonzero(np.r_[True, np.diff(groups[order]) != 0])
    out = None
    for first, last in zip(starts, np.r_[starts[1:], len(order)]):
        members = order[first:last]
        result = np.asarray(function(points[members]))
        if out is None:
            out = np.zeros(len(points), result.dtype)
        out[members] = result
    return np.zeros(len(points), bool) if out is None else out


def ground_by_group(points, groups, **settings):
    """Ground mask decided separately for each group (for example each frame of a merged sequence)."""
    return by_group(points, groups, lambda part: ground(part, **settings))


def _surface(points, cell, slope, low_share, least, pit_depth=0.3):
    """Lowest surface under points on a grid of `cell` metres: (grid corner, cell size, heights per cell).

    Each cell with at least `least` points offers the `low_share` quantile of their heights. A cell far
    below the cells around it is a pit made by stray points and is dropped. Empty cells take the nearest
    known value; then no cell may stand higher than a neighbour plus the slope's rise.
    """
    from scipy import ndimage
    low = points[:, :2].min(axis=0)
    ij = np.floor((points[:, :2] - low) / cell).astype(np.int64)
    shape = ij.max(axis=0) + 1
    if shape[0] * shape[1] > 60_000_000:
        raise ValueError("the cloud spreads too far for this cell size; use larger cells")
    flat = ij[:, 0] * shape[1] + ij[:, 1]
    order = np.lexsort((points[:, 2], flat))
    flat_sorted = flat[order]
    starts = np.flatnonzero(np.r_[True, np.diff(flat_sorted) != 0])
    counts = np.diff(np.r_[starts, len(order)])
    enough = counts >= least
    pick = order[starts[enough] + np.floor(counts[enough] * low_share).astype(np.int64)]
    height = np.full(shape, np.nan)
    height.ravel()[flat_sorted[starts[enough]]] = points[pick, 2]
    known = np.isfinite(height)
    if not known.any():
        return low, cell, None
    rise = np.tan(np.radians(slope)) * cell
    for _ in range(3):
        nearest = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
        around = ndimage.median_filter(height[tuple(nearest)], size=7, mode="nearest")
        pits = known & (height < around - (3 * rise + pit_depth))
        if not pits.any() or pits.sum() == known.sum():
            break
        height[pits], known = np.nan, known & ~pits
    nearest = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
    surface = height[tuple(nearest)]
    diagonal = rise * np.sqrt(2.0)
    for _ in range(int(shape.max()) + 2):
        padded = np.pad(surface, 1, mode="edge")
        lowest = surface.copy()
        for dx, dy in [(i, j) for i in (-1, 0, 1) for j in (-1, 0, 1) if (i, j) != (0, 0)]:
            neighbour = padded[1 + dx:1 + dx + shape[0], 1 + dy:1 + dy + shape[1]]
            np.minimum(lowest, neighbour + (diagonal if dx and dy else rise), out=lowest)
        if np.array_equal(lowest, surface):
            break
        surface = lowest
    return low, cell, surface


def _level(points, low, cell, surface):
    """Height of a gridded surface under each point, interpolated between cell centres."""
    shape = np.array(surface.shape)
    position = (points[:, :2] - low) / cell - 0.5
    base = np.clip(np.floor(position).astype(np.int64), 0, shape - 1)
    upper = np.minimum(base + 1, shape - 1)
    fraction = np.clip(position - base, 0.0, 1.0)
    top = surface[base[:, 0], base[:, 1]] * (1 - fraction[:, 1]) + surface[base[:, 0], upper[:, 1]] * fraction[:, 1]
    bottom = surface[upper[:, 0], base[:, 1]] * (1 - fraction[:, 1]) + surface[upper[:, 0], upper[:, 1]] * fraction[:, 1]
    return top * (1 - fraction[:, 0]) + bottom * fraction[:, 0]


def height_above_ground(points, cell=0.5, slope=15.0, tolerance=0.15, low_share=0.05):
    """Height of every point above the ground under it (NaN for points far below it, which are noise).

    The ground is the lowest surface under the cloud that nowhere rises steeper than `slope` degrees.
    First a coarse surface from wide cells, taken well above their lowest points, marks points that lie
    far below it as noise (reflections, multipath). The fine surface is then built from the remaining
    points with cells of `cell` metres: each cell offers a height near the bottom of its points, and no
    cell may stand higher than a neighbour plus the rise the slope allows, which brings down cells whose
    ground is hidden under a car or a wall.
    """
    points = np.asarray(points, np.float64)
    out = np.full(len(points), np.nan)
    if len(points) < 3:
        return out
    coarse = max(4.0 * cell, 2.0)
    low, size, surface = _surface(points, coarse, slope, 0.1, 8)
    keep = np.ones(len(points), bool)
    if surface is not None:
        keep = points[:, 2] >= _level(points, low, size, surface) - (2 * tolerance + np.tan(np.radians(slope)) * coarse)
    low, size, surface = _surface(points[keep], cell, slope, low_share, 1, 2 * tolerance)
    if surface is None:
        return out
    offset = points[:, 2] - _level(points, low, size, surface)
    below = -2 * tolerance - np.tan(np.radians(slope)) * cell
    out[keep & (offset >= below)] = offset[keep & (offset >= below)]
    return out


def ground(points, cell=0.5, slope=15.0, tolerance=0.15, low_share=0.05):
    """Mask of ground points: those within `tolerance` above the surface found by height_above_ground."""
    height = height_above_ground(points, cell, slope, tolerance, low_share)
    return np.isfinite(height) & (height <= tolerance)


def with_feet(points, picked, candidates, reach):
    """Add to `picked` the candidate points that hang on to it by steps of at most `reach` (an object's lowest part)."""
    from scipy.spatial import cKDTree
    picked, candidates = np.asarray(picked, np.int64), np.asarray(candidates, np.int64)
    for _ in range(8):
        if not len(candidates) or not len(picked):
            break
        distance, _ = cKDTree(points[picked]).query(points[candidates], distance_upper_bound=reach)
        joined = np.isfinite(distance)
        if not joined.any():
            break
        picked, candidates = np.concatenate([picked, candidates[joined]]), candidates[~joined]
    return picked
