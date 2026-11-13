# Changelog

## 1.1.0 — 2026-11-13

MapBarber now labels LiDAR point clouds, scan sequences and voxel maps. The guide is in the
[wiki](https://github.com/Hyounjun-Oh/MapBarber/wiki) (English and Korean).

### Point cloud labelling
- **Labelling mode** (`Ctrl+L`, toolbar) in the point cloud and voxel editors; switching it off returns to editing as it was. Frames folders open in it.
- **Classes** with a role (obstacle, free surface, ignore), *wins any voxel* and *changes shape* flags; presets for indoor robots, SemanticKITTI and LAS; `labels.yaml`; eye and lock per class or for all at once.
- **Labelling:** *Label mapping* (`Enter`, `Ctrl+1`…`Ctrl+9`), label brush with `Ctrl`+drag painting and `Ctrl`+right drag take-back, `Alt`+click to take a class.
- **Protect labelled points** (corner switch, `P`), *write to* rules and locked classes keep earlier work out of wide selections.
- **Review:** progress, next unlabelled area (`N`), labels unlike their neighbours, small stray patches, suggestions for the gaps.
- **Objects:** split a class into objects, merge, undo the split; colour by object.
- **Files:** `label` / `instance` fields in PCD and PLY, LAS `classification`, SemanticKITTI `.label` per frame, `name.labels.npz` otherwise; export to SemanticKITTI, KITTI object labels and OpenPCDet.
- **Voxels:** voxel labels by vote of their points, and a lossless way back to every point's own label.
- `Ctrl+Z` / `Ctrl+Shift+Z` cover labels, classes, objects, boxes and tracking.

### Smart pick
- One click finds a **connected object**, a **flat surface** or a **smooth surface**; objects stop at the ground and, on dense data, at sharp bends; `[` / `]` loosen or tighten the last pick. Also in the voxel editor.
- **Ground filter:** select the ground or everything standing on it, judged per frame in sequences.

### 3D bounding boxes
- **Auto 3D boxes** for a class, for every object on screen, or around a selection; edit centre, size and yaw, refit, delete, select the points inside.
- Robust fitting leaves stray points out and turns each box to the object's faces; the box list counts strays and they can be selected.
- Unlabelled points beside a box can be selected and put into it.
- Boxes are saved per cloud (`name.boxes.json`) or per frame (`boxes/<frame>.json`).

### Auto 3D box tracking
- Tracking **forwards or backwards in time** from every box made or corrected by hand; a track stops at the next such box of the same object, so objects labelled in a middle frame can be followed both ways.
- Each frame is judged only against the previous one or two frames: box overlap picks the candidate, point-to-plane alignment fits it and holds still where surfaces cannot tell (static objects no longer slide).
- Score = 0.5 × IoU + 0.5 × alignment; frames below the accept score arrive as suggestions marked `?` and never teach the next frame.
- The starting frame is the reference: neighbours there are never taken later; shape-changing classes stay within their labelled size.
- *Re-track from the corrected box* carries a correction to the frames around it.

### Frame sequences
- KITTI odometry, KITTI raw (OXTS poses) and any folder of scans with a pose file (3×4, 4×4, TUM, CSV, timestamps in file names).
- **Timeline** under the view: frame range handles, sliding by the range width with the arrow keys, view fixed to the world, the LiDAR or a box.
- Suggest labels in other frames; select labels that differ between frames.

### Interface
- Point cloud card on the start screen and *Open frames folder* (`Ctrl+Shift+O`).
- Plain button names and a drawn icon for every button.
- Busy dialog with progress for long work; screen-sized axes and markers; LAS / LAZ support (optional laspy).

### Documentation
- Short README built around animations; the full guide, shortcuts and file notes moved to the wiki.

## 1.0.0 — 2026-11-12

First release: voxel, point cloud and 2D occupancy grid editors, lossless conversions, command line.
