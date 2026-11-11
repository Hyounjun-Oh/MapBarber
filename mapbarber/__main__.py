"""Command line entry point: open the editor, or inspect, clean and convert maps without a window."""
import argparse
import os
import sys

import numpy as np

from . import __version__, cloud, convert, formats, grid
from .formats import CLOUD, GRID, VOXEL
from .i18n import LANGUAGES
from .voxels import VoxelMap, unpack

_OUTPUT_KINDS = {"bt": VOXEL, "ot": VOXEL, "yaml": GRID, "pgm": GRID, "png": GRID, "bmp": GRID,
                 "pcd": CLOUD, "ply": CLOUD, "xyz": CLOUD, "npy": CLOUD}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mapbarber",
        description="Editor for robot maps: OctoMap octrees, point clouds and 2D occupancy grids. "
                    "Without --output or --info it opens the graphical editor.")
    parser.add_argument("map", nargs="*", help="files to open, each in its own tab; the type is detected automatically")
    parser.add_argument("-l", "--language", choices=sorted(LANGUAGES), help="interface language")
    parser.add_argument("--info", action="store_true", help="print a summary and exit")
    parser.add_argument("-o", "--output", help="write the (cleaned or converted) map here and exit; "
                                               "the extension picks the output type")
    cleaning = parser.add_argument_group("cleaning, applied before writing")
    cleaning.add_argument("--remove-islands", type=int, metavar="N", help="voxel maps: drop groups of at most N voxels")
    cleaning.add_argument("--clear-speckles", type=int, metavar="N", help="2D grids: free occupied blobs of at most N cells")
    cleaning.add_argument("--remove-outliers", type=float, nargs=2, metavar=("K", "RATIO"),
                          help="point clouds: statistical outlier removal with K neighbours")
    conversion = parser.add_argument_group("conversion between map types")
    conversion.add_argument("-r", "--resolution", type=float, help="voxel size [m] when points become voxels")
    conversion.add_argument("--z-band", type=float, nargs=2, metavar=("LOW", "HIGH"),
                            help="height band [m] projected when making a 2D grid")
    conversion.add_argument("--empty-free", action="store_true",
                            help="when making a 2D grid from 3D data, mark cells without obstacles free instead of unknown")
    conversion.add_argument("--wall-height", type=float, default=1.0, help="wall height [m] when a 2D grid becomes 3D")
    parser.add_argument("--version", action="version", version=f"mapbarber {__version__}")
    return parser


def load(path):
    kind = formats.kind(path)
    if kind == VOXEL:
        return kind, formats.load_voxels(path)
    if kind == CLOUD:
        return kind, formats.read_cloud(path)
    return kind, grid.load(path)


def describe(kind, payload):
    if kind == VOXEL:
        keys, resolution = payload
        lines = [("type", "voxel map"), ("voxel size", f"{resolution:g} m"), ("voxels", len(keys))]
        if len(keys):
            cells = unpack(keys)
            low, high = cells.min(axis=0) * resolution, (cells.max(axis=0) + 1) * resolution
            lines += [(f"{a} range", f"{lo:+.3f} .. {hi:+.3f} m") for a, lo, hi in zip("xyz", low, high)]
    elif kind == CLOUD:
        xyz, table = payload
        finite = xyz[np.all(np.isfinite(xyz), axis=1)]
        lines = [("type", "point cloud"), ("points", len(finite))]
        if table is not None:
            lines.append(("fields", " ".join(table.dtype.names)))
        if len(finite):
            lines += [(f"{a} range", f"{lo:+.3f} .. {hi:+.3f} m") for a, lo, hi in zip("xyz", finite.min(0), finite.max(0))]
    else:
        counts = payload.counts()
        lines = [("type", "2D occupancy grid"), ("size", f"{payload.shape[1]} x {payload.shape[0]} cells"),
                 ("resolution", f"{payload.resolution:g} m/cell"), ("origin", ", ".join(f"{v:g}" for v in payload.origin)),
                 ("occupied", counts[grid.OCCUPIED]), ("free", counts[grid.FREE]), ("unknown", counts[grid.UNKNOWN])]
    return "\n".join(f"{name:<12}{value}" for name, value in lines)


def clean(kind, payload, args):
    if kind == VOXEL and args.remove_islands:
        vmap = VoxelMap(*payload)
        islands, count = vmap.islands(args.remove_islands)
        vmap.apply(remove=islands)
        print(f"removed {len(islands)} voxels in {count} islands")
        return vmap.occupied, vmap.resolution
    if kind == GRID and args.clear_speckles:
        cells, groups = payload.clear_speckles(args.clear_speckles)
        print(f"cleared {cells} cells in {groups} speckles")
    if kind == CLOUD and args.remove_outliers:
        xyz, table = payload
        finite = np.all(np.isfinite(xyz), axis=1)
        xyz, table = xyz[finite], (None if table is None else table[finite])
        neighbours, ratio = int(args.remove_outliers[0]), args.remove_outliers[1]
        drop = cloud.statistical_outliers(xyz, neighbours, ratio)
        keep = np.setdiff1d(np.arange(len(xyz)), drop)
        print(f"removed {len(drop)} outlier points")
        return xyz[keep], (None if table is None else table[keep])
    return payload


def to_voxels(kind, payload, args):
    if kind == VOXEL:
        return payload
    if kind == GRID:
        return convert.grid_to_voxels(payload, args.wall_height)
    xyz, _ = payload
    resolution = formats.estimate_resolution(xyz) if args.resolution is None else args.resolution
    return convert.points_to_voxels(xyz, resolution), resolution


def write(path, kind, payload, args):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    target = _OUTPUT_KINDS.get(ext, kind if ext == "npz" else None)
    if target is None:
        raise SystemExit(f"mapbarber: unsupported output type: {path}")
    if target == kind == CLOUD:
        formats.save_cloud(path, *payload)
    elif target == kind == GRID:
        grid.save(path, payload)
    elif target == GRID:
        keys, resolution = to_voxels(kind, payload, args)
        band = sorted(args.z_band) if args.z_band else (-np.inf, np.inf)
        grid.save(path, convert.voxels_to_grid(keys, resolution, *band, grid.FREE if args.empty_free else grid.UNKNOWN))
    elif target == CLOUD and kind == VOXEL:
        formats.save_voxels(path, *payload)
    elif target == CLOUD:
        formats.save_voxels(path, *to_voxels(kind, payload, args))
    else:
        formats.save_voxels(path, *to_voxels(kind, payload, args))
    print(f"wrote {path}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    headless = args.output or args.info
    if not headless:
        if args.remove_islands or args.clear_speckles or args.remove_outliers:
            parser.error("cleaning options need --output")
        from .app import main as run_editor
        return run_editor(args.map, args.language)
    if len(args.map) != 1:
        parser.error("--output and --info need exactly one input file")
    args.map = args.map[0]
    try:
        kind, payload = load(args.map)
    except (OSError, ValueError) as error:
        print(f"mapbarber: cannot open {args.map}: {error}", file=sys.stderr)
        return 1
    if args.info:
        print(describe(kind, payload))
    try:
        payload = clean(kind, payload, args)
        if args.output:
            write(args.output, kind, payload, args)
    except (OSError, ValueError) as error:
        print(f"mapbarber: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
