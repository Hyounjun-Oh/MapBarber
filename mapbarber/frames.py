"""A folder of LiDAR frames with their poses: frames are read on demand and can be merged into one cloud."""
import os
import re
from collections import OrderedDict

import numpy as np

from . import formats

FRAME_EXTENSIONS = (".bin", ".pcd", ".ply", ".las", ".laz", ".xyz", ".npy")
POSE_NAMES = ("poses.txt", "poses.tum", "trajectory.txt", "trajectory.tum", "poses.csv")
CLASS_FILE = "labels.yaml"
CACHED_FRAMES = 64


def _rotation(qx, qy, qz, qw):
    norm = np.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm
    return np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                     [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                     [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])


_NAMES = {"time": ("timestamp", "time", "t", "stamp", "sec", "secs", "seconds"), "x": ("x", "tx", "px", "pos_x"),
          "y": ("y", "ty", "py", "pos_y"), "z": ("z", "tz", "pz", "pos_z"), "qx": ("qx", "q_x", "rx"),
          "qy": ("qy", "q_y", "ry"), "qz": ("qz", "q_z", "rz"), "qw": ("qw", "q_w", "w"), "roll": ("roll",),
          "pitch": ("pitch",), "yaw": ("yaw", "heading")}


def _columns_named(words):
    """Map of pose quantity -> column index, from a header line; None when the words are not a pose header."""
    lowered = [word.strip().lower() for word in words]
    found = {}
    for key, names in _NAMES.items():
        for name in names:
            if name in lowered:
                found[key] = lowered.index(name)
                break
    has_rotation = all(k in found for k in ("qx", "qy", "qz", "qw")) or all(k in found for k in ("roll", "pitch", "yaw"))
    return found if all(k in found for k in "xyz") and has_rotation else None


def read_poses(path, calibration=None):
    """Sensor poses from a text file -> ((N, 4, 4) matrices, time of each pose or None).

    Accepted rows: 12 numbers (a 3x4 matrix; with a KITTI calib.txt the camera frame is turned into the
    LiDAR frame), 16 numbers (a 4x4 matrix), 7 or 8 numbers ([time] x y z qx qy qz qw), or any columns
    named by a header line (time, x, y, z and qx qy qz qw or roll pitch yaw in radians).
    """
    header, rows = None, []
    for line in open(path, errors="replace"):
        words = line.replace(",", " ").replace(";", " ").split()
        if not words:
            continue
        if line.lstrip().startswith("#") or not re.match(r"^[-+.\d]", words[0]):
            named = _columns_named([word.lstrip("#") for word in words if word != "#"])
            header = header or named
            continue
        rows.append([float(word) for word in words])
    if not rows:
        raise ValueError("the pose file holds no numbers")
    rows = np.array(rows, np.float64)
    poses = np.tile(np.eye(4), (len(rows), 1, 1))
    times = None
    if header is not None:
        poses[:, :3, 3] = rows[:, [header["x"], header["y"], header["z"]]]
        times = rows[:, header["time"]] if "time" in header else None
        for index, row in enumerate(rows):
            poses[index, :3, :3] = (_rotation(*row[[header[k] for k in ("qx", "qy", "qz", "qw")]])
                                    if "qx" in header else _rotation_rpy(*row[[header[k] for k in ("roll", "pitch", "yaw")]]))
    elif rows.shape[1] in (12, 16):
        poses[:, :3, :] = rows[:, :12].reshape(-1, 3, 4)
        link = _lidar_to_camera(calibration) if rows.shape[1] == 12 else None
        if link is not None:
            poses = np.linalg.inv(link) @ poses @ link
    elif rows.shape[1] in (7, 8):
        values = rows[:, -7:]
        times = rows[:, 0] if rows.shape[1] == 8 else None
        poses[:, :3, 3] = values[:, :3]
        for index, quaternion in enumerate(values[:, 3:]):
            poses[index, :3, :3] = _rotation(*quaternion)
    else:
        raise ValueError("pose rows must hold 12 or 16 numbers (a matrix), [time] x y z qx qy qz qw, "
                         "or columns named in a header line")
    return poses, times


def _quaternion(rotation):
    """Rotation matrix -> unit quaternion (w, x, y, z)."""
    m = rotation
    w = np.sqrt(max(0.0, 1.0 + m[0, 0] + m[1, 1] + m[2, 2])) / 2
    x = np.copysign(np.sqrt(max(0.0, 1.0 + m[0, 0] - m[1, 1] - m[2, 2])) / 2, m[2, 1] - m[1, 2])
    y = np.copysign(np.sqrt(max(0.0, 1.0 - m[0, 0] + m[1, 1] - m[2, 2])) / 2, m[0, 2] - m[2, 0])
    z = np.copysign(np.sqrt(max(0.0, 1.0 - m[0, 0] - m[1, 1] + m[2, 2])) / 2, m[1, 0] - m[0, 1])
    q = np.array([w, x, y, z])
    return q / np.linalg.norm(q)


def interpolate(poses, times, wanted):
    """Poses at the `wanted` times: positions linearly, rotations along the shortest arc between neighbours."""
    order = np.argsort(times)
    poses, times = poses[order], np.asarray(times, np.float64)[order]
    out = np.tile(np.eye(4), (len(wanted), 1, 1))
    for index, moment in enumerate(wanted):
        right = int(np.clip(np.searchsorted(times, moment), 1, len(times) - 1)) if len(times) > 1 else 0
        left = max(right - 1, 0)
        span = times[right] - times[left]
        share = 0.0 if span <= 0 else float(np.clip((moment - times[left]) / span, 0.0, 1.0))
        out[index, :3, 3] = poses[left, :3, 3] * (1 - share) + poses[right, :3, 3] * share
        a, b = _quaternion(poses[left, :3, :3]), _quaternion(poses[right, :3, :3])
        if a @ b < 0:
            b = -b
        angle = np.arccos(np.clip(a @ b, -1.0, 1.0))
        q = a if angle < 1e-9 else (np.sin((1 - share) * angle) * a + np.sin(share * angle) * b) / np.sin(angle)
        out[index, :3, :3] = _rotation(q[1], q[2], q[3], q[0])
    return out


def name_time(name):
    """Time in seconds written in a frame's file name (seconds, or milli-, micro- or nanoseconds), or None."""
    found = re.findall(r"\d+(?:\.\d+)?", name)
    if not found:
        return None
    value = float(found[-1] if "." in found[-1] or len(found) == 1 else ".".join(found[-2:]))
    for limit, scale in ((1e17, 1e-9), (1e14, 1e-6), (1e11, 1e-3)):
        if value > limit:
            return value * scale
    return value


def natural_key(name):
    """Sort key that puts frame_2 before frame_10."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _lidar_to_camera(path):
    if not path or not os.path.isfile(path):
        return None
    for line in open(path, errors="replace"):
        if line.startswith("Tr:") or line.startswith("Tr "):
            link = np.eye(4)
            link[:3, :] = np.array(line.split(":", 1)[-1].split(), float).reshape(3, 4)
            return link
    return None


EARTH_RADIUS = 6378137.0


def _rotation_rpy(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = np.cos(roll), np.sin(roll), np.cos(pitch), np.sin(pitch), np.cos(yaw), np.sin(yaw)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def gnss_poses(rows):
    """GPS/IMU rows (lat, lon, alt in degrees and metres, roll, pitch, yaw in radians, ...) -> (N, 4, 4) poses.

    Positions are put on a local flat map with a Mercator projection scaled at the first latitude, and
    the first pose becomes the origin.
    """
    rows = np.asarray(rows, np.float64)
    lat, lon, alt = rows[:, 0], rows[:, 1], rows[:, 2]
    scale = np.cos(np.radians(lat[0]))
    east = scale * EARTH_RADIUS * np.radians(lon)
    north = scale * EARTH_RADIUS * np.log(np.tan(np.radians(90.0 + lat) / 2.0))
    poses = np.tile(np.eye(4), (len(rows), 1, 1))
    poses[:, :3, 3] = np.column_stack([east, north, alt])
    for index, (roll, pitch, yaw) in enumerate(rows[:, 3:6]):
        poses[index, :3, :3] = _rotation_rpy(roll, pitch, yaw)
    return np.linalg.inv(poses[0]) @ poses


def read_rigid(path):
    """A 'R: 9 numbers' and 'T: 3 numbers' calibration file -> 4x4 transform, or None."""
    if not path or not os.path.isfile(path):
        return None
    values = {}
    for line in open(path, errors="replace"):
        key, _, rest = line.partition(":")
        if key.strip() in ("R", "T"):
            values[key.strip()] = np.array(rest.split(), float)
    if "R" not in values or "T" not in values:
        return None
    out = np.eye(4)
    out[:3, :3], out[:3, 3] = values["R"].reshape(3, 3), values["T"]
    return out


def apply(pose, points):
    return points @ pose[:3, :3].T + pose[:3, 3]


class Sequence:
    def __init__(self, folder):
        folder = os.path.abspath(folder)
        if os.path.basename(folder) == "data" and os.path.basename(os.path.dirname(folder)) == "velodyne_points":
            folder = os.path.dirname(os.path.dirname(folder))
        elif os.path.basename(folder) == "velodyne_points":
            folder = os.path.dirname(folder)
        self.folder = folder
        self.scan_folder = next((path for path in (os.path.join(folder, "velodyne"),
                                                   os.path.join(folder, "velodyne_points", "data")) if os.path.isdir(path)),
                                folder)
        names = sorted((name for name in os.listdir(self.scan_folder)
                        if name.lower().endswith(FRAME_EXTENSIONS) and not name.startswith(".")), key=natural_key)
        if not names:
            raise ValueError("the folder holds no point cloud frames")
        self.paths = [os.path.join(self.scan_folder, name) for name in names]
        self.names = [name[:-len(".pcd.bin")] if name.lower().endswith(".pcd.bin") else os.path.splitext(name)[0]
                      for name in names]
        self.layout = ("kitti" if self.scan_folder.endswith(os.sep + "velodyne") else
                       "kitti raw" if self.scan_folder.endswith(os.path.join("velodyne_points", "data")) else "folder")
        self.poses, self.pose_source = None, None
        for base in (self.scan_folder, folder, os.path.dirname(folder)):
            found = next((os.path.join(base, name) for name in POSE_NAMES if os.path.isfile(os.path.join(base, name))), None)
            if found:
                self.use_poses(found)
                break
        if self.poses is None:
            self.poses = self._gnss_poses()
            self.pose_source = "oxts" if self.poses is not None else None
        self._cache = OrderedDict()
        self.counts = {}

    def use_poses(self, path):
        """Take poses from a file: matched by time when both the poses and the frame names carry one, else in order."""
        poses, times = read_poses(path, os.path.join(os.path.dirname(path), "calib.txt"))
        stamps = [name_time(name) for name in self.names]
        if times is not None and None not in stamps and len(times) > 1:
            low, high = times.min(), times.max()
            span = max(high - low, 1e-9)
            if all(low - 0.1 * span <= stamp <= high + 0.1 * span for stamp in stamps):
                self.poses, self.pose_source = interpolate(poses, times, stamps), os.path.basename(path)
                return
        if len(poses) < len(self.paths):
            raise ValueError(f"{os.path.basename(path)} holds {len(poses)} poses for {len(self.paths)} frames, "
                             "and the frame names carry no times to match them by")
        self.poses, self.pose_source = poses[:len(self.paths)], os.path.basename(path)

    def to_camera(self):
        """4x4 LiDAR-to-camera transform from the recording's calibration files, or None."""
        for base in (self.folder, os.path.dirname(self.folder)):
            found = read_rigid(os.path.join(base, "calib_velo_to_cam.txt"))
            if found is None:
                found = _lidar_to_camera(os.path.join(base, "calib.txt"))
            if found is not None:
                return found
        return None

    def drop_poses(self):
        """Treat the frames as already sharing one coordinate frame."""
        self.poses, self.pose_source = None, None

    def _gnss_poses(self):
        """LiDAR poses from a raw recording's GPS/IMU folder (oxts/data, one text row per frame), if there is one."""
        data = os.path.join(self.folder, "oxts", "data")
        if not os.path.isdir(data):
            return None
        rows = []
        for name in self.names:
            path = os.path.join(data, name + ".txt")
            if not os.path.isfile(path):
                return None
            rows.append(np.loadtxt(path, ndmin=1)[:6])
        poses = gnss_poses(rows)
        link = next((read_rigid(os.path.join(base, "calib_imu_to_velo.txt"))
                     for base in (self.folder, os.path.dirname(self.folder))
                     if os.path.isfile(os.path.join(base, "calib_imu_to_velo.txt"))), None)
        if link is not None:
            to_imu = np.linalg.inv(link)
            poses = poses @ to_imu
            poses = np.linalg.inv(poses[0]) @ poses
        return poses

    def __len__(self):
        return len(self.paths)

    @property
    def class_file(self):
        return os.path.join(self.folder, CLASS_FILE)

    def label_path(self, index):
        """Where a frame's labels are stored: the dataset's own `labels/` folder for .bin scans, else beside the frame."""
        path = self.paths[index]
        if path.lower().endswith(".bin"):
            base = os.path.join(self.folder, "labels") if self.scan_folder != self.folder else self.folder
            return os.path.join(base, self.names[index] + ".label")
        return formats.label_sidecar(path)

    def estimate(self, index):
        """Point count of a frame without reading it, when the file layout allows; else read it once."""
        if index in self.counts:
            return self.counts[index]
        path = self.paths[index]
        if path.lower().endswith(".bin"):
            return os.path.getsize(path) // 16
        return len(self.load(index)[0])

    def load(self, index):
        """(points in the sensor frame, record array) of one frame."""
        if index in self._cache:
            self._cache.move_to_end(index)
            return self._cache[index]
        xyz, table = formats.read_cloud(self.paths[index])
        self._cache[index] = (xyz, table)
        self.counts[index] = len(xyz)
        while len(self._cache) > CACHED_FRAMES:
            self._cache.popitem(last=False)
        return xyz, table

    def labels(self, index):
        """(class, instance) per point of a frame: from its label file, else from fields of the frame itself."""
        xyz, table = self.load(index)
        path = self.label_path(index)
        if os.path.isfile(path):
            return formats.read_label_file(path, len(xyz))
        cls, inst = formats.table_labels(table)
        return (np.zeros(len(xyz), np.uint16) if cls is None else cls,
                np.zeros(len(xyz), np.uint32) if inst is None else inst)

    def save_labels(self, index, cls, inst):
        path = self.label_path(index)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        formats.write_label_file(path, cls, inst)

    def merge(self, indices, progress=None):
        """Chosen frames in one cloud, placed by their poses.

        Returns (xyz, record array with `frame` and, when every frame has it, `intensity`, first point of each frame).
        """
        indices = list(indices)
        parts, starts, intensity = [], [0], []
        for done, index in enumerate(indices):
            if progress:
                progress(done, len(indices))
            xyz, table = self.load(index)
            parts.append(xyz if self.poses is None else apply(self.poses[index], xyz))
            starts.append(starts[-1] + len(xyz))
            intensity.append(table["intensity"] if table is not None and "intensity" in table.dtype.names else None)
        xyz = np.vstack(parts) if parts else np.zeros((0, 3))
        fields = [("x", "f4"), ("y", "f4"), ("z", "f4"), ("frame", "u4")]
        shared = all(values is not None for values in intensity) and bool(intensity)
        table = np.zeros(len(xyz), np.dtype(fields + ([("intensity", "f4")] if shared else [])))
        for axis, name in enumerate("xyz"):
            table[name] = xyz[:, axis]
        for index, start, end in zip(indices, starts[:-1], starts[1:]):
            table["frame"][start:end] = index
        if shared:
            table["intensity"] = np.concatenate(intensity)
        return xyz, table, np.array(starts)
