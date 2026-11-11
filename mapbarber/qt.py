"""Qt binding selection shared with VTK's Qt widget."""
import importlib
import os

import vtkmodules.qt as _vtk_qt

_CANDIDATES = ("PySide6", "PySide2", "PyQt5")


def _pick():
    wanted = os.environ.get("MAPBARBER_QT")
    for name in ((wanted,) if wanted else _CANDIDATES):
        try:
            importlib.import_module(f"{name}.QtWidgets")
            return name
        except ImportError:
            continue
    raise ImportError("no Qt binding found; install PySide6 (pip install PySide6)")


BINDING = _pick()
_vtk_qt.PyQtImpl = BINDING

QtCore = importlib.import_module(f"{BINDING}.QtCore")
QtGui = importlib.import_module(f"{BINDING}.QtGui")
QtWidgets = importlib.import_module(f"{BINDING}.QtWidgets")
QtTest = importlib.import_module(f"{BINDING}.QtTest")
QAction = getattr(QtGui, "QAction", None) or QtWidgets.QAction
QActionGroup = getattr(QtGui, "QActionGroup", None) or QtWidgets.QActionGroup

from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor  # noqa: E402


__all__ = ["BINDING", "QAction", "QActionGroup", "QtCore", "QtGui", "QtTest", "QtWidgets", "QVTKRenderWindowInteractor", "run"]


def run(target):
    """Run a QApplication or QDialog event loop on any supported binding."""
    return (getattr(target, "exec", None) or target.exec_)()
