"""OctoMap-compatible octree files (.bt binary, .ot full), handled as a linear octree.

Cells are kept as a sorted array of Morton codes, so every tree node is a contiguous
slice of that array and no pointer tree is ever built. Files are decoded and encoded
one tree level at a time with array operations, never node by node.
"""
import struct

import numpy as np

from .safeio import replacing
from .voxels import DEPTH, EMPTY, OFFSET, pack, unpack

OCCUPIED_LOG_ODDS = 3.5
MAX_EXPANDED_CELLS = 150_000_000

# Extra bytes stored per node after the log-odds value, by tree id.
_NODE_PAYLOAD = {"OcTree": 0, "OcTreeStamped": 0, "ColorOcTree": 3}
_SPREAD = ((32, 0x1F00000000FFFF), (16, 0x1F0000FF0000FF), (8, 0x100F00F00F00F00F), (4, 0x10C30C30C30C30C3),
           (2, 0x1249249249249249))


def _spread(v):
    v = v.astype(np.int64)
    for shift, mask in _SPREAD:
        v = (v | (v << shift)) & mask
    return v


def _compact(v):
    v = v & _SPREAD[-1][1]
    for (shift, _), mask in zip(reversed(_SPREAD), [m for _, m in reversed(_SPREAD[:-1])] + [0x1FFFFF]):
        v = (v | (v >> shift)) & mask
    return v


def morton_encode(cells):
    """Non-negative cell indices (N, 3) -> interleaved codes with x in the lowest bit."""
    return _spread(cells[:, 0]) | (_spread(cells[:, 1]) << 1) | (_spread(cells[:, 2]) << 2)


def morton_decode(codes):
    return np.stack([_compact(codes), _compact(codes >> 1), _compact(codes >> 2)], axis=1)


def _codes_from_keys(keys):
    return np.sort(morton_encode(unpack(keys) + OFFSET))


def _keys_from_blocks(bases, levels):
    """Blocks given by first Morton code and level -> keys of every cell they cover."""
    if not len(bases):
        return EMPTY
    spans = np.int64(1) << (3 * levels)
    total = int(spans.sum())
    if total > MAX_EXPANDED_CELLS:
        raise ValueError("occupied volume is too large to edit at this resolution")
    codes = np.repeat(bases, spans) + (np.arange(total) - np.repeat(np.cumsum(spans) - spans, spans))
    return np.sort(pack(morton_decode(codes) - OFFSET))


def _subtree_ends(children):
    """Index of the last node of every node's subtree, for nodes stored in pre-order with their child counts."""
    count = len(children)
    after = np.cumsum(children.astype(np.int64) - 1)
    before = np.concatenate([[0], after[:-1]])
    width = count + 1
    lookup = np.sort((after + 1) * width + np.arange(count))
    wanted = before * width + np.arange(count)
    found = np.searchsorted(lookup, wanted)
    if (found >= count).any():
        raise ValueError(DAMAGED)
    hit = lookup[found]
    if (hit // width != before).any():
        raise ValueError(DAMAGED)
    return hit % width


def _walk(states_of, inner_of, count):
    """Visit a pre-order node stream level by level.

    states_of(positions, octant) -> per-node state of that octant, where state 3 means "has a child node there".
    Yields (positions, bases, level) for the nodes of each level, top down.
    """
    ends = _subtree_ends(inner_of)
    if int(ends[0]) != count - 1:
        raise ValueError(DAMAGED)
    positions, bases, level = np.zeros(1, np.int64), np.zeros(1, np.int64), DEPTH
    while len(positions):
        yield positions, bases, level
        if level == 0:
            if inner_of[positions].any():
                raise ValueError(DAMAGED)
            return
        span = np.int64(1) << (3 * (level - 1))
        cursor = positions + 1
        next_positions, next_bases = [], []
        for octant in range(8):
            has_child = states_of(positions, octant) == 3
            child = cursor[has_child]
            next_positions.append(child)
            next_bases.append(bases[has_child] + octant * span)
            cursor[has_child] = ends[child] + 1
        positions, bases, level = np.concatenate(next_positions), np.concatenate(next_bases), level - 1


def _parse_header(data):
    fields, pos = {}, 0
    while True:
        end = data.find(b"\n", pos)
        if end < 0:
            raise ValueError("not an OctoMap file: missing 'data' marker")
        line = data[pos:end].decode("ascii", errors="replace").strip()
        pos = end + 1
        if line == "data":
            return fields, pos
        if line and not line.startswith("#"):
            key, _, value = line.partition(" ")
            fields[key] = value.strip()


DAMAGED = "the octree data ends early or is malformed; the file is truncated or damaged"


def read_bt(path):
    """Binary octree -> (occupied keys, resolution)."""
    try:
        return _read_bt(path)
    except (IndexError, KeyError, struct.error) as error:
        raise ValueError(DAMAGED) from error


def read_ot(path):
    """Full octree (OcTree, OcTreeStamped or ColorOcTree) -> (occupied keys, resolution)."""
    try:
        return _read_ot(path)
    except (IndexError, KeyError, struct.error) as error:
        raise ValueError(DAMAGED) from error


def _read_bt(path):
    with open(path, "rb") as f:
        data = f.read()
    fields, pos = _parse_header(data)
    resolution = float(fields["res"])
    nodes = np.frombuffer(data, "<u2", count=(len(data) - pos) // 2, offset=pos).astype(np.int64)
    if not len(nodes):
        return EMPTY, resolution
    pairs = (nodes[:, None] >> (2 * np.arange(8))) & 3
    block_bases, block_levels = [], []
    for positions, bases, level in _walk(lambda p, octant: pairs[p, octant], (pairs == 3).sum(axis=1), len(nodes)):
        span = np.int64(1) << (3 * (level - 1))
        for octant in range(8):
            occupied = pairs[positions, octant] == 2
            block_bases.append(bases[occupied] + octant * span)
            block_levels.append(np.full(int(occupied.sum()), level - 1, np.int64))
    return _keys_from_blocks(np.concatenate(block_bases), np.concatenate(block_levels)), resolution


def _read_ot(path):
    with open(path, "rb") as f:
        data = f.read()
    fields, pos = _parse_header(data)
    tree_id = fields.get("id", "OcTree")
    if tree_id not in _NODE_PAYLOAD:
        raise ValueError(f"unsupported octree type: {tree_id}")
    resolution = float(fields["res"])
    record = np.dtype([("value", "<f4"), ("payload", "u1", (_NODE_PAYLOAD[tree_id],)), ("mask", "u1")])
    nodes = np.frombuffer(data, record, count=(len(data) - pos) // record.itemsize, offset=pos)
    if not len(nodes):
        return EMPTY, resolution
    mask = nodes["mask"].astype(np.int64)
    present = (mask[:, None] >> np.arange(8)) & 1
    block_bases, block_levels = [], []
    for positions, bases, level in _walk(lambda p, octant: present[p, octant] * 3, present.sum(axis=1), len(nodes)):
        leaf = (mask[positions] == 0) & (nodes["value"][positions] > 0.0)
        block_bases.append(bases[leaf])
        block_levels.append(np.full(int(leaf.sum()), level, np.int64))
    return _keys_from_blocks(np.concatenate(block_bases), np.concatenate(block_levels)), resolution


def _octants(codes, low, high, level):
    """Split the slice [low, high) of a node at `level` into its non-empty octants.

    Yields (octant, low, high, solid) where solid means the octant is completely occupied.
    """
    span = 1 << (3 * (level - 1))
    base = (int(codes[low]) >> (3 * level)) << (3 * level)
    cuts = low + np.searchsorted(codes[low:high], base + span * np.arange(9))
    for octant in range(8):
        a, b = int(cuts[octant]), int(cuts[octant + 1])
        if b > a:
            yield octant, a, b, b - a == span


def _write(path, magic, body, count, resolution):
    with replacing(path) as part, open(part, "wb") as f:
        f.write(magic + b"\n# (written by MapBarber)\n")
        f.write(f"id OcTree\nsize {count}\nres {float(resolution)!r}\ndata\n".encode())
        f.write(body)


def _levels(codes):
    """Per tree level, bottom up: (node prefixes, cell count under each node, which nodes are completely occupied)."""
    prefixes, counts = codes, np.ones(len(codes), np.int64)
    levels = [(prefixes, counts, np.ones(len(codes), bool))]
    for level in range(1, DEPTH + 1):
        parents = prefixes >> 3
        starts = np.concatenate([[0], np.flatnonzero(np.diff(parents)) + 1])
        prefixes, counts = parents[starts], np.add.reduceat(counts, starts)
        levels.append((prefixes, counts, counts == (1 << (3 * level))))
    return levels


def _child_states(levels, level):
    """For the nodes of `level`: per-octant state of each child (0 none, 2 solid, 3 has children) as an (N, 8) array."""
    prefixes = levels[level][0]
    children, _, solid = levels[level - 1]
    states = np.zeros((len(prefixes), 8), np.int64)
    states[np.searchsorted(prefixes, children >> 3), children & 7] = np.where(solid, 2, 3)
    return states


def _preorder(parts):
    """Concatenate per-level (aligned code, level, payload) parts into pre-order: by position, parents first."""
    codes = np.concatenate([part[0] for part in parts])
    levels = np.concatenate([part[1] for part in parts])
    payload = np.concatenate([part[2] for part in parts])
    return payload[np.lexsort((-levels, codes))]


def write_bt(path, keys, resolution):
    """Write occupied cells as a binary octree; everything else is left unknown."""
    codes = _codes_from_keys(keys)
    body, count = b"", 0
    if len(codes):
        levels = _levels(codes)
        parts = []
        for level in range(1, DEPTH + 1):
            prefixes, _, solid = levels[level]
            states = _child_states(levels, level)[~solid]
            bits = (states << (2 * np.arange(8))).sum(axis=1)
            parts.append((prefixes[~solid] << (3 * level), np.full(len(bits), level), bits))
            count += len(bits) + int((states == 2).sum())
        body = _preorder(parts).astype("<u2").tobytes()
    _write(path, b"# Octomap OcTree binary file", body, count, resolution)


def write_ot(path, keys, resolution, log_odds=OCCUPIED_LOG_ODDS):
    """Write occupied cells as a full OcTree with a uniform log-odds value."""
    codes = _codes_from_keys(keys)
    body, count = b"", 0
    if len(codes):
        levels = _levels(codes)
        parts = []
        for level in range(DEPTH + 1):
            prefixes, _, solid = levels[level]
            if level == DEPTH:
                emitted = np.ones(len(prefixes), bool)
            else:
                parent_prefixes, _, parent_solid = levels[level + 1]
                emitted = ~parent_solid[np.searchsorted(parent_prefixes, prefixes >> 3)]
            masks = np.zeros(len(prefixes), np.int64)
            if level:
                masks[~solid] = ((_child_states(levels, level)[~solid] > 0) << np.arange(8)).sum(axis=1)
            parts.append((prefixes[emitted] << (3 * level), np.full(int(emitted.sum()), level), masks[emitted]))
        masks = _preorder(parts)
        count = len(masks)
        record = np.zeros(count, np.dtype([("value", "<f4"), ("mask", "u1")]))
        record["value"], record["mask"] = log_odds, masks
        body = record.tobytes()
    _write(path, b"# Octomap OcTree file", body, count, resolution)
