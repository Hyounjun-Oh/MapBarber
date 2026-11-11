"""VTK viewport shared by the voxel and point cloud editors."""
import numpy as np
import vtk

from .qt import QtCore, QtGui, QVTKRenderWindowInteractor

Qt = QtCore.Qt
CLICK_SLOP = 3
VIEWS = (("top", (0, 0, 1), (0, 1, 0)), ("front", (1, 0, 0), (0, 0, 1)), ("side", (0, -1, 0), (0, 0, 1)),
         ("iso", (1, -1, 0.8), (0, 0, 1)))
HEIGHT_RAMP = np.array([[59, 76, 192], [51, 153, 230], [38, 204, 178], [120, 220, 80], [240, 215, 50], [245, 130, 40],
                        [200, 40, 30]], np.float64)


def ramp(values, low, high):
    t = np.clip((values - low) / max(high - low, 1e-9), 0.0, 1.0) * (len(HEIGHT_RAMP) - 1)
    i = np.minimum(t.astype(np.int64), len(HEIGHT_RAMP) - 2)
    f = (t - i)[:, None]
    return (HEIGHT_RAMP[i] * (1 - f) + HEIGHT_RAMP[i + 1] * f).astype(np.uint8)


class Viewport:
    """Render window with trackball navigation, click and hover callbacks, and Shift-drag rectangles."""

    def __init__(self, parent, on_click, on_hover, on_rectangle):
        self.widget = QVTKRenderWindowInteractor(parent)
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.10, 0.11, 0.13)
        self.widget.GetRenderWindow().AddRenderer(self.renderer)
        self.interactor = self.widget.GetRenderWindow().GetInteractor()
        self.on_click, self.on_hover, self.on_rectangle = on_click, on_hover, on_rectangle
        self.axes = vtk.vtkAxesActor()
        self.axes.AxisLabelsOff()
        self.renderer.AddActor(self.axes)
        self._press = None
        self._band = None
        self._initialized = False

        corners = vtk.vtkPoints()
        corners.SetNumberOfPoints(4)
        loop = vtk.vtkCellArray()
        loop.InsertNextCell(5)
        for i in (0, 1, 2, 3, 0):
            loop.InsertCellPoint(i)
        self.band_shape = vtk.vtkPolyData()
        self.band_shape.SetPoints(corners)
        self.band_shape.SetLines(loop)
        band_mapper = vtk.vtkPolyDataMapper2D()
        band_mapper.SetInputData(self.band_shape)
        self.band_actor = vtk.vtkActor2D()
        self.band_actor.SetMapper(band_mapper)
        self.band_actor.GetProperty().SetColor(1.0, 1.0, 0.2)
        self.band_actor.GetProperty().SetLineWidth(1.5)
        self.band_actor.VisibilityOff()
        self.renderer.AddViewProp(self.band_actor)

        # Observers on the style replace its default handlers, so each one forwards explicitly.
        self.style = vtk.vtkInteractorStyleTrackballCamera()
        self.interactor.SetInteractorStyle(self.style)
        self.style.AddObserver("LeftButtonPressEvent", self._on_press)
        self.style.AddObserver("LeftButtonReleaseEvent", self._on_release)
        self.style.AddObserver("MouseMoveEvent", self._on_move)
        self.style.AddObserver("CharEvent", lambda *_: None)

    def initialize(self):
        if not self._initialized:
            self.interactor.Initialize()
            self._initialized = True

    def outline(self, rgb, width=2.0):
        source = vtk.vtkOutlineSource()
        actor = self._actor(source, rgb, width)
        return source, actor

    def wire_sphere(self, rgb):
        source = vtk.vtkSphereSource()
        source.SetThetaResolution(16)
        source.SetPhiResolution(10)
        actor = self._actor(source, rgb, 1.0)
        actor.GetProperty().SetRepresentationToWireframe()
        return source, actor

    def _actor(self, source, rgb, width):
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*rgb)
        actor.GetProperty().SetLineWidth(width)
        actor.GetProperty().LightingOff()
        actor.VisibilityOff()
        self.renderer.AddActor(actor)
        return actor

    def render(self):
        self.renderer.ResetCameraClippingRange()
        self.widget.GetRenderWindow().Render()

    def set_axes_length(self, length):
        self.axes.SetTotalLength(length, length, length)

    def look_from(self, direction, up, bounds):
        center = np.array([(bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2])
        direction = np.asarray(direction, float)
        camera = self.renderer.GetActiveCamera()
        camera.SetFocalPoint(*center)
        camera.SetPosition(*(center + direction / np.linalg.norm(direction)))
        camera.SetViewUp(*up)
        self.renderer.ResetCamera(*bounds)
        self.render()

    def ray(self, x, y):
        def unproject(depth):
            self.renderer.SetDisplayPoint(x, y, depth)
            self.renderer.DisplayToWorld()
            point = np.array(self.renderer.GetWorldPoint())
            return point[:3] / point[3]
        near, far = unproject(0.0), unproject(1.0)
        direction = far - near
        return near, direction / np.linalg.norm(direction)

    def pixel_angle(self):
        """Angle in radians covered by one screen pixel at the centre of the view."""
        height = max(self.renderer.GetSize()[1], 1)
        return np.radians(self.renderer.GetActiveCamera().GetViewAngle()) / height

    def rectangle_hits(self, points, corner_a, corner_b, front_only, tolerance):
        """Indices of points that project into a screen rectangle, optionally only the front layer."""
        if not len(points):
            return np.zeros(0, np.int64)
        width, height = self.renderer.GetSize()
        camera = self.renderer.GetActiveCamera()
        matrix = camera.GetCompositeProjectionTransformMatrix(self.renderer.GetTiledAspectRatio(), -1, 1)
        m = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])
        clip = points @ m[:3, :3].T + m[:3, 3]
        w = points @ m[3, :3] + m[3, 3]
        ahead = w > 1e-9
        safe = np.where(ahead, w, 1.0)
        sx = (clip[:, 0] / safe + 1) / 2 * width
        sy = (clip[:, 1] / safe + 1) / 2 * height
        x0, x1 = sorted((corner_a[0], corner_b[0]))
        y0, y1 = sorted((corner_a[1], corner_b[1]))
        chosen = np.flatnonzero(ahead & (sx >= x0) & (sx <= x1) & (sy >= y0) & (sy <= y1))
        if front_only and len(chosen):
            # Keep only points close to the nearest one in each small screen tile.
            eye, forward = np.array(camera.GetPosition()), np.array(camera.GetDirectionOfProjection())
            depth = (points[chosen] - eye) @ forward
            tile = (sx[chosen] // 8).astype(np.int64) * 100_000 + (sy[chosen] // 8).astype(np.int64)
            _, inverse = np.unique(tile, return_inverse=True)
            nearest = np.full(int(inverse.max()) + 1, np.inf)
            np.minimum.at(nearest, inverse, depth)
            chosen = chosen[depth <= nearest[inverse] + tolerance]
        return chosen

    def capture(self):
        """Current frame as a QImage."""
        grabber = vtk.vtkWindowToImageFilter()
        grabber.SetInput(self.widget.GetRenderWindow())
        grabber.ReadFrontBufferOff()
        grabber.Update()
        image = grabber.GetOutput()
        width, height, _ = image.GetDimensions()
        from vtk.util import numpy_support
        pixels = numpy_support.vtk_to_numpy(image.GetPointData().GetScalars()).reshape(height, width, -1)[::-1, :, :3]
        pixels = np.ascontiguousarray(pixels)
        return QtGui.QImage(pixels.tobytes(), width, height, 3 * width, QtGui.QImage.Format_RGB888).copy()

    def _on_press(self, *_):
        x, y = self.interactor.GetEventPosition()
        self._press = (x, y)
        if self.interactor.GetShiftKey():
            self._band = (x, y)
        else:
            self.style.OnLeftButtonDown()

    def _on_move(self, *_):
        x, y = self.interactor.GetEventPosition()
        if self._band is not None:
            x0, y0 = self._band
            corners = self.band_shape.GetPoints()
            for i, (px, py) in enumerate(((x0, y0), (x, y0), (x, y), (x0, y))):
                corners.SetPoint(i, px, py, 0)
            corners.Modified()
            self.band_actor.VisibilityOn()
            self.render()
            return
        self.style.OnMouseMove()
        if self._press is None:
            self.on_hover(x, y)

    def _on_release(self, *_):
        x, y = self.interactor.GetEventPosition()
        press, self._press = self._press, None
        ctrl = bool(self.interactor.GetControlKey())
        if self._band is not None:
            start, self._band = self._band, None
            self.band_actor.VisibilityOff()
            if abs(x - start[0]) > CLICK_SLOP and abs(y - start[1]) > CLICK_SLOP:
                self.on_rectangle(start, (x, y), ctrl)
            else:
                self.render()
            return
        self.style.OnLeftButtonUp()
        if press is not None and abs(x - press[0]) <= CLICK_SLOP and abs(y - press[1]) <= CLICK_SLOP:
            self.on_click(x, y, ctrl)
