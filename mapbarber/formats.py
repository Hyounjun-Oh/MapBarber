"""File format registry: decides which editor a file belongs to and reads or writes it."""
import os

import numpy as np

from . import octree
from .safeio import replacing
from .voxels import centers, voxelize

VOXEL, CLOUD, GRID = "voxel", "cloud", "grid"
_EXTENSIONS = {".bt": "bt", ".ot": "ot", ".pcd": "pcd", ".ply": "ply", ".xyz": "xyz", ".txt": "xyz", ".csv": "xyz",
               ".npy": "npy", ".npz": "npz", ".yaml": "yaml", ".yml": "yaml", ".pgm": "pgm", ".png": "png", ".bmp": "bmp",
               ".bin": "bin", ".las": "las", ".laz": "las"}
FRAMES = "frames"
CLASS_FIELDS = ("label", "labels", "class", "classification", "semantic", "category", "scalar_classification",
                "scalar_label")
INSTANCE_FIELDS = ("instance", "instance_id", "instances", "object", "object_id", "scalar_instance")
LABEL_SUFFIX = ".labels.npz"
OPEN_PATTERNS = " ".join(f"*{ext}" for ext in _EXTENSIONS)
KIND_EXTENSIONS = {"voxel": (".bt", ".ot", ".npz"),
                   "cloud": (".pcd", ".ply", ".las", ".laz", ".bin", ".xyz", ".txt", ".csv", ".npy", ".npz"),
                   "grid": (".yaml", ".yml", ".pgm", ".png", ".bmp")}
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
    """Format name from the file extension, falling back to the file signature; a folder is a set of frames."""
    if os.path.isdir(path):
        return FRAMES
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
    if fmt in ("pcd", "ply", "xyz", "npy", "bin", "las", FRAMES):
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
    with open(path, "r", errors="replace") as f:
        names = f.readline().lstrip("#").replace(",", " ").split() if f.read(1) == "#" else []
    if names[:3] == ["x", "y", "z"] and "label" in names:
        return _read_named_text(path, names)
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


def _read_named_text(path, names):
    """Text points whose header line names the columns, as written for labelled clouds."""
    with open(path, "r", errors="replace") as f:
        rows = np.loadtxt([line.replace(",", " ") for line in f if not line.startswith("#")], ndmin=2)
    if rows.shape[1] < len(names):
        raise ValueError("the text file has fewer columns than its header names")
    kinds = {"x": "f8", "y": "f8", "z": "f8", "red": "u1", "green": "u1", "blue": "u1", "label": "u2", "instance": "u4"}
    table = np.zeros(len(rows), np.dtype([(name, kinds.get(name, "f8")) for name in names]))
    for column, name in enumerate(names):
        table[name] = rows[:, column]
    return _columns(table), table


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
    if fmt == "bin":
        return _read_bin(path)
    if fmt == "las":
        return _read_las(path)
    if fmt == "npy":
        return np.asarray(np.load(path), np.float64).reshape(-1, 3), None
    if fmt == "npz":
        with np.load(path) as archive:
            name = next((n for n in ("centers", "points", "xyz") if n in archive), archive.files[0])
            return np.asarray(archive[name], np.float64).reshape(-1, 3), None
    raise ValueError(f"not a point file: {path}")


def _read_bin(path):
    """Raw float32 scan as written by LiDAR datasets.

    Four numbers per point (x y z intensity) by default; five (x y z intensity ring) for `.pcd.bin`
    files; otherwise whatever record width the file size allows, preferring 4, then 5, then 3.
    """
    raw = np.fromfile(path, np.float32)
    widths = (5, 4, 3) if path.lower().endswith(".pcd.bin") else (4, 5, 3)
    width = next((w for w in widths if raw.size and raw.size % w == 0), 0)
    if not width:
        raise ValueError("the .bin file does not hold whole x y z (intensity) records")
    names = ["x", "y", "z", "intensity", "ring"][:width]
    table = np.zeros(raw.size // width, np.dtype([(name, "f4") for name in names]))
    for column, name in enumerate(names):
        table[name] = raw[column::width]
    return _columns(table), table


_LAS_EXTRA = ("u1", "i1", "u2", "i2", "u4", "i4", "u8", "i8", "f4", "f8")


def _laspy():
    try:
        import laspy
    except ImportError:
        raise ValueError("LAS and LAZ files need the optional 'laspy' package: pip install \"laspy[lazrs]\"") from None
    return laspy


def _read_las(path):
    laspy = _laspy()
    las = laspy.read(path)
    xyz = np.column_stack([np.asarray(las.x, np.float64), np.asarray(las.y, np.float64), np.asarray(las.z, np.float64)])
    fields = [("x", "f8"), ("y", "f8"), ("z", "f8")]
    columns = {}
    for name in las.point_format.dimension_names:
        if name in ("X", "Y", "Z"):
            continue
        values = np.asarray(las[name])
        if values.ndim == 1 and values.dtype.kind in "fiu":
            columns[name] = values
            fields.append((name, values.dtype.str[1:]))
    header = {"version": str(las.header.version), "format": int(las.header.point_format.id),
              "scales": [float(v) for v in las.header.scales], "offsets": [float(v) for v in las.header.offsets]}
    table = np.zeros(len(xyz), np.dtype(fields, metadata={"las": header}))
    for axis, name in enumerate("xyz"):
        table[name] = xyz[:, axis]
    for name, values in columns.items():
        table[name] = values
    return xyz, table


def _save_las(path, xyz, table):
    laspy = _laspy()
    source = ((table.dtype.metadata or {}).get("las") if table is not None else None) or {}
    header = laspy.LasHeader(point_format=source.get("format", 6), version=source.get("version", "1.4"))
    header.scales = np.array(source.get("scales", [0.001] * 3))
    header.offsets = np.array(source.get("offsets", np.floor(xyz.min(axis=0)).tolist() if len(xyz) else [0.0] * 3))
    names = [name for name in (table.dtype.names if table is not None else ()) if name not in ("x", "y", "z")]
    known = set(header.point_format.dimension_names)
    extra = [name for name in names if name not in known and table.dtype[name].str[1:] in _LAS_EXTRA]
    if extra:
        header.add_extra_dims([laspy.ExtraBytesParams(name=name, type=np.dtype(table.dtype[name].str[1:]))
                               for name in extra])
    las = laspy.LasData(header)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    for name in names:
        if name in known or name in extra:
            las[name] = table[name]
    class_field, _ = label_fields(table)
    if class_field is not None and class_field not in known:
        values = np.asarray(table[class_field], np.int64)
        las.classification = np.where(values < 256, values, 1).astype(np.uint8)
    las.write(path)


def label_fields(table):
    """Names of the fields that hold the class and the instance number: (class field or None, instance field or None)."""
    if table is None:
        return None, None
    lowered = {name.lower(): name for name in table.dtype.names if not table.dtype[name].shape}
    return (next((lowered[n] for n in CLASS_FIELDS if n in lowered), None),
            next((lowered[n] for n in INSTANCE_FIELDS if n in lowered), None))


def table_labels(table):
    """(class per point, instance per point) stored in a record array, or (None, None)."""
    class_field, instance_field = label_fields(table)
    cls = None if class_field is None else np.clip(np.nan_to_num(table[class_field]), 0, 65535).astype(np.uint16)
    inst = None if instance_field is None else np.clip(np.nan_to_num(table[instance_field]), 0, 2 ** 32 - 1).astype(np.uint32)
    return cls, inst


def with_labels(xyz, table, cls, inst):
    """Record array carrying the labels: existing label fields are filled in, missing ones are added."""
    if table is None:
        table = _xyz_table(xyz)
    class_field, instance_field = label_fields(table)
    extra = ([("label", "u2")] if class_field is None else []) + \
            ([("instance", "u4")] if instance_field is None and inst is not None and inst.any() else [])
    if extra:
        wider = np.zeros(len(table), np.dtype(table.dtype.descr + extra, metadata=dict(table.dtype.metadata or {})))
        for name in table.dtype.names:
            wider[name] = table[name]
        table = wider
    else:
        table = table.copy()
    class_field, instance_field = label_fields(table)
    table[class_field] = cls
    if instance_field is not None and inst is not None:
        table[instance_field] = inst
    return table


def label_sidecar(path):
    """Where the labels of a file live when they are kept beside it instead of inside it."""
    return path + LABEL_SUFFIX


def read_label_file(path, count=None):
    """Labels from a SemanticKITTI .label file, a MapBarber sidecar, a NumPy array or a text column -> (cls, inst)."""
    lowered = path.lower()
    if lowered.endswith(".label"):
        packed = np.fromfile(path, np.uint32)
        cls, inst = (packed & 0xFFFF).astype(np.uint16), (packed >> 16).astype(np.uint32)
    elif lowered.endswith(".npz"):
        with np.load(path) as archive:
            cls = np.asarray(archive["cls" if "cls" in archive else archive.files[0]]).astype(np.uint16).ravel()
            inst = np.asarray(archive["inst"]).astype(np.uint32).ravel() if "inst" in archive else np.zeros(len(cls), np.uint32)
    elif lowered.endswith(".npy"):
        cls = np.asarray(np.load(path)).astype(np.uint16).ravel()
        inst = np.zeros(len(cls), np.uint32)
    else:
        cls = np.loadtxt(path, ndmin=1).astype(np.uint16).ravel()
        inst = np.zeros(len(cls), np.uint32)
    if count is not None and len(cls) != count:
        raise ValueError(f"the label file holds {len(cls)} labels but the cloud has {count} points")
    return cls, inst


def write_label_file(path, cls, inst=None):
    """Write labels as a SemanticKITTI .label file or, for any other name, a MapBarber sidecar archive."""
    inst = np.zeros(len(cls), np.uint32) if inst is None else inst
    with replacing(path) as part:
        if path.lower().endswith(".label"):
            (np.asarray(cls, np.uint32) | (np.asarray(inst, np.uint32) << 16)).astype("<u4").tofile(part)
        else:
            with open(part, "wb") as f:
                np.savez_compressed(f, cls=np.asarray(cls, np.uint16), inst=np.asarray(inst, np.uint32))


def write_voxel_labels(path, keys, cls):
    """Classes of voxels, kept beside a voxel map file."""
    with replacing(path) as part, open(part, "wb") as f:
        np.savez_compressed(f, keys=np.asarray(keys, np.int64), cls=np.asarray(cls, np.uint16))


def read_voxel_labels(path):
    """(keys, classes) written by write_voxel_labels, or None when the file holds labels of points instead."""
    with np.load(path) as archive:
        if "keys" not in archive:
            return None
        return np.asarray(archive["keys"], np.int64), np.asarray(archive["cls"], np.uint16)


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
    if fmt == "las":
        fits = [name for name in names if not table.dtype[name].shape and table.dtype[name].str[1:] in _LAS_EXTRA]
        return fits, [name for name in names if name not in fits]
    if fmt == "bin":
        fits = [name for name in ("x", "y", "z", "intensity") if name in names]
    elif fmt == "ply":
        fits = [name for name in names if not table.dtype[name].shape and table.dtype[name].str[1:] in _PLY_NAMES]
    elif fmt == "xyz":
        fits = list("xyz") + (list(_RGB) if all(c in names for c in _RGB) else []) + \
               [name for name in ("label", "instance") if name in names]
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
        extra = cloud_fields(table, fmt)[0][3:]
        columns = np.column_stack([xyz] + [table[name] for name in extra]) if extra else xyz
        named = "label" in extra
        np.savetxt(path, columns, fmt=["%.6f"] * 3 + ["%d"] * len(extra), comments="# ",
                   header=" ".join(["x", "y", "z"] + extra) if named else "",
                   delimiter="," if target.lower().endswith(".csv") and not named else " ")
    elif fmt == "bin":
        columns = [xyz] + ([table["intensity"]] if table is not None and "intensity" in table.dtype.names else
                           [np.zeros(len(xyz))])
        np.column_stack(columns).astype("<f4").tofile(path)
    elif fmt == "las":
        _save_las(path, xyz, table)
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
