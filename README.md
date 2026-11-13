<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="MapBarber — a barbershop for robot maps" width="560">
  </picture>
</p>

<p align="center">
  <b>English</b> · <a href="README.ko.md">한국어</a> · <a href="README.ja.md">日本語</a> · <a href="README.zh.md">简体中文</a> · <a href="README.de.md">Deutsch</a> · <a href="README.es.md">Español</a>
</p>

**A barbershop for robot maps.** Clean and edit OctoMap voxel maps, point clouds and ROS 2D occupancy grids — and, since 1.1, label LiDAR point clouds and scan sequences. Everything runs offline, in one window.

[![tests](https://github.com/Hyounjun-Oh/MapBarber/actions/workflows/tests.yml/badge.svg)](https://github.com/Hyounjun-Oh/MapBarber/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![version](https://img.shields.io/badge/version-1.1.0-orange)

![Voxel editor, point cloud editor, 2D grid editor, point cloud labelling, 3D object labelling and auto 3D box labelling](docs/home.webp)

<sub>Labelling animations: [KITTI raw dataset](https://www.cvlibs.net/datasets/kitti/raw_data.php), drive 2011_09_26_0005 (Geiger et al., CC BY-NC-SA 3.0), frame 0 labelled by hand.</sub>

Detailed usage, every shortcut and the file notes are in the **[wiki](https://github.com/Hyounjun-Oh/MapBarber/wiki)**.

## Features

- **Voxel editor** — OctoMap `.bt` / `.ot`: erase, add, floating islands, box, slice, ruler; 35 million voxels stay interactive.
- **Point cloud editor** — PCD, PLY, LAS/LAZ, text, `.bin`: noise filters, thinning, colour by any field; every field is kept on save.
- **2D grid editor** — ROS map_server maps: pen, line, rectangle, fill, speckles, border trim, origin.
- **Conversion** — voxel map ↔ point cloud ↔ 2D grid, with lossless round trips.
- **LiDAR labelling** — classes, smart pick, 3D boxes and auto 3D box labelling through scan sequences; export to SemanticKITTI, KITTI and OpenPCDet.
- **Command line** — batch cleaning and conversion without a window.

| Voxel maps | Point clouds | 2D occupancy grids |
|---|---|---|
| ![Voxel maps](docs/voxel.gif) | ![Point clouds](docs/cloud.gif) | ![2D occupancy grids](docs/grid.gif) |

Maps convert between the three kinds without loss, and every edit can be undone until you save.

## Quick start

```bash
git clone https://github.com/Hyounjun-Oh/MapBarber.git
cd MapBarber
./mapbarber.sh                                  # empty window — drop maps onto it
./mapbarber.sh demo/office_octomap.bt           # or open files, one tab each
```

The first run installs NumPy, SciPy, VTK and PySide6 into `.venv/` (about 500 MB); you need Python 3.10+ and a desktop session. `pip install .` works too (`pip install ".[las]"` adds LAS/LAZ). [`demo/`](demo/README.md) has realistic maps with known defects and a checklist.

## New in 1.1: LiDAR labelling

### Point cloud labelling
Classes, label brush, protection of labelled points, review tools, objects, and export to SemanticKITTI, KITTI and OpenPCDet.

![Point cloud labelling](docs/labelling.gif)

### Smart pick
One click takes a whole car, pedestrian or pole without the ground under it — or a whole plane.

![Smart pick](docs/smart_pick.gif)

### 3D bounding boxes
Split a class into objects and box each one; a few mislabelled points do not stretch a box.

![3D bounding boxes](docs/boxes.gif)

### Auto 3D box labelling
Boxes and point labels are carried forwards or backwards in time through a whole drive. Here: from one hand-labelled frame through all 154 scans.

![Auto 3D box labelling](docs/auto_labelling.webp)

<sub>Labelling animations: [KITTI raw dataset](https://www.cvlibs.net/datasets/kitti/raw_data.php), drive 2011_09_26_0005 (Geiger et al., CC BY-NC-SA 3.0), frame 0 labelled by hand.</sub>

## Documentation

The **[wiki](https://github.com/Hyounjun-Oh/MapBarber/wiki)** is the full guide: [Getting started](https://github.com/Hyounjun-Oh/MapBarber/wiki/Getting-Started) · [Labelling](https://github.com/Hyounjun-Oh/MapBarber/wiki/Labelling) · [Smart pick](https://github.com/Hyounjun-Oh/MapBarber/wiki/Smart-Pick) · [3D boxes](https://github.com/Hyounjun-Oh/MapBarber/wiki/3D-Boxes) · [Auto 3D box labelling](https://github.com/Hyounjun-Oh/MapBarber/wiki/Auto-3D-Box-Labelling) · [Frame sequences](https://github.com/Hyounjun-Oh/MapBarber/wiki/Frame-Sequences) · [Keyboard shortcuts](https://github.com/Hyounjun-Oh/MapBarber/wiki/Keyboard-Shortcuts) · [Files and formats](https://github.com/Hyounjun-Oh/MapBarber/wiki/Files-and-Formats) · [Command line](https://github.com/Hyounjun-Oh/MapBarber/wiki/Command-Line) · [FAQ](https://github.com/Hyounjun-Oh/MapBarber/wiki/FAQ) — also in [한국어](https://github.com/Hyounjun-Oh/MapBarber/wiki/Home-ko).

## License

[MIT](LICENSE) — free to use, modify and redistribute, including commercially. Dependencies keep their own licenses (PySide6 LGPL-3.0; VTK, NumPy, SciPy BSD-3-Clause); see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), which also covers the KITTI data shown in the labelling animations. [CHANGELOG](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)
