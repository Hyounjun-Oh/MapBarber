<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="MapBarber — a barbershop for robot maps" width="560">
  </picture>
</p>

**A barbershop for robot maps.** Trim the stray voxels, points and pixels that noisy sensors leave behind, and fill the bald spots — in OctoMap octrees, point clouds and ROS 2D occupancy grids, all from one window.

[![tests](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml/badge.svg)](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-Unlicense-green)

[한국어](README.ko.md)

![Opening three kinds of map, converting a voxel map to a 2D grid and switching language](docs/overview.gif)

Open or drop a file and MapBarber recognises what it holds, then hands it to the matching editor: a voxel editor for octrees, a point editor for clouds, and a painter for 2D occupancy grids. Maps can be converted between the three, and everything is undoable until you save.

## Quick start

```bash
git clone https://github.com/Hyounjun-Oh/mapbarber.git
cd mapbarber
./mapbarber.sh                      # empty window — drop a map onto it
./mapbarber.sh examples/room.bt     # or open a file directly
```

The first run creates a private virtual environment in `.venv/` and installs NumPy, SciPy, VTK and PySide6 (about 500 MB). Later runs start immediately. You need Python 3.9 or newer and a desktop session (X11, or Wayland through XWayland, which the script selects for you).

Prefer pip? `pip install .` installs a `mapbarber` command that does the same thing.

## What it opens

| Map type | Files | Opens in |
|---|---|---|
| Voxel map | OctoMap `.bt` (binary), `.ot` (`OcTree`, `OcTreeStamped`, `ColorOcTree`), `.npz` voxel archives | voxel editor |
| Point cloud | `.pcd` (ascii, binary), `.ply` (ascii, binary), `.xyz` / `.txt` / `.csv`, `.npy`, `.npz` | point cloud editor |
| 2D occupancy grid | map_server `.yaml` with `.pgm` / `.png` / `.bmp`, or the bare image | grid editor |

Detection looks at the extension first and the file signature second, so a backup such as `map.bt.bak_20240101` still opens as an octree. Opening a bare `.pgm` picks up the `.yaml` next to it when that YAML points at the image.

## Voxel map editor

![Removing floating specks and a ghost blob, filling a hole and adding voxels](docs/voxel.gif)

- **Navigate / Select / Erase / Add** tools with a cubic brush of 1–31 cells. Add grows a layer outward from the face you click, or places voxels on a horizontal work plane.
- **Shift + drag** selects everything inside a screen rectangle. *Front layer only* skips voxels hidden behind the surface you see.
- **Select islands** finds groups of voxels that touch nothing else — the floating specks depth cameras produce. It only selects, so you can look before pressing Delete.
- **Box** tools select, erase or fill an exact axis-aligned region typed in metres.
- **Visible range** hides a ceiling or a far wall so you can work inside the room. Hidden voxels are never edited.
- Voxels added since the last save are drawn white; the selection is pink.

## Point cloud editor

![Selecting outliers, erasing a streak, colouring by intensity and thinning out](docs/cloud.gif)

- **Select / Erase** with a spherical brush around the point you click, plus Shift + drag rectangles.
- **Noise filters** select statistical outliers (mean neighbour distance far above the norm) or sparse points (too few neighbours within a radius).
- **Thin out** keeps one point per cubic cell. **Box** crops: select, erase inside or erase outside.
- **Colour by** height, stored RGB or any numeric field such as `intensity`.
- Points are only ever removed, so saving to PCD or PLY keeps every field of every surviving point.

## 2D occupancy grid editor

![Clearing speckles, closing a doorway, drawing obstacles, filling a hole and trimming the border](docs/grid.gif)

- **Pen**, **Line**, **Rectangle** and **Fill** tools paint *occupied*, *free* or *unknown* (keys `O`, `F`, `U`).
- **Clear speckles** frees small isolated occupied blobs.
- **Trim unknown border** crops the unexplored margin and moves the origin so nothing on the map shifts.
- **Map info** edits resolution and origin (x, y, yaw). The red and green arrows mark the map origin.
- Saving writes the image and a map_server YAML side by side.

## Converting between map types

The **Convert** menu turns the open map into another kind and opens it in that editor. The original file is not touched.

| From \ To | Voxel map | Point cloud | 2D grid |
|---|---|---|---|
| Voxel map | — | voxel centres | project a height band |
| Point cloud | voxelize at a chosen size | — | voxelize, then project |
| 2D grid | extrude walls to a height | — | — |

## Command line

Without `--output` or `--info` the editor opens. With them, nothing is shown and the work is done in the terminal:

```bash
./mapbarber.sh room.bt --info
./mapbarber.sh room.bt --remove-islands 20 -o room_clean.bt
./mapbarber.sh room.bt --z-band 0.1 1.8 -o floor.yaml          # octree -> ROS map
./mapbarber.sh floor.yaml --clear-speckles 4 -o floor_clean.yaml
./mapbarber.sh floor.yaml --wall-height 2.0 -o walls.bt        # ROS map -> octree
./mapbarber.sh scan.pcd --remove-outliers 16 2.0 -o scan_clean.pcd
./mapbarber.sh scan.pcd -r 0.05 -o scan.bt                     # cloud -> octree
```

The output extension decides the output type.

## Keys

| Key | Action |
|---|---|
| `1` … `5` | switch tool (see the toolbar) |
| Left drag / middle drag / wheel | rotate / pan / zoom (2D: middle or right drag pans) |
| `Shift` + drag | rectangle select, with `Ctrl` to deselect |
| `Delete` / `Esc` | erase selection / clear selection |
| `Ctrl+A` / `Ctrl+I` | select all visible / invert selection |
| `Ctrl+Z` / `Ctrl+Y` | undo / redo |
| `Ctrl+S` / `Ctrl+Shift+S` | save / save as or export |
| `F1` | controls for the current editor |

## Languages

English, 한국어, 日本語, 简体中文, Deutsch and Español, switchable from the **Language** menu. The choice is remembered. To add a language, copy `mapbarber/locales/en.json`, translate the values, add the code to `LANGUAGES` in `mapbarber/i18n.py`, and run the tests — they check that every key and placeholder is present.

## File notes

- **Octree output** stores occupied cells only. Free-space information present in a source file is not written back, which matches how static maps are normally used for collision checking.
- **`.ot` output** uses one log-odds value (3.5, p ≈ 0.97) for every occupied cell.
- **PCD / PLY** keep all per-point fields. `.xyz`, `.csv` and `.npy` hold coordinates only. Compressed binary PCD is not supported.
- **Grids** follow the map_server rules: `trinary`, `scale` and `raw` modes, `negate`, and the occupied/free thresholds stored in the YAML.
- **Backups:** overwriting a file keeps the previous one as `name.bak_YYYYmmdd_HHMMSS`. Turn this off in the File menu.

## How it works

MapBarber is an independent implementation written from the published file layouts. It does not use or derive from the source code of OctoMap, PCL or map_server.

- Octree files are read and written as a *linear octree*. Occupied cells form a sorted array of Morton codes, so every tree node is a contiguous slice of that array, found by binary search. No pointer tree is built.
- Editing works on a sorted array of packed cell keys, with set operations for undo and redo.
- Connected components (islands, speckles) and neighbour queries use SciPy. Rendering uses VTK glyphs inside a Qt window.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                   # core tests, no display needed
MAPBARBER_GUI_TESTS=1 .venv/bin/pytest            # plus end-to-end tests in a real window
.venv/bin/python tools/make_examples.py            # regenerate examples/
.venv/bin/python tools/record_demo.py docs         # re-record the animations (needs ffmpeg)
.venv/bin/python tools/make_logo.py                # regenerate the icon and logos
```

Set `MAPBARBER_QT` to `PySide6`, `PySide2` or `PyQt5` to choose a Qt binding.

## License

Public domain, under the [Unlicense](LICENSE). Use it for anything, with or without credit. The dependencies keep their own licenses: PySide6 (LGPL-3.0), VTK (BSD-3-Clause), NumPy and SciPy (BSD-3-Clause).
