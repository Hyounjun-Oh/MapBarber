"""Labels written in the layouts other tools and training code expect."""
import os

import numpy as np

from .labels import IGNORE, UNLABELED
from .safeio import replacing

AXES_TO_CAMERA = np.array([[0.0, -1.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0], [1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]])


def class_config(classes, counts=None):
    """Dataset description in the layout of SemanticKITTI's semantic-kitti.yaml.

    Raw class numbers are kept in the label files; `learning_map` squeezes them into 0..N for training,
    with unlabeled points and classes marked 'ignore' mapped to 0.
    """
    numbers = classes.numbers()
    kept = [number for number in numbers if classes.role(number) != IGNORE]
    train = {UNLABELED: 0, **{number: 0 for number in numbers}, **{number: i + 1 for i, number in enumerate(kept)}}
    total = max(sum((counts or {}).values()), 1)
    lines = ["# Written by MapBarber in the layout of semantic-kitti.yaml", "labels:", '  0: "unlabeled"']
    lines += [f'  {number}: "{classes.name(number)}"' for number in numbers]
    lines += ["color_map: # bgr", "  0: [0, 0, 0]"]
    lines += [f"  {number}: [{', '.join(str(v) for v in classes.rgb(number)[::-1])}]" for number in numbers]
    lines += ["content: # share of points per class"]
    lines += [f"  {number}: {(counts or {}).get(number, 0) / total:.10f}" for number in [UNLABELED] + numbers]
    lines += ["learning_map:"] + [f"  {number}: {train[number]}" for number in [UNLABELED] + numbers]
    lines += ["learning_map_inv:", "  0: 0"] + [f"  {i + 1}: {number}" for i, number in enumerate(kept)]
    lines += ["learning_ignore:", "  0: True"] + [f"  {i + 1}: False" for i in range(len(kept))]
    return "\n".join(lines) + "\n"


def semantic_kitti(folder, frames, classes, poses=None):
    """Write frames as a SemanticKITTI sequence folder: velodyne/*.bin, labels/*.label, poses.txt, calib.txt.

    frames yields (name, points in the sensor frame, intensity or None, class per point, instance per point).
    Poses are written for the LiDAR frame, with an identity `Tr` in calib.txt so that readers which apply
    the calibration arrive at the same poses. Returns the number of frames written.
    """
    for name in ("velodyne", "labels"):
        os.makedirs(os.path.join(folder, name), exist_ok=True)
    counts, written = {}, 0
    for name, xyz, intensity, cls, inst in frames:
        cloud = np.column_stack([xyz, np.zeros(len(xyz)) if intensity is None else intensity]).astype("<f4")
        with replacing(os.path.join(folder, "velodyne", name + ".bin")) as part:
            cloud.tofile(part)
        packed = (np.asarray(cls, np.uint32) & 0xFFFF) | ((np.asarray(inst, np.uint32) & 0xFFFF) << 16)
        with replacing(os.path.join(folder, "labels", name + ".label")) as part:
            packed.astype("<u4").tofile(part)
        found = np.bincount(np.asarray(cls, np.int64))
        for number in np.flatnonzero(found):
            counts[int(number)] = counts.get(int(number), 0) + int(found[number])
        written += 1
    if poses is not None:
        with replacing(os.path.join(folder, "poses.txt")) as part, open(part, "w") as f:
            f.writelines(" ".join(f"{v:.9g}" for v in pose[:3].ravel()) + "\n" for pose in poses)
        flat = "1 0 0 0 0 1 0 0 0 0 1 0"
        with replacing(os.path.join(folder, "calib.txt")) as part, open(part, "w") as f:
            f.write("".join(f"P{i}: {flat}\n" for i in range(4)) + f"Tr: {flat}\n")
    with replacing(os.path.join(folder, "semantic-kitti.yaml")) as part, open(part, "w", encoding="utf-8") as f:
        f.write(class_config(classes, counts))
    return written


def _token(name):
    return "_".join(name.split()) or "object"


def pcdet_boxes(path, boxes, classes):
    """One box per line in the LiDAR frame: x y z dx dy dz heading class (the OpenPCDet custom-dataset layout)."""
    with replacing(path) as part, open(part, "w", encoding="utf-8") as f:
        for box in boxes:
            values = list(box["center"]) + list(box["size"]) + [box["yaw"]]
            f.write(" ".join(f"{v:.4f}" for v in values) + f" {_token(classes.name(box['class']))}\n")


def rectified(calib):
    """4x4 transform from the LiDAR to the rectified camera frame of KITTI labels (R0_rect · Tr_velo_to_cam)."""
    rect, link = np.eye(4), np.eye(4)
    rect[:3, :3] = calib["R0_rect"]
    link[:3, :] = calib["Tr_velo_to_cam"]
    return rect @ link


def _camera_box(box, link):
    """(h, w, l, x, y, z, rotation_y) of a LiDAR box in a camera frame: bottom centre, turn about camera y."""
    length, width, height = box["size"]
    bottom = np.array([box["center"][0], box["center"][1], box["center"][2] - height / 2.0, 1.0])
    x, y, z = (link @ bottom)[:3]
    heading = link[:3, :3] @ np.array([np.cos(box["yaw"]), np.sin(box["yaw"]), 0.0])
    return height, width, length, x, y, z, float(np.arctan2(-heading[2], heading[0]))


def kitti_objects(path, boxes, classes, to_camera=None):
    """Boxes as KITTI object labels: type truncated occluded alpha bbox(4) h w l x y z rotation_y.

    Locations are the bottom centre of each box in the camera frame. `to_camera` is the 4x4 LiDAR-to-camera
    transform (rectified(); without one the usual axis convention is used: camera x = -LiDAR y, y = -z, z = x).
    Truncation and occlusion are written as 0, the viewing angle as -10 and the image box as zeros,
    because they need a camera image. A frame without boxes gets an empty file.
    """
    link = AXES_TO_CAMERA if to_camera is None else np.asarray(to_camera, np.float64)
    with replacing(path) as part, open(part, "w", encoding="utf-8") as f:
        for box in boxes:
            h, w, l, x, y, z, turn = _camera_box(box, link)
            f.write(f"{_token(classes.name(box['class']))} 0.00 0 -10.00 0.00 0.00 0.00 0.00 "
                    f"{h:.2f} {w:.2f} {l:.2f} {x:.2f} {y:.2f} {z:.2f} {turn:.2f}\n")


def kitti_calib(path, calib):
    """A KITTI object calibration file: P0..P3, R0_rect, Tr_velo_to_cam (and Tr_imu_to_velo when known)."""
    keys = ["P0", "P1", "P2", "P3", "R0_rect", "Tr_velo_to_cam"] + (["Tr_imu_to_velo"] if "Tr_imu_to_velo" in calib else [])
    with replacing(path) as part, open(part, "w") as f:
        f.writelines(f"{key}: " + " ".join(f"{v:.12e}" for v in np.ravel(calib[key])) + "\n" for key in keys)


def kitti_tracking(path, rows, classes, to_camera=None):
    """Boxes of a whole sequence as KITTI tracking labels (label_02):
    frame track_id type truncated occluded alpha bbox(4) h w l x y z rotation_y.

    rows are (frame number, box); the object number of a box is its track id (-1 for boxes without one).
    """
    link = AXES_TO_CAMERA if to_camera is None else np.asarray(to_camera, np.float64)
    with replacing(path) as part, open(part, "w", encoding="utf-8") as f:
        for frame, box in rows:
            h, w, l, x, y, z, turn = _camera_box(box, link)
            track = int(box.get("instance", 0)) or -1
            f.write(f"{frame} {track} {_token(classes.name(box['class']))} 0 0 -10.000000 0.000000 0.000000 0.000000 "
                    f"0.000000 {h:.6f} {w:.6f} {l:.6f} {x:.6f} {y:.6f} {z:.6f} {turn:.6f}\n")


def pcdet_points(path, xyz, intensity=None):
    """Points of one frame for the OpenPCDet custom dataset: points/<frame>.npy, float32 x y z intensity."""
    cloud = np.column_stack([xyz, np.zeros(len(xyz)) if intensity is None else intensity]).astype(np.float32)
    with replacing(path) as part, open(part, "wb") as f:
        np.save(f, cloud)
