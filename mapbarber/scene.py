"""VTK viewport shared by the voxel and point cloud editors."""
import numpy as np
import vtk

from .qt import QtCore, QtGui, QVTKRenderWindowInteractor

Qt = QtCore.Qt
CLICK_SLOP = 3
VIEWS = (("top", (0, 0, 1), (0, 1, 0), ["7", "Num+7"]), ("front", (1, 0, 0), (0, 0, 1), ["1", "Num+1"]),
         ("side", (0, -1, 0), (0, 0, 1), ["3", "Num+3"]), ("iso", (1, -1, 0.8), (0, 0, 1), ["Home", "0", "Num+0"]))
HEIGHT_RAMP = np.array([[59, 76, 192], [51, 153, 230], [38, 204, 178], [120, 220, 80], [240, 215, 50], [245, 130, 40],
                        [200, 40, 30]], np.float64)


def ramp(values, low, high):
    t = np.clip((values - low) / max(high - low, 1e-9), 0.0, 1.0) * (len(HEIGHT_RAMP) - 1)
    i = np.minimum(t.astype(np.int64), len(HEIGHT_RAMP) - 2)
    f = (t - i)[:, None]
    return (HEIGHT_RAMP[i] * (1 - f) + HEIGHT_RAMP[i + 1] * f).astype(np.uint8)


class Viewport:
    """Render window with trackball navigation, click and hover callbacks, and Shift-drag rectangles."""

    def __init__(self, parent, on_click, on_hover, on_rectangle, on_right_click=None):
        self.widget = QVTKRenderWindowInteractor(parent)
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.10, 0.11, 0.13)
        self.widget.GetRenderWindow().AddRenderer(self.renderer)
        self.interactor = self.widget.GetRenderWindow().GetInteractor()
        self.on_click, self.on_hover, self.on_rectangle = on_click, on_hover, on_rectangle
        self.on_right_click = on_right_click
        self.gizmos = []
        self.band_allowed = lambda: True
        self.paint_allowed = lambda: False
        self.on_paint = None
        self.on_paint_end = None
        self._painting = False
        self._space = False
        self._panning = False
        self.default_cursor = Qt.ArrowCursor
        self._gizmo = None
        self._right = None
        self._band_subtract = False
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
        self.style.AddObserver("RightButtonPressEvent", self._on_right_press)
        self.style.AddObserver("RightButtonReleaseEvent", self._on_right_release)
        self.style.AddObserver("CharEvent", lambda *_: None)
        self.style.AddObserver("KeyPressEvent", lambda *_: self._key(True))
        self.style.AddObserver("KeyReleaseEvent", lambda *_: self._key(False))

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

    def _key(self, down):
        if self.interactor.GetKeySym() == "space":
            self._space = down
            self.widget.setCursor(Qt.OpenHandCursor if down else self.default_cursor)

    def zoom(self, factor):
        camera = self.renderer.GetActiveCamera()
        if camera.GetParallelProjection():
            camera.SetParallelScale(camera.GetParallelScale() / factor)
        else:
            camera.Dolly(factor)
        self.render()

    def to_display(self, world):
        self.renderer.SetWorldPoint(world[0], world[1], world[2], 1.0)
        self.renderer.WorldToDisplay()
        return self.renderer.GetDisplayPoint()[:2]

    def set_default_cursor(self, cursor):
        self.default_cursor = cursor
        self.widget.setCursor(cursor)

    def _gizmo_at(self, x, y):
        for gizmo in self.gizmos:
            handle = gizmo.hit(x, y)
            if handle is not None:
                return gizmo, handle
        return None, None

    def ray(self, x, y):
        def unproject(depth):
            self.renderer.SetDisplayPoint(x, y, depth)
            self.renderer.DisplayToWorld()
            point = np.array(self.renderer.GetWorldPoint())
            return point[:3] / point[3]
        near, far = unproject(0.0), unproject(1.0)
        direction = far - near
        return near, direction / np.linalg.norm(direction)

    def eye_ray(self, x, y):
        """Ray from the camera eye through a screen position (for angular picking)."""
        camera = self.renderer.GetActiveCamera()
        near, direction = self.ray(x, y)
        if camera.GetParallelProjection():
            return near, direction
        eye = np.array(camera.GetPosition())
        through = near - eye
        return eye, through / np.linalg.norm(through)

    def pixel_angle(self):
        """Angle in radians covered by one screen pixel at the centre of the view."""
        height = max(self.renderer.GetSize()[1], 1)
        return np.radians(self.renderer.GetActiveCamera().GetViewAngle()) / height

    def project(self, points):
        """World points (N, 3) -> (screen x, screen y, in front of the camera)."""
        width, height = self.renderer.GetSize()
        camera = self.renderer.GetActiveCamera()
        matrix = camera.GetCompositeProjectionTransformMatrix(self.renderer.GetTiledAspectRatio(), -1, 1)
        m = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])
        clip = points @ m[:3, :3].T + m[:3, 3]
        w = points @ m[3, :3] + m[3, 3]
        ahead = w > 1e-9
        safe = np.where(ahead, w, 1.0)
        return (clip[:, 0] / safe + 1) / 2 * width, (clip[:, 1] / safe + 1) / 2 * height, ahead

    def rectangle_hits(self, points, corner_a, corner_b, front_only, tolerance, footprint=0.0):
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
            # Keep only points close to the nearest one in each screen tile. A tile is about as large as one
            # item on screen, so neighbours on the same surface never hide each other.
            eye, forward = np.array(camera.GetPosition()), np.array(camera.GetDirectionOfProjection())
            depth = (points[chosen] - eye) @ forward
            per_pixel = max(float(np.median(depth)), 1e-6) * self.pixel_angle()
            size = 3.0
            if footprint > 0:
                size = float(np.clip(footprint / per_pixel, 2.0, 64.0))
            else:
                footprint = 2.0 * size * per_pixel
            tile = (sx[chosen] // size).astype(np.int64) * 100_000 + (sy[chosen] // size).astype(np.int64)
            _, inverse = np.unique(tile, return_inverse=True)
            nearest = np.full(int(inverse.max()) + 1, np.inf)
            np.minimum.at(nearest, inverse, depth)
            chosen = chosen[depth <= nearest[inverse] + tolerance + footprint]
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
        if self._space:
            self._panning = True
            self.style.OnMiddleButtonDown()
            return
        if self.interactor.GetShiftKey() and self.band_allowed():
            self._band, self._band_subtract = (x, y), False
            return
        gizmo, handle = self._gizmo_at(x, y)
        if gizmo is not None:
            self._gizmo = gizmo
            gizmo.begin(handle, x, y)
            return
        if self.interactor.GetControlKey() and self.on_paint and self.paint_allowed():
            self._painting = True
            self.on_paint(x, y)
            return
        self.style.OnLeftButtonDown()

    def _on_right_press(self, *_):
        x, y = self.interactor.GetEventPosition()
        self._right = (x, y)
        if self.interactor.GetShiftKey():
            self._band, self._band_subtract = (x, y), True
        else:
            self.style.OnRightButtonDown()

    def _on_right_release(self, *_):
        x, y = self.interactor.GetEventPosition()
        start, self._right = self._right, None
        if self._band is not None:
            self._finish_band(x, y)
            return
        self.style.OnRightButtonUp()
        if start is not None and self.on_right_click and abs(x - start[0]) <= CLICK_SLOP and abs(y - start[1]) <= CLICK_SLOP:
            self.on_right_click(x, y)

    def _finish_band(self, x, y):
        start, self._band = self._band, None
        self.band_actor.VisibilityOff()
        if abs(x - start[0]) > CLICK_SLOP and abs(y - start[1]) > CLICK_SLOP:
            self.on_rectangle(start, (x, y), self._band_subtract or bool(self.interactor.GetControlKey()))
        else:
            self.render()

    def _on_move(self, *_):
        x, y = self.interactor.GetEventPosition()
        if self._gizmo is not None:
            self._gizmo.drag(x, y)
            self.render()
            return
        if self._painting:
            self.on_paint(x, y)
            return
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
        if self._press is None and self._right is None:
            over_handle = self._gizmo_at(x, y)[0] is not None
            self.widget.setCursor(Qt.SizeAllCursor if over_handle else self.default_cursor)
            if not over_handle:
                self.on_hover(x, y)

    def _on_release(self, *_):
        x, y = self.interactor.GetEventPosition()
        press, self._press = self._press, None
        ctrl = bool(self.interactor.GetControlKey())
        if self._panning:
            self._panning = False
            self.style.OnMiddleButtonUp()
            return
        if self._gizmo is not None:
            self._gizmo.end()
            self._gizmo = None
            return
        if self._painting:
            self._painting = False
            if self.on_paint_end:
                self.on_paint_end()
            return
        if self._band is not None:
            self._finish_band(x, y)
            return
        self.style.OnLeftButtonUp()
        if press is not None and abs(x - press[0]) <= CLICK_SLOP and abs(y - press[1]) <= CLICK_SLOP:
            self.on_click(x, y, ctrl)
