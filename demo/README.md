# Demo maps for hands-on testing

[한국어](README.ko.md)

Every file here was produced by `tools/make_demo.py` from simulated sensors, so the maps contain the
same kinds of defects real robots leave behind, and the true dimensions are known. Open them, fix
them, and check the results against the numbers below.

```bash
./mapbarber.sh demo/office_octomap.bt demo/map_cloud.pcd demo/warehouse_map.yaml   # three tabs
```

## What is in the folder

| File | Opens in | Simulated source | Deliberate problems |
|---|---|---|---|
| `office_octomap.bt` | voxel editor | depth camera, 14 viewpoints, 5 cm voxels | flying pixels, ghost of a walking person, holes on a black monitor, ceiling hiding the room |
| `office_octomap_with_free.bt` | voxel editor | the same map saved by a live mapping node | also stores 608k free-space leaves |
| `office_color.ot` | voxel editor | the same map as a `ColorOcTree` | per-voxel colour |
| `office_octomap.bt.bak_20250101_090000` | voxel editor | a backup copy | no usable file extension |
| `office_voxels.npz` | voxel editor | NumPy voxel archive | — |
| `map_cloud.pcd` | point cloud editor | 120k points from the depth camera | outliers, flying pixels; `intensity` and `rgb` fields |
| `depth_frame.pcd` | point cloud editor | one organized 320 × 240 frame, camera optical frame | 39 % invalid (NaN) pixels, edge smearing |
| `lidar_sweep.ply` | point cloud editor | one 16-ring LiDAR sweep | dust returns; `intensity`, `ring`, `time` fields |
| `colored_points.xyz` | point cloud editor | text, `x y z r g b` per line | — |
| `survey_points.csv` | point cloud editor | CSV with a header and a label column | — |
| `cloud_points.npy` | point cloud editor | NumPy N × 3 array | — |
| `warehouse_map.yaml` + `.pgm` | grid editor | 2D LiDAR SLAM, 50 × 40 m, 5 cm cells | speckles, ghost double wall, a person's trail, an unknown hole, an open doorway, unknown border |
| `lab_map.yaml` + `.png` | grid editor | map_server map with `negate: 1` and a rotated origin (yaw 0.35 rad) | speckles |
| `keepout_mask.yaml` + `.pgm` | grid editor | costmap filter mask in `mode: raw` | — |
| `drive/` | point cloud editor, labeling mode | 16 LiDAR frames of a street with poses (KITTI layout), a class list and noisy model predictions | a walking person, a car driving towards the sensor, wrong predictions along the kerb |
| `broken_truncated.bt` | — | an octree cut off at 60 % | must be refused |
| `not_a_map.yaml` | — | a parameter file, not a map | must be refused |
| `not_points.txt` | — | meeting notes | must be refused |

## True dimensions (for the ruler)

| Map | Feature | True value |
|---|---|---|
| office | room inside, wall to wall along x / y | 8.00 m / 6.00 m |
| office | desk top height | 0.75 m |
| office | door opening in the south wall (y = 0) | 1.00 m wide, x 1.0–2.0 m |
| office | pillar | 0.40 × 0.40 m |
| office | ghost person | x 5.2–5.5, y 4.0–4.3, 1.75 m tall |
| warehouse | rack pitch, outline to outline | 5.00 m (100 px) |
| warehouse | clear aisle between racks | 3.80 m (76 free cells) |
| warehouse | rack | 1.20 m × 24.0 m |
| warehouse | doorway in the east wall | 5.0 m (map y −5 … 0) |

Voxel measurements are surface to surface and can be off by one voxel (5 cm) where noise sits on a
wall. Tick *Snap to voxel centres* for centre-to-centre readings.

## Scenarios

### 1. Clean a noisy voxel map — `office_octomap.bt`

1. **Slice** ▸ *Slice the space*, axis Z, position 2.9 m, keep *below*. The ceiling disappears and the
   status bar reports how many voxels are hidden and protected. Drag the blue arrow on the plane to
   move the cut.
2. **Islands** ▸ *Select small isolated clusters* (max 20). About 1,550 floating groups (≈2,190 voxels) turn pink.
   Press `Delete`.
3. The ghost person still stands east of the desk (x 5.2–5.5, y 4.0–4.3). Press `V`, then
   `Shift`-drag around it and press `Delete`. Right-click any voxel you selected by mistake to deselect it.
4. Measure: press `I`, click the west wall, then hold `Shift` and click the east wall. The ruler locks
   to the x axis and shows about 8.00 m. Measure the desk top height (0.75 m) the same way along z.
5. **Box**: tick *Show box*, drag the coloured arrows to move it over the black monitor
   (x 2.6–3.0, y 3.6–3.65, z 0.75–1.1) and the dots to resize it, then press *Fill the box*. The monitor's
   holes close; new voxels are white until you save.
6. *Restore view*. The ceiling is back, untouched: voxels in the hidden half were never edited.
7. `Ctrl+Z` steps back through every edit, `Ctrl+Shift+Z` forward again. `Ctrl+Shift+S` and save as
   `.bt`, then reopen the file: the count in the status bar matches.

### 2. The other octree variants

Open `office_octomap_with_free.bt`, `office_color.ot`, the `.bak_…` copy and `office_voxels.npz`.
Each opens in its own tab with the same 123,596 voxels as scenario 1. `Ctrl+Tab` cycles through them.

### 3. Clean a point cloud — `map_cloud.pcd`

1. *Colour by* ▸ *Stored colour*, then *intensity*.
2. **Noise filters** ▸ *Select outliers* → `Delete`; *Select sparse points* → `Delete`.
3. Press `E`, set the brush radius with `[` / `]`, and sweep away remaining specks.
4. Slice along Z to look under the desk, measure with `I` (floor to desk top ≈ 0.75 m).
5. Save as `.pcd` and reopen: the `intensity` and `rgb` fields are still there.

### 4. A single depth frame — `depth_frame.pcd`

The frame is organized (320 × 240) and in the camera optical frame (z forward). NaN pixels are
skipped automatically, so about 46,900 points are shown. The smear between foreground and background
is typical edge noise: *Select sparse points* or `Shift`-drag it away. Saving writes an unorganized
cloud.

### 5. LiDAR fields — `lidar_sweep.ply`

Colour by *intensity* and *ring*. Dust returns are short, weak and scattered: *Select sparse points*
removes most of them. `ring` and `time` survive saving to `.ply` or `.pcd`.

### 6. Text and NumPy points

`colored_points.xyz` shows its stored colours; `survey_points.csv` ignores the header and label
column; `cloud_points.npy` opens as plain points.

### 7. Repair a 2D SLAM map — `warehouse_map.yaml`

1. *Clear speckles* (max 4 cells).
2. The thin vertical line beside the third rack is a ghost wall from loop-closure drift. Press `L`,
   choose *Free* (`F`), set the pen to 3 cells and drag along it with `Shift` held: the line stays
   perfectly vertical.
3. The dotted wavy trail in the second aisle is a person who walked past: paint over it with `B` in
   *Free*.
4. Close the open doorway on the east wall: *Occupied* (`O`), `L`, `Shift`-drag along the gap.
5. Fill the grey unknown hole near the south wall: *Free*, press `G`, click inside it.
6. Measure the rack pitch with `I` and `Shift`: click the left outline of one rack, then of the next:
   5.00 m, 100 px.
7. *Trim unknown border*: the map shrinks and the origin changes, but nothing moves — measure the
   same racks again.
8. `Ctrl+S` writes both the `.pgm` and the `.yaml`.

### 8. Map server details — `lab_map.yaml`, `keepout_mask.yaml`

* `lab_map` uses `negate: 1` and a rotated origin. The red and green arrows point along the rotated
  map axes and the ruler's Δx / Δy are given in the map frame. Saving keeps `negate`.
* `keepout_mask` is a `raw` mask. Draw a keep-out zone with `R` in *Occupied* (hold `Shift` for a
  square, `Alt` to draw from the centre), save, reopen: the zone is still there and the file is still
  `raw`.

### 9. Conversions in new tabs

From the office voxel map choose **Convert ▸ To 2D occupancy grid…** with the band 0.1–1.8 m: a floor
plan opens in a new tab while the voxel map stays open. Convert `map_cloud.pcd` to a voxel map, or
extrude the warehouse map to 2 m walls.

### 10. Label a LiDAR sequence — `drive/`

```bash
./mapbarber.sh demo/drive
```

1. The folder opens in labeling mode with its own classes (`labels.yaml`). Drag the right handle of the
   timeline under the view to frame 5: six frames are merged by their poses.
2. **Ground filter** ▸ *Select ground*, then `Enter` with *road* active. Fix the kerb with the label
   brush `B` (*sidewalk*); `Ctrl`+drag paints with the view fixed.
3. Press `W` and click a parked car: only the car is picked, without the road under it. Choose
   *parked car* and press `Enter`. With *Protect labeled points* on, a rectangle over the whole street
   now selects only what is still unlabeled.
4. With *parked car* active press *Auto 3D boxes: parked car*. Each car becomes its own object with
   a box; turn or resize one in the box list.
5. *Auto 3D box labeling ▶ forwards in time* carries the boxes and object numbers from the first frame
   to the later ones (◀ goes back to earlier frames, for objects labeled in a middle frame); the score of
   each step is shown in the box list.
6. *Load labels…* ▸ pick `drive/predictions`: the model's guesses arrive as pale suggestions on the points
   that are still unlabeled. *Select labels unlike their neighbours* shows its mistakes along the kerb.
7. `Ctrl+S` writes `labels/*.label` and `boxes/*.json`; *Export in standard formats…* writes a
   SemanticKITTI sequence with KITTI and OpenPCDet boxes. Every step can be undone with `Ctrl+Z`.

### 11. Broken input

Open the three broken files (or drop them all at once). Each is refused with a short reason, and the
other tabs are unaffected.

### 12. Command line

```bash
./mapbarber.sh demo/office_octomap.bt --info
./mapbarber.sh demo/office_octomap.bt --remove-islands 20 -o /tmp/office_clean.bt
./mapbarber.sh demo/office_octomap.bt --z-band 0.1 1.8 -o /tmp/office_floor.yaml
./mapbarber.sh demo/warehouse_map.yaml --clear-speckles 4 -o /tmp/warehouse_clean.yaml
./mapbarber.sh demo/map_cloud.pcd --remove-outliers 16 2.0 -o /tmp/cloud_clean.pcd
./mapbarber.sh demo/broken_truncated.bt --info        # exits with status 1 and a message
```

## Performance set (not committed)

```bash
python tools/make_demo.py --large      # writes demo/large/, about 60 MB
```

| File | Size | Open | Select all + delete |
|---|---|---|---|
| `big_octomap.bt` | 546k voxels | 1.1 s | 0.6 s |
| `big_cloud.pcd` | 3,000,000 points | 0.9 s | 3.3 s |
| `warehouse_map_large.yaml` | 4000 × 3200 cells | 0.9 s | — (clear speckles 0.5 s) |

Timings from a desktop with an 8-core CPU; yours will differ.

## Regenerating

`python tools/make_demo.py` rebuilds this folder. The output is deterministic, so the numbers above
stay valid.
