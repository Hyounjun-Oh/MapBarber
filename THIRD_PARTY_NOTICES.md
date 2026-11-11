# Third-party notices

MapBarber's own files are released under the MIT license (see `LICENSE`).
Nothing from other projects is copied into this repository. At run time it uses the libraries
below, which are installed separately (by `mapbarber.sh` or `pip`) and keep their own licenses.

| Library | Used for | License |
|---|---|---|
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html) | window, widgets, images | LGPL-3.0-only (or GPL, or a commercial Qt license) |
| [VTK](https://vtk.org/about/#license) | 3D rendering | BSD-3-Clause |
| [NumPy](https://numpy.org/doc/stable/license.html) | arrays | BSD-3-Clause |
| [SciPy](https://github.com/scipy/scipy/blob/main/LICENSE.txt) | connected components, neighbour search | BSD-3-Clause |

Only LGPL Qt modules are imported: QtCore, QtGui, QtWidgets and QtTest, plus the SVG image plugin for
the window icon. No GPL-only Qt module (such as Qt Charts or Qt Data Visualization) is used.
`MAPBARBER_QT` can select PySide2 (LGPL) or PyQt5 instead; PyQt5 is GPL-3.0 or commercial, so choosing
it puts the combined program under those terms for whoever distributes it.

## If you redistribute MapBarber bundled with these libraries

Running from source, or installing with `pip`, needs nothing beyond the above. If you ship a bundle
that contains the libraries (for example a PyInstaller build, a container image or an installer),
their licenses apply to that bundle:

- **Qt / PySide6 (LGPL-3.0):** include the LGPL-3.0 and GPL-3.0 license texts, state that Qt and
  PySide6 are used, keep the Qt libraries replaceable by the recipient (a one-folder build with
  separate shared libraries, not a single fused executable), and say where their source code can be
  obtained.
- **VTK, NumPy, SciPy (BSD-3-Clause):** include each project's copyright notice and license text.

## Names

OctoMap, PCL, ROS and map_server are the names of independent projects. MapBarber reads and writes
their file formats but is not affiliated with or endorsed by them, and contains none of their code.
