"""OctoMap-compatible octree files (.bt binary, .ot full), handled as a linear octree.

Cells are kept as a sorted array of Morton codes, so every tree node is a contiguous
slice of that array and no pointer tree is ever built.
"""
import struct

import numpy as np

from .voxels import DEPTH, EMPTY, OFFSET, pack, unpack

OCCUPIED_LOG_ODDS = 3.5
MAX_EXPANDED_CELLS = 50_000_000

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


def _keys_from_blocks(blocks):
    """Blocks as (first code, level) -> keys of every cell they cover."""
    if not blocks:
        return EMPTY
    blocks = np.asarray(blocks, np.int64)
    spans = np.int64(1) << (3 * blocks[:, 1])
    if int(spans.sum()) > MAX_EXPANDED_CELLS:
        raise ValueError("occupied volume is too large to edit at this resolution")
    codes = np.repeat(blocks[:, 0], spans) + (np.arange(int(spans.sum())) - np.repeat(np.cumsum(spans) - spans, spans))
    return np.unique(pack(morton_decode(codes) - OFFSET))


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
    blocks = []
    pending = [(0, DEPTH)] if pos + 2 <= len(data) else []
    while pending:
        base, level = pending.pop()
        states = data[pos] | (data[pos + 1] << 8)
        pos += 2
        span = 1 << (3 * (level - 1))
        inner = []
        for octant in range(8):
            state = (states >> (2 * octant)) & 3
            if state == 2:
                blocks.append((base + octant * span, level - 1))
            elif state == 3:
                inner.append((base + octant * span, level - 1))
        pending.extend(reversed(inner))
    return _keys_from_blocks(blocks), float(fields["res"])


def _read_ot(path):
    with open(path, "rb") as f:
        data = f.read()
    fields, pos = _parse_header(data)
    tree_id = fields.get("id", "OcTree")
    if tree_id not in _NODE_PAYLOAD:
        raise ValueError(f"unsupported octree type: {tree_id}")
    record = 4 + _NODE_PAYLOAD[tree_id]
    value_at = struct.Struct("<f").unpack_from
    blocks = []
    pending = [(0, DEPTH)] if pos + record < len(data) else []
    while pending:
        base, level = pending.pop()
        value = value_at(data, pos)[0]
        octants = data[pos + record]
        pos += record + 1
        if octants == 0:
            if value > 0.0:
                blocks.append((base, level))
            continue
        span = 1 << (3 * (level - 1))
        pending.extend((base + octant * span, level - 1) for octant in range(7, -1, -1) if octants & (1 << octant))
    return _keys_from_blocks(blocks), float(fields["res"])


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
    with open(path, "wb") as f:
        f.write(magic + b"\n# (written by MapBarber)\n")
        f.write(f"id OcTree\nsize {count}\nres {resolution:g}\ndata\n".encode())
        f.write(body)


def write_bt(path, keys, resolution):
    """Write occupied cells as a binary octree; everything else is left unknown."""
    codes = _codes_from_keys(keys)
    body = bytearray()
    count = 0
    pending = [(0, len(codes), DEPTH)] if len(codes) else []
    while pending:
        low, high, level = pending.pop()
        count += 1
        states = 0
        inner = []
        for octant, a, b, solid in _octants(codes, low, high, level):
            if solid:
                states |= 2 << (2 * octant)
                count += 1
            else:
                states |= 3 << (2 * octant)
                inner.append((a, b, level - 1))
        body += bytes((states & 0xFF, states >> 8))
        pending.extend(reversed(inner))
    _write(path, b"# Octomap OcTree binary file", body, count, resolution)


def write_ot(path, keys, resolution, log_odds=OCCUPIED_LOG_ODDS):
    """Write occupied cells as a full OcTree with a uniform log-odds value."""
    codes = _codes_from_keys(keys)
    value = struct.pack("<f", log_odds)
    body = bytearray()
    count = 0
    pending = [(0, len(codes), DEPTH, False)] if len(codes) else []
    while pending:
        low, high, level, solid = pending.pop()
        count += 1
        body += value
        if solid:
            body.append(0)
            continue
        children = list(_octants(codes, low, high, level))
        body.append(sum(1 << octant for octant, *_ in children))
        pending.extend((a, b, level - 1, full) for _, a, b, full in reversed(children))
    _write(path, b"# Octomap OcTree file", body, count, resolution)
