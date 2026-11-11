"""Two-point distance measurement for the 3D views."""
import numpy as np
import vtk

RULER_RGB = (1.0, 0.82, 0.15)


def measure(a, b, cell=None):
    """Distance between two points -> dict with the length, per-axis offsets and the length in cells."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    delta = b - a
    length = float(np.linalg.norm(delta))
    result = {"d": length, "dx": float(delta[0]), "dy": float(delta[1])}
    if len(delta) > 2:
        result["dz"] = float(delta[2])
    if cell:
        result["cells"] = length / cell
    return result


class Ruler3D:
    """A line with end markers and a distance label, drawn in a VTK renderer."""

    def __init__(self, renderer):
        self.renderer = renderer
        self.first = None
        self.second = None
        self.line = vtk.vtkLineSource()
        self.line_actor = self._actor(self.line)
        self.line_actor.GetProperty().SetLineWidth(3.0)
        self.line_actor.GetProperty().LightingOff()
        self.ends = []
        for _ in range(2):
            source = vtk.vtkSphereSource()
            source.SetThetaResolution(16)
            source.SetPhiResolution(12)
            self.ends.append((source, self._actor(source)))
        self.label = vtk.vtkBillboardTextActor3D()
        prop = self.label.GetTextProperty()
        prop.SetFontSize(18)
        prop.SetBold(True)
        prop.SetColor(1.0, 1.0, 1.0)
        prop.SetBackgroundColor(0.08, 0.09, 0.12)
        prop.SetBackgroundOpacity(0.85)
        prop.SetFrame(True)
        prop.SetFrameColor(*RULER_RGB)
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToBottom()
        self.label.PickableOff()
        self.label.VisibilityOff()
        renderer.AddActor(self.label)
        self.marker_size = 0.02

    def _actor(self, source):
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*RULER_RGB)
        actor.GetProperty().SetAmbient(0.6)
        actor.PickableOff()
        actor.VisibilityOff()
        self.renderer.AddActor(actor)
        return actor

    @property
    def pending(self):
        return self.first is not None and self.second is None

    def clear(self):
        self.first = self.second = None
        for actor in [self.line_actor, self.label] + [actor for _, actor in self.ends]:
            actor.VisibilityOff()

    def _draw(self, a, b, text):
        self.line.SetPoint1(*a)
        self.line.SetPoint2(*b)
        for (source, actor), point in zip(self.ends, (a, b)):
            source.SetCenter(*point)
            source.SetRadius(self.marker_size)
            actor.VisibilityOn()
        self.line_actor.VisibilityOn()
        self.label.SetPosition(*((np.asarray(a) + np.asarray(b)) / 2))
        self.label.SetInput(text)
        self.label.VisibilityOn()

    def start(self, point):
        self.first, self.second = np.asarray(point, float), None
        source, actor = self.ends[0]
        source.SetCenter(*self.first)
        source.SetRadius(self.marker_size)
        actor.VisibilityOn()
        for item in (self.line_actor, self.label, self.ends[1][1]):
            item.VisibilityOff()

    def preview(self, point, text):
        if self.pending:
            self._draw(self.first, point, text)

    def finish(self, point, text):
        self.second = np.asarray(point, float)
        self._draw(self.first, self.second, text)
