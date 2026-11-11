"""Draws a chunked voxel map: one actor per chunk, coarser cubes for chunks far from the camera."""
import numpy as np
import vtk
from vtk.util import numpy_support

from .scene import ramp

MAX_LEVEL = 4
MIN_PIXELS = 1.3
NORMAL, ADDED, SELECTED = 0, 1, 2
FLAG_RGB = {ADDED: np.array([245, 245, 245], np.uint8), SELECTED: np.array([255, 40, 200], np.uint8)}


def coarsen(cells, flags, level):
    """Merge cells into blocks of 2**level; a block takes the strongest flag of its cells."""
    if level == 0 or not len(cells):
        return cells, flags
    blocks = cells >> level
    low = blocks.min(axis=0)
    span = blocks.max(axis=0) - low + 1
    code = ((blocks[:, 0] - low[0]) * span[1] + (blocks[:, 1] - low[1])) * span[2] + (blocks[:, 2] - low[2])
    order = np.argsort(code, kind="stable")
    code = code[order]
    starts = np.concatenate([[0], np.flatnonzero(np.diff(code)) + 1])
    return blocks[order[starts]] << level, np.maximum.reduceat(flags[order], starts)


class ChunkView:
    """Keeps one actor per chunk and detail level; levels built once are kept so switching back is instant."""

    def __init__(self, renderer):
        self.renderer = renderer
        self.resolution = 0.05
        self.height_range = (0.0, 1.0)
        self.cubes = [vtk.vtkCubeSource() for _ in range(MAX_LEVEL + 1)]
        self.actors = {}
        self.levels = {}
        self.cached = 0
        self.set_resolution(self.resolution)

    def set_resolution(self, resolution):
        self.resolution = resolution
        for level, cube in enumerate(self.cubes):
            edge = resolution * (1 << level) * 0.94
            cube.SetXLength(edge)
            cube.SetYLength(edge)
            cube.SetZLength(edge)

    def clear(self):
        for chunk_key in list(self.actors):
            self.forget(chunk_key)

    def forget(self, chunk_key):
        """Drop every cached level of a chunk (its content changed or it is gone)."""
        for data, actor in self.actors.pop(chunk_key, {}).values():
            self.cached -= data.GetNumberOfPoints()
            self.renderer.RemoveActor(actor)
        self.levels.pop(chunk_key, None)

    def drawn(self):
        """Number of cubes currently visible."""
        return sum(self.actors[chunk][level][0].GetNumberOfPoints() for chunk, level in self.levels.items())

    def has(self, chunk_key, level):
        return level in self.actors.get(chunk_key, {})

    def show(self, chunk_key, level):
        """Make a cached level of a chunk the visible one."""
        for other, (_, actor) in self.actors[chunk_key].items():
            actor.SetVisibility(other == level)
        self.levels[chunk_key] = level

    def trim(self, limit):
        """Free cached levels that are not on screen once the cache holds more than `limit` cubes."""
        if self.cached <= limit:
            return
        for chunk_key, by_level in self.actors.items():
            for level in [level for level in by_level if level != self.levels.get(chunk_key)]:
                data, actor = by_level.pop(level)
                self.cached -= data.GetNumberOfPoints()
                self.renderer.RemoveActor(actor)
            if self.cached <= limit:
                return

    def level_for(self, centres, radius, eye, pixel_angle):
        """Detail level per chunk so that one drawn cube covers at least about a pixel."""
        distance = np.maximum(np.linalg.norm(centres - eye, axis=1) - radius, 1e-6)
        pixels = self.resolution / (distance * max(pixel_angle, 1e-9))
        level = np.ceil(np.log2(MIN_PIXELS / np.maximum(pixels, 1e-12)))
        return np.clip(level, 0, MAX_LEVEL).astype(np.int64)

    def build(self, chunk_key, cells, flags, level):
        """Create the actor for one level of a chunk from its visible cells (N, 3) and per-cell flags, and show it."""
        if not len(cells):
            self.forget(chunk_key)
            return
        cells, flags = coarsen(cells, flags, level)
        centres = (cells + (1 << level) / 2.0) * self.resolution
        colours = ramp(centres[:, 2], *self.height_range)
        for flag, rgb in FLAG_RGB.items():
            colours[flags == flag] = rgb
        data = vtk.vtkPolyData()
        points = vtk.vtkPoints()
        points.SetData(numpy_support.numpy_to_vtk(np.ascontiguousarray(centres, np.float32), deep=True))
        data.SetPoints(points)
        array = numpy_support.numpy_to_vtk(np.ascontiguousarray(colours), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        array.SetName("rgb")
        data.GetPointData().SetScalars(array)
        mapper = vtk.vtkGlyph3DMapper()
        mapper.SetInputData(data)
        mapper.SetSourceConnection(self.cubes[level].GetOutputPort())
        mapper.ScalingOff()
        mapper.OrientOff()
        mapper.SetScalarModeToUsePointData()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetAmbient(0.35)
        actor.GetProperty().SetDiffuse(0.75)
        self.renderer.AddActor(actor)
        by_level = self.actors.setdefault(chunk_key, {})
        if level in by_level:
            self.cached -= by_level[level][0].GetNumberOfPoints()
            self.renderer.RemoveActor(by_level[level][1])
        by_level[level] = (data, actor)
        self.cached += len(centres)
        self.show(chunk_key, level)
