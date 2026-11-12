"""What a save would leave out, so that it can be said before the file is written."""
from . import formats
from .formats import CLOUD, VOXEL

FREE_SPACE, VALUES, COLOURS, FIELDS, ELEMENTS = "free_space", "values", "colours", "fields", "elements"


def voxel_losses(leaves, fmt):
    """[(what, detail)] for a voxel map read from an octree and written as `fmt`."""
    if leaves is None or fmt == "ot":
        return []
    out = [(FREE_SPACE, "")] if fmt != "bt" and leaves.free.any() else []
    if leaves.graded:
        out.append((VALUES, ""))
    if leaves.colours is not None:
        out.append((COLOURS, ""))
    return out


def cloud_losses(table, fmt):
    """[(what, detail)] for a point cloud with per-point fields written as `fmt`."""
    if table is None:
        return []
    dropped = formats.cloud_fields(table, fmt)[1]
    out = [(FIELDS, ", ".join(dropped))] if dropped else []
    elements = ((table.dtype.metadata or {}).get("ply") or {}).get("elements")
    if elements:
        out.append((ELEMENTS, ", ".join(elements)))
    return out


def describe(losses, translate):
    return [translate(f"loss_{what}", detail=detail) for what, detail in losses]


def of(kind, payload, fmt):
    """Losses for the payloads the command line passes around."""
    if kind == VOXEL:
        return voxel_losses(payload[2] if len(payload) > 2 else None, fmt)
    if kind == CLOUD:
        return cloud_losses(payload[1], fmt)
    return []
