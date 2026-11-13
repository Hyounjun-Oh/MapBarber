# Changelog

## Unreleased

### Benchmark export
- **KITTI object:** a `label_2` file for every frame (empty when it has no box), `calib/*.txt` with `P0`–`P3`, `R0_rect`, `Tr_velo_to_cam` (and `Tr_imu_to_velo`) from the KITTI raw or odometry calibration, box locations in the rectified camera frame, `ImageSets/train.txt`.
- **KITTI tracking** (`tracking/label_02/0000.txt` + `calib`): object numbers become track ids.
- **OpenPCDet custom dataset:** `points/*.npy` (x y z intensity), `labels/*.txt`, `ImageSets/train.txt`.
- Suggestions not yet accepted (pale points, `?` boxes) are left out unless asked for; the status bar counts what was left out.

### Fixes and wording
- *Auto 3D box tracking* is now called **Auto 3D box labeling** (its buttons, messages and documentation).
- "Labelling" is spelled "labeling" everywhere (interface in six languages, documentation, file names of the animations).
- *Accept all suggestions* also accepts uncertain `?` boxes.

### Documentation
- README sections built on the 2 × 3 feature animation; translations moved to `docs/i18n/`, images to `docs/media/`, the changelog and third-party notices to `docs/`, contributing and security notes to `.github/`.
- New wiki page *Benchmark Export*; animations recorded again.

## 1.1.0 — 2026-11-13

MapBarber now labels point clouds, LiDAR scan sequences and voxel maps. The guide is in the
[wiki](https://github.com/Hyounjun-Oh/MapBarber/wiki) (English and Korean).

### Point cloud labeling
- **Labeling mode** (`Ctrl+L`, toolbar) in the point cloud and voxel editors; switching it off returns to editing as it was. Frames folders open in it.
- **Classes** with a role (obstacle, free surface, ignore), *wins any voxel* and *changes shape* flags; presets for indoor robots, SemanticKITTI and LAS; `labels.yaml`; eye and lock per class or for all at once.
- **Labeling:** *Label mapping* (`Enter`, `Ctrl+1`…`Ctrl+9`), label brush with `Ctrl`+drag painting and `Ctrl`+right drag take-back, `Alt`+click to take a class.
- **Protect labeled points** (corner switch, `P`), *write to* rules and locked classes keep earlier work out of wide selections.
- **Review:** progress, next unlabeled area (`N`), labels unlike their neighbours, small stray patches, suggestions for the gaps.
- **Objects:** split a class into objects, merge, undo the split; colour by object.
- **Files:** `label` / `instance` fields in PCD and PLY, LAS `classification`, SemanticKITTI `.label` per frame, `name.labels.npz` otherwise; export to SemanticKITTI, KITTI object labels and OpenPCDet.
- **Voxels:** voxel labels by vote of their points, and a lossless way back to every point's own label.
- `Ctrl+Z` / `Ctrl+Shift+Z` cover labels, classes, objects, boxes and auto labeling.

### Smart pick
- One click finds a **connected object**, a **flat surface** or a **smooth surface**; objects stop at the ground and, on dense data, at sharp bends; `[` / `]` loosen or tighten the last pick. Also in the voxel editor.
- **Ground filter:** select the ground or everything standing on it, judged per frame in sequences.

### 3D bounding boxes
- **Auto 3D boxes** for a class, for every object on screen, or around a selection; edit centre, size and yaw, refit, delete, select the points inside.
- Robust fitting leaves stray points out and turns each box to the object's faces; the box list counts strays and they can be selected.
- Unlabeled points beside a box can be selected and put into it.
- Boxes are saved per cloud (`name.boxes.json`) or per frame (`boxes/<frame>.json`).

### Auto 3D box labeling
- Boxes and point labels are carried **forwards or backwards in time** from every box made or corrected by hand; a run stops at the next such box of the same object, so objects labeled in a middle frame can be labeled both ways.
- Each frame is judged only against the previous one or two frames: box overlap picks the candidate, point-to-plane alignment fits it and holds still where surfaces cannot tell (static objects no longer slide).
- Score = 0.5 × IoU + 0.5 × alignment; frames below the accept score arrive as suggestions marked `?` and never teach the next frame.
- The starting frame is the reference: neighbours there are never taken later; shape-changing classes stay within their labeled size.
- *Auto-label again from the corrected box* carries a correction to the frames around it.

### Frame sequences
- KITTI odometry, KITTI raw (OXTS poses) and any folder of scans with a pose file (3×4, 4×4, TUM, CSV, timestamps in file names).
- **Timeline** under the view: frame range handles, sliding by the range width with the arrow keys, view fixed to the world, the LiDAR or a box.
- Suggest labels in other frames; select labels that differ between frames.

### Interface
- Point cloud card on the start screen and *Open frames folder* (`Ctrl+Shift+O`).
- Plain button names and a drawn icon for every button.
- Busy dialog with progress for long work; screen-sized axes and markers; LAS / LAZ support (optional laspy).

### Documentation
- Short README led by a 2 × 3 animation of the main features; the full guide, shortcuts and file notes moved to the wiki.

## 1.0.0 — 2026-11-12

First release: voxel, point cloud and 2D occupancy grid editors, lossless conversions, command line.
