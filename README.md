<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="MapBarber — a barbershop for robot maps" width="560">
  </picture>
</p>

<p align="center">
  <b>English</b> · <a href="README.ko.md">한국어</a> · <a href="README.ja.md">日本語</a> · <a href="README.zh.md">简体中文</a> · <a href="README.de.md">Deutsch</a> · <a href="README.es.md">Español</a>
</p>

**A barbershop for robot maps.** Trim the stray voxels, points and pixels that noisy sensors leave behind, and fill the bald spots — in OctoMap octrees, point clouds and ROS 2D occupancy grids, all from one window.

[![tests](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml/badge.svg)](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

![Opening three kinds of map in tabs, converting a voxel map to a 2D grid and switching language](docs/overview.gif)

Open or drop files and MapBarber recognises what each one holds, then opens it in its own tab with the matching editor: a voxel editor for octrees, a point editor for clouds, and a painter for 2D occupancy grids. Maps can be converted between the three, and every edit is undoable until you save.

## Quick start

```bash
git clone https://github.com/Hyounjun-Oh/mapbarber.git
cd mapbarber
./mapbarber.sh                                      # empty window — drop maps onto it
./mapbarber.sh demo/office_octomap.bt demo/warehouse_map.yaml   # or open files, one tab each
```

The first run creates a private virtual environment in `.venv/` and installs NumPy, SciPy, VTK and PySide6 (about 500 MB). Later runs start immediately. You need Python 3.10 or newer and a desktop session (X11, or Wayland through XWayland, which the script selects for you).

Prefer pip? `pip install .` installs a `mapbarber` command that does the same thing.

**Try it on realistic data:** [`demo/`](demo/README.md) holds maps made from simulated sensors, each with known defects and known true dimensions, plus a step-by-step checklist.

## What it opens

| Map type | Files | Opens in |
|---|---|---|
| Voxel map | OctoMap `.bt` (binary), `.ot` (`OcTree`, `OcTreeStamped`, `ColorOcTree`), `.npz` voxel archives | voxel editor |
| Point cloud | `.pcd` (ascii, binary, organized), `.ply` (ascii, binary), `.xyz` / `.txt` / `.csv` (optional RGB columns), `.npy`, `.npz` | point cloud editor |
| Point cloud (more) | `.las` / `.laz` (after `pip install "laspy[lazrs]"`), LiDAR `.bin` scans (x y z intensity) | point cloud editor |
| Frame sequence | a **folder** of scans with poses: KITTI odometry (`velodyne/` + `poses.txt`), KITTI raw (`velodyne_points/` + `oxts/`), or any folder of `.pcd` / `.ply` / `.las` / `.bin` with a pose file (TUM, 3×4 or 4×4 matrices, or CSV with a header) | point cloud editor in labelling mode |
| 2D occupancy grid | map_server `.yaml` with `.pgm` / `.png` / `.bmp`, or the bare image | grid editor |

Detection looks at the extension first and the file signature second, so a backup such as `map.bt.bak_20240101` still opens as an octree. Opening a bare `.pgm` picks up the `.yaml` next to it when that YAML points at the image. Damaged or unrelated files are refused with a short reason.

## Voxel map editor

![Removing floating specks and a ghost blob, filling a hole and adding voxels](docs/voxel.gif)

- **Tools:** Navigate `H`, Select `V`, Erase `E`, Add `B`, Measure `I`. The brush is a cube of 1–31 cells; `[` and `]` change its size. Add grows a layer outward from the face you click, or places voxels on a horizontal work plane.
- **Selection:** `Shift`-drag selects inside a screen rectangle (*Front layer only* skips hidden voxels). Right-click deselects under the cursor; `Shift`+right-drag deselects a rectangle.
- **Painting:** hold `Ctrl` and drag to keep applying the brush (select or erase) while the view stays still; one stroke is one undo step. `Backspace` takes back the last selection step.
- **Large maps:** the map is stored in chunks; distant chunks are drawn coarser and edits redraw only what they touch, so a 35-million-voxel building stays interactive.
- **Select islands** finds groups of voxels that touch nothing else — the floating specks depth cameras produce. It only selects, so you can look before pressing `Delete`.
- **Box:** drag the coloured arrows in the 3D view to move it along x, y or z, and the dots on its faces to resize it (or type the bounds). Then select, erase or fill everything inside.
- **Slice:** cut the space with a plane on x, y or z and work on one side; the other side is hidden and protected. Tilt the plane with two angles, drag its arrow to move it along its normal, flip sides, and *Restore view* when done.
- **Ruler:** click two voxels to read the distance, Δx/Δy/Δz and the length in voxels. Hold `Shift` to lock the measurement to an axis; tick *Snap to voxel centres* for centre-to-centre readings. The voxel under the cursor is outlined, and the offsets along x, y and z are drawn as coloured legs with their values. A read-out in the top-right corner repeats each measurement as a clear diagram, keeps every measurement in its own tab, and sums them on the Σ tab.
- Voxels added since the last save are drawn white; the selection is pink.
- Panel sections carry an icon and a colour stripe, and buttons are tinted by purpose: red erases, green adds, pink selects.

## Point cloud editor

![Selecting outliers, erasing a streak, colouring by intensity and thinning out](docs/cloud.gif)

- **Tools:** Navigate `H`, Select `V`, Erase `E`, Measure `I`, with a spherical brush around the point you click (`[` / `]` change its radius), rectangle selection and right-click deselect.
- **Noise filters** select statistical outliers (mean neighbour distance far above the norm) or sparse points (too few neighbours within a radius).
- **Thin out** keeps one point per cubic cell. **Box** and **Slice** work as in the voxel editor, and the box can also erase everything outside.
- **Colour by** height, stored RGB or any numeric field such as `intensity` or `ring`.
- **Ruler** measures the real distance between two picked points.
- Points are only ever removed, so saving to PCD keeps every field of every surviving point, and PLY every scalar field.
- **Large clouds:** the cloud is split into spatial chunks; distant chunks are thinned on screen and edits redraw only the chunks they touch, so 30 million points stay interactive.

## Labelling

Press **Labelling mode** in the toolbar (`Ctrl+L`) in the point cloud or voxel editor. The tools and the panel change to labelling; switching it off returns to editing exactly as it was. Everything runs offline on the CPU, and the original points are never moved or dropped.

- **Classes:** a list with number, name, colour and what the class means in a map (obstacle, free surface, ignore). Presets for indoor robots, SemanticKITTI and LAS codes; load or save `labels.yaml`. The eye hides a class and the lock freezes it; click the eye or lock in the header to switch it for every class.
- **Label:** select with any tool and press `Enter` (*Label mapping*) or `Ctrl+1`…`Ctrl+9`, or paint with the label brush `B`. `Ctrl`+drag paints with the view fixed, `Ctrl`+right drag takes back.
- **Protect labelled points** (the switch in the top-right corner of the view, or `P`): labelled points stay out of selections and keep their label, so a wide selection of a wall or floor skips the objects you labelled before.
- **Smart pick `W`:** click to find a *connected object*, a *flat surface* or a *smooth surface*. A connected object stops at the ground (clearance) and, on dense data, at wide surfaces that face another way; `[` / `]` loosen or tighten the last pick. The **Ground filter** selects the ground or everything standing on it.
- **Review:** progress bar, *Next unlabelled* (`N`), doubtful labels, small islands, and *Suggest for the gaps*; suggestions are shown pale until confirmed.
- **Objects and 3D boxes:** pick a class and press *Box every object of …*: its points are split into separate objects and each gets an upright box you can edit, refit or delete. *Back to class only* turns instances back into plain classes.
- **Frames:** open a folder of scans. The timeline under the view sets the first and last frame shown; the frames are merged by their poses while every label stays with its own frame. Labels can be carried to other frames as suggestions, and conflicts between frames can be listed. *View fixed to* on the same strip chooses what stays put while the frames change: the world, the LiDAR, or the box chosen in the box list.
- **Tracking:** box the objects in one frame, set the frame range, and *Track boxes*. Going forwards, each object is found in the next frame by box overlap (IoU) and its points are aligned (ICP) and gathered into one model, so the box grows to the whole object as the view of it changes. Then every frame, earlier ones too, is fitted again against the finished model: one box size per object, and the points an early, partial box missed are picked up. Classes marked *changes shape* (people) get a box per frame instead. Low scores arrive as suggestions marked `?`; *Select points left outside the boxes* shows what still hangs on to an object, and *Give them to their objects* takes it in and widens the box.
- **Voxels:** a cloud turned into voxels gives each voxel the class most of its points carry. Turning the map back gives every point its own label again; only voxels you relabelled pass their class on.
- **Files:** labels are stored in the file where the format allows (`label` / `instance` fields in PCD and PLY, `classification` in LAS), as `.label` files for `.bin` sequences, or beside the file (`name.labels.npz`). *Export in standard formats* writes a SemanticKITTI sequence, KITTI object labels and OpenPCDet boxes.
- `Ctrl+Z` covers labels, classes, boxes and tracking. `Delete` never removes points in labelling mode: it clears labels, or deletes the box or object clicked last.

## 2D occupancy grid editor

![Clearing speckles, closing a doorway, drawing obstacles, filling a hole and trimming the border](docs/grid.gif)

- **Tools:** Navigate `H`, Pen `B`, Line `L`, Rectangle `R`, Fill `G`, Measure `I`. Paint *occupied*, *free* or *unknown* with `O`, `F`, `U`; `[` / `]` change the pen width.
- **Constraints, as in PowerPoint:** hold `Shift` to lock a line (or the ruler) to 0°, 45° or 90° and to make a rectangle square; `Alt` draws a rectangle from its centre; `Shift`+click with the pen draws a straight line from the last point.
- **Clear speckles** frees small isolated occupied blobs.
- **Trim unknown border** crops the unexplored margin and moves the origin so nothing on the map shifts.
- **Map info** edits resolution and origin (x, y, yaw). The red and green arrows mark the map origin.
- **Ruler** gives the distance in metres and in pixels, and Δx/Δy in the map frame (rotated origins included).
- Zoomed out, thin walls stay visible: occupied cells win over unknown, unknown over free.
- Saving writes the image and a map_server YAML side by side (`trinary`, `scale` and `raw` modes, `negate`).

## Several maps at once

Every file opens in its own tab, and opening a file that is already open switches to it. `Ctrl+Tab` / `Ctrl+Shift+Tab` move between tabs, `Ctrl+W` closes one (asking first if it has unsaved changes), and you can drop several files at once.

The **Convert** menu turns the current map into another kind in a new tab, leaving the original untouched. Nothing is lost on the way back: a voxel map made from a cloud returns that cloud's own points at their exact positions with all fields (minus the voxels you erased), and a cloud made from voxels returns to the same voxels.

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

## Keyboard shortcuts

Shortcuts follow common desktop conventions (Photoshop, Figma and PowerPoint for tools and constraints, the operating system for files and editing). On macOS, `Ctrl` is `⌘`.

| Keys | Action |
|---|---|
| `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S` | open / save / save as or export |
| `Ctrl+N` / `Ctrl+Shift+N` | new voxel map / new 2D grid |
| `Ctrl+W` / `Ctrl+Tab` / `Ctrl+Shift+Tab` | close tab / next tab / previous tab |
| `Ctrl+Z` / `Ctrl+Shift+Z` or `Ctrl+Y` | undo / redo |
| `H` `V` `E` `B` `L` `R` `G` `I` | navigate, select, erase, add/pen, line, rectangle, fill, measure |
| `[` / `]` | smaller / larger brush |
| `Delete` / `Backspace` | erase selection / undo the last selection step |
| `Ctrl+A` / `Ctrl+Shift+I` / `Esc` or `Ctrl+D` | select all visible / invert / deselect |
| Left drag / middle drag or `Space`+drag / wheel | rotate / pan / zoom (2D: left drag pans with Navigate) |
| `Shift`+drag / `Shift`+right drag / right click | rectangle select / rectangle deselect / deselect |
| `Ctrl`+drag | paint with the brush (select or erase) while the view stays still |
| `Shift` / `Alt` while drawing | lock to 0°·45°·90° or square / draw from the centre |
| `1` `3` `7` / `0` or `Home` | front, side, top / isometric view (numpad too) |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | zoom in / zoom out / fit (2D) |
| `F11` / `F1` | full screen / controls for the current editor |
| `Ctrl+L` | labelling mode on / off |
| `B` / `W` (labelling mode) | label brush / smart pick |
| `Enter` / `Ctrl+1`…`Ctrl+9` / `Ctrl+0` or `Delete` | label the selection with the active class / the n-th class / clear the label |
| `P` / `N` / `Alt`+click | protect labelled points / next unlabelled patch / take the class under the cursor |
| `Ctrl`+right drag | take back with the brush (deselect or clear labels) while the view stays still |
| `,` / `.`  ·  click the timeline, then `←` / `→` | previous / next frame  ·  slide the frame range by its own width (`Shift`: by one frame) |

## Languages

The interface speaks English, 한국어, 日本語, 简体中文, Deutsch and Español, switchable from the **Language** menu; the choice is remembered. To add a language, copy `mapbarber/locales/en.json`, translate the values, add the code to `LANGUAGES` in `mapbarber/i18n.py`, and run the tests — they check that every key and placeholder is present.

## File notes

- **Octree files keep what they held.** Free space read from a `.bt` or `.ot` file is written back, split around any voxel you add; a `.ot` file also keeps each cell's occupancy value and, for a `ColorOcTree`, its colour. Voxels you add get log-odds 3.5 (p ≈ 0.97) and white; voxels you erase become *unknown*, not free.
- **When a format cannot hold something, MapBarber says so before writing.** Saving a `.ot` map as `.bt` reduces the values to occupied/free and drops colours; saving an octree as points drops free space. The dialog lists exactly what would be left out (the command line prints the same on stderr) and nothing is written until you agree.
- **PCD** keeps every per-point field, the `VIEWPOINT`, and the organized `WIDTH`/`HEIGHT` as long as no point was removed. **PLY** keeps every scalar field; vector fields and 64-bit integers cannot be stored and are reported, as are faces or other non-vertex elements of the source file. `.xyz`/`.csv` hold coordinates (six decimals) plus RGB when present, `.npy` coordinates only. Compressed binary PCD is not supported. *Thin out* keeps the first point read in each cell.
- **Grids** follow the map_server rules: `trinary`, `scale` and `raw` modes, `negate`, and the occupied/free thresholds stored in the YAML. The editor works with three states, but cells you do not touch are saved with the exact pixel value they had, so graded `scale`/`raw` maps survive an edit elsewhere.
- **Backups:** overwriting a file keeps the previous one as `name.bak_YYYYmmdd_HHMMSS`. Turn this off in the File menu.
- **Safe saving:** every file is written to a temporary name and put in place only when complete, so a failed save never damages the existing file (a map image and its YAML are replaced together). Origins and resolutions are written with full precision.
- **3D to 2D:** a voxel map or cloud records obstacles only, so cells without one become *unknown* in the grid. Tick the option in the conversion dialog (or pass `--empty-free`) to mark them free when the whole area was observed.
- **Bad input:** truncated or malformed files end in an error message, and cell indices outside ±32768 per axis are refused instead of wrapping around. See [SECURITY.md](SECURITY.md).

## How it works

MapBarber is an independent implementation written from the published file layouts. It does not use or derive from the source code of OctoMap, PCL or map_server.

- Octree files are read and written as a *linear octree*. Occupied cells form a sorted array of Morton codes, so every tree node is a contiguous slice of that array, found by binary search. No pointer tree is built.
- Editing works on a sorted array of packed cell keys, with set operations for undo and redo.
- Connected components (islands, speckles) and neighbour queries use SciPy. Rendering uses VTK glyphs inside a Qt window.

## License

[MIT](LICENSE). Use, modify and redistribute it freely, including commercially; just keep the copyright notice and license text with any copy. This covers the code, translations, logo, icons and the example and demo maps, all made for this project.

The libraries it runs on keep their own licenses: PySide6 (LGPL-3.0), VTK, NumPy and SciPy (BSD-3-Clause). Running from source or installing with pip needs nothing more; if you redistribute a bundle that contains them, see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Contributions are accepted under the same license ([CONTRIBUTING.md](CONTRIBUTING.md)).
