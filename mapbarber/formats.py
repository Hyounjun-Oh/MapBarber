"""File format registry: decides which editor a file belongs to and reads or writes it."""
import os

import numpy as np

from . import octree
from .safeio import replacing
from .voxels import centers, voxelize

VOXEL, CLOUD, GRID = "voxel", "cloud", "grid"
_EXTENSIONS = {".bt": "bt", ".ot": "ot", ".pcd": "pcd", ".ply": "ply", ".xyz": "xyz", ".txt": "xyz", ".csv": "xyz",
               ".npy": "npy", ".npz": "npz", ".yaml": "yaml", ".yml": "yaml", ".pgm": "pgm", ".png": "png", ".bmp": "bmp"}
OPEN_PATTERNS = " ".join(f"*{ext}" for ext in _EXTENSIONS)
GRID_FORMATS = ("yaml", "pgm", "png", "bmp")
_PLY_TYPES = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2", "int16": "i2", "ushort": "u2",
              "uint16": "u2", "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4", "float": "f4", "float32": "f4",
              "double": "f8", "float64": "f8"}
_PLY_NAMES = {"i1": "char", "u1": "uchar", "i2": "short", "u2": "ushort", "i4": "int", "u4": "uint", "f4": "float",
              "f8": "double"}
_PCD_TYPES = {("F", 4): "f4", ("F", 8): "f8", ("I", 1): "i1", ("I", 2): "i2", ("I", 4): "i4", ("I", 8): "i8",
              ("U", 1): "u1", ("U", 2): "u2", ("U", 4): "u4", ("U", 8): "u8"}
_PCD_KINDS = {"f": "F", "i": "I", "u": "U"}
_PCD_VIEWPOINT = "0 0 0 1 0 0 0"
_RGB = ("red", "green", "blue")


def detect(path):
    """Format name from the file extension, falling back to the file signature."""
    fmt = _EXTENSIONS.get(os.path.splitext(path)[1].lower())
    if fmt or not os.path.isfile(path):
        return fmt
    with open(path, "rb") as f:
        head = f.read(64)
    if head.startswith(b"# Octomap OcTree binary file"):
        return "bt"
    if head.startswith(b"# Octomap OcTree file"):
        return "ot"
    if head.startswith(b"ply"):
        return "ply"
    if head.startswith(b"# .PCD") or head.startswith(b"VERSION"):
        return "pcd"
    if head.startswith(b"\x93NUMPY"):
        return "npy"
    if head[:2] in (b"P5", b"P2"):
        return "pgm"
    return None


def kind(path):
    """Which editor handles this file: VOXEL, CLOUD or GRID."""
    fmt = detect(path)
    if fmt in ("bt", "ot"):
        return VOXEL
    if fmt in GRID_FORMATS:
        return GRID
    if fmt == "npz":
        with np.load(path) as archive:
            return VOXEL if "resolution" in archive else CLOUD
    if fmt in ("pcd", "ply", "xyz", "npy"):
        return CLOUD
    raise ValueError(f"unsupported file format: {path}")


def _columns(table):
    return np.stack([np.asarray(table[axis], np.float64) for axis in "xyz"], axis=1)


def _read_pcd(path):
    with open(path, "rb") as f:
        data = f.read()
    header, pos = {}, 0
    while True:
        end = data.find(b"\n", pos)
        if end < 0:
            raise ValueError("PCD header has no DATA line")
        line = data[pos:end].decode("ascii", errors="replace").strip()
        pos = end + 1
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(" ")
        header[key.upper()] = value.split()
        if key.upper() == "DATA":
            break
    names = [name.lower() for name in header["FIELDS"]]
    sizes = [int(v) for v in header["SIZE"]]
    counts = [int(v) for v in header.get("COUNT", ["1"] * len(names))]
    total = int(header["POINTS"][0]) if "POINTS" in header else int(header["WIDTH"][0]) * int(header["HEIGHT"][0])
    mode = header["DATA"][0].lower()
    if any(axis not in names for axis in "xyz"):
        raise ValueError("PCD file has no x, y, z fields")
    kept = {"viewpoint": " ".join(header.get("VIEWPOINT", _PCD_VIEWPOINT.split())),
            "width": int(header.get("WIDTH", [total])[0]), "height": int(header.get("HEIGHT", ["1"])[0])}
    dtype = np.dtype([(name, _PCD_TYPES[(kind_, size)], (count,)) if count > 1 else (name, _PCD_TYPES[(kind_, size)])
                      for name, kind_, size, count in zip(names, header["TYPE"], sizes, counts)], metadata={"pcd": kept})
    if mode == "binary":
        return np.frombuffer(data, dtype=dtype, count=total, offset=pos).copy()
    if mode == "ascii":
        rows = np.loadtxt(data[pos:].decode("ascii", errors="replace").splitlines(), ndmin=2)
        table = np.zeros(len(rows), dtype)
        column = 0
        for name, count in zip(names, counts):
            table[name] = rows[:, column] if count == 1 else rows[:, column:column + count]
            column += count
        return table
    raise ValueError(f"PCD DATA mode '{mode}' is not supported; convert the file to ascii or binary")


def _read_ply(path):
    with open(path, "rb") as f:
        data = f.read()
    end = data.find(b"end_header")
    if not data.startswith(b"ply") or end < 0:
        raise ValueError("not a PLY file")
    body = data.find(b"\n", end) + 1
    fmt, element, count, props, first, others = None, None, 0, [], True, []
    for line in data[:end].decode("ascii", errors="replace").splitlines():
        words = line.split()
        if not words:
            continue
        if words[0] == "format":
            fmt = words[1]
        elif words[0] == "element":
            element = words[1]
            if element == "vertex":
                count = int(words[2])
            elif first:
                raise ValueError("PLY files must list the vertex element first")
            elif int(words[2]):
                others.append(element)
            first = False
        elif words[0] == "property" and element == "vertex":
            if words[1] == "list":
                raise ValueError("PLY list properties on vertices are not supported")
            props.append((words[2], _PLY_TYPES[words[1]]))
    if any(axis not in [name for name, _ in props] for axis in "xyz"):
        raise ValueError("PLY file has no x, y, z vertex properties")
    native = np.dtype(props, metadata={"ply": {"elements": others}})
    if fmt == "ascii":
        rows = np.loadtxt(data[body:].decode("ascii", errors="replace").splitlines()[:count], ndmin=2)
        table = np.zeros(len(rows), native)
        for column, (name, _) in enumerate(props):
            table[name] = rows[:, column]
        return table
    order = "<" if fmt == "binary_little_endian" else ">"
    table = np.frombuffer(data, dtype=np.dtype([(name, order + code) for name, code in props]), count=count, offset=body)
    return table.astype(native)


def _read_xyz(path):
    """Text points, one per line; three more numbers after x y z are read as an RGB colour."""
    rows, colours = [], []
    with open(path, "r", errors="replace") as f:
        for line in f:
            parts = line.replace(",", " ").replace(";", " ").split()
            if len(parts) < 3:
                continue
            try:
                rows.append([float(v) for v in parts[:3]])
            except ValueError:
                continue
            try:
                colours.append([float(v) for v in parts[3:6]] if len(parts) >= 6 else None)
            except ValueError:
                colours.append(None)
    xyz = np.asarray(rows, np.float64).reshape(-1, 3)
    if not rows or any(c is None for c in colours):
        return xyz, None
    rgb = np.asarray(colours)
    if rgb.min() < 0 or rgb.max() > 255:
        return xyz, None
    table = _xyz_table(xyz)
    coloured = np.zeros(len(xyz), np.dtype(table.dtype.descr + [("red", "u1"), ("green", "u1"), ("blue", "u1")]))
    for name in "xyz":
        coloured[name] = table[name]
    for i, name in enumerate(("red", "green", "blue")):
        coloured[name] = np.round(rgb[:, i] * (255.0 if rgb.max() <= 1.0 else 1.0))
    return xyz, coloured


def read_cloud(path):
    """Point file -> (xyz (N, 3), per-point record array with every field, or None).

    The record array's dtype metadata carries what else the file said: the PCD viewpoint and layout,
    and the names of PLY elements other than the vertices.
    """
    xyz, table = _read_cloud(path)
    if not np.isfinite(xyz).all(axis=1).any():
        raise ValueError("no x, y, z coordinates were found in the file")
    return xyz, table


def _read_cloud(path):
    fmt = detect(path)
    if fmt == "pcd":
        table = _read_pcd(path)
        return _columns(table), table
    if fmt == "ply":
        table = _read_ply(path)
        return _columns(table), table
    if fmt == "xyz":
        return _read_xyz(path)
    if fmt == "npy":
        return np.asarray(np.load(path), np.float64).reshape(-1, 3), None
    if fmt == "npz":
        with np.load(path) as archive:
            name = next((n for n in ("centers", "points", "xyz") if n in archive), archive.files[0])
            return np.asarray(archive[name], np.float64).reshape(-1, 3), None
    raise ValueError(f"not a point file: {path}")


def _xyz_table(xyz):
    table = np.zeros(len(xyz), np.dtype([("x", "f4"), ("y", "f4"), ("z", "f4")]))
    for i, axis in enumerate("xyz"):
        table[axis] = xyz[:, i]
    return table


def cloud_fields(table, fmt):
    """Field names of a record array split into (those the format can store, those it cannot)."""
    if table is None:
        return [], []
    names = list(table.dtype.names)
    if fmt == "pcd":
        return names, []
    if fmt == "ply":
        fits = [name for name in names if not table.dtype[name].shape and table.dtype[name].str[1:] in _PLY_NAMES]
    elif fmt == "xyz":
        fits = [name for name in names if name in "xyz" or name in _RGB] if all(c in names for c in _RGB) else list("xyz")
    else:
        fits = list("xyz")
    return fits, [name for name in names if name not in fits]


def save_cloud(path, xyz, table=None, fmt=None):
    """Write points with every field the format can store. The file is replaced only on success."""
    fmt = fmt or _EXTENSIONS.get(os.path.splitext(path)[1].lower())
    with replacing(path) as part:
        _save_cloud(part, xyz, table, fmt, path)


def _save_cloud(path, xyz, table, fmt, target):
    if fmt in ("pcd", "ply") and table is None:
        table = _xyz_table(xyz)
    if fmt == "pcd":
        names, sizes, kinds, counts = [], [], [], []
        for name in table.dtype.names:
            base, shape = table.dtype[name].base, table.dtype[name].shape
            names.append(name)
            sizes.append(str(base.itemsize))
            kinds.append(_PCD_KINDS[base.kind])
            counts.append(str(int(np.prod(shape)) if shape else 1))
        source = (table.dtype.metadata or {}).get("pcd", {})
        width, height = len(table), 1
        if source.get("height", 1) > 1 and source["width"] * source["height"] == len(table):
            width, height = source["width"], source["height"]
        header = ("# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\n"
                  f"FIELDS {' '.join(names)}\nSIZE {' '.join(sizes)}\nTYPE {' '.join(kinds)}\nCOUNT {' '.join(counts)}\n"
                  f"WIDTH {width}\nHEIGHT {height}\nVIEWPOINT {source.get('viewpoint', _PCD_VIEWPOINT)}\n"
                  f"POINTS {len(table)}\nDATA binary\n")
        with open(path, "wb") as f:
            f.write(header.encode("ascii"))
            f.write(np.ascontiguousarray(table).tobytes())
    elif fmt == "ply":
        fits, _ = cloud_fields(table, fmt)
        little = np.zeros(len(table), np.dtype([(name, "<" + table.dtype[name].str[1:]) for name in fits]))
        for name in fits:
            little[name] = table[name]
        props = "".join(f"property {_PLY_NAMES[table.dtype[name].str[1:]]} {name}\n" for name in fits)
        header = f"ply\nformat binary_little_endian 1.0\nelement vertex {len(table)}\n{props}end_header\n"
        with open(path, "wb") as f:
            f.write(header.encode("ascii"))
            f.write(little.tobytes())
    elif fmt == "xyz":
        columns, layout = xyz, ["%.6f"] * 3
        if len(cloud_fields(table, fmt)[0]) > 3:
            columns = np.column_stack([xyz] + [table[name] for name in _RGB])
            layout += ["%d"] * 3
        np.savetxt(path, columns, fmt=layout, delimiter="," if target.lower().endswith(".csv") else " ")
    elif fmt == "npy":
        with open(path, "wb") as f:
            np.save(f, xyz)
    elif fmt == "npz":
        with open(path, "wb") as f:
            np.savez_compressed(f, points=xyz)
    else:
        raise ValueError(f"unsupported point format: {target}")


def estimate_resolution(points, default=0.05):
    """Grid spacing of points that already sit on a regular grid, else a default."""
    points = np.asarray(points, np.float64).reshape(-1, 3)
    if len(points) < 2:
        return default
    sample = points[:: max(1, len(points) // 200_000)]
    steps = []
    for axis in range(3):
        values = np.unique(np.round(sample[:, axis], 6))
        if len(values) > 1:
            steps.append(float(np.min(np.diff(values))))
    if not steps:
        return default
    step = round(min(steps), 6)
    extent = float(np.ptp(sample, axis=0).max())
    return step if step >= 1e-3 and extent / step <= 4096 else default


def load_voxels(path, resolution=None):
    """Octree, voxel archive or point file -> (occupied keys, resolution)."""
    return read_voxels(path, resolution)[:2]


def read_voxels(path, resolution=None):
    """Like load_voxels, plus what an octree file holds besides the occupied cells (octree.Leaves, or None)."""
    fmt = detect(path)
    if fmt in ("bt", "ot"):
        return octree.read(path, fmt)
    if fmt == "npz":
        with np.load(path) as archive:
            if "resolution" in archive and resolution is None:
                resolution = float(archive["resolution"])
    points, _ = read_cloud(path)
    resolution = resolution or estimate_resolution(points)
    return voxelize(points, resolution), float(resolution), None


def save_voxels(path, keys, resolution, fmt=None, leaves=None):
    """Write occupied cells as an octree, a voxel archive, or their centres as points.

    `leaves` (from read_voxels) lets an octree keep its free space, and a full octree its values and colours.
    """
    fmt = fmt or _EXTENSIONS.get(os.path.splitext(path)[1].lower())
    if fmt == "bt":
        octree.write_bt(path, keys, resolution, leaves)
    elif fmt == "ot":
        octree.write_ot(path, keys, resolution, leaves)
    elif fmt == "npz":
        with replacing(path) as part, open(part, "wb") as f:
            np.savez_compressed(f, centers=centers(keys, resolution), resolution=np.float64(resolution))
    else:
        save_cloud(path, centers(keys, resolution), fmt=fmt)
