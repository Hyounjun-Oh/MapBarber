"""Label classes, the label layer, voting, the labeling helpers, label files and frame sequences."""
import os

import numpy as np
import pytest

from mapbarber import convert, formats, frames, labels
from mapbarber.grid import FREE, OCCUPIED, UNKNOWN
from mapbarber.voxels import VoxelMap, pack
from mapbarber.labels import ClassList, LabelLayer


def scene(seed=0):
    """A floor, a wall standing on it and a box floating apart: (points, truth 1/2/3)."""
    rng = np.random.default_rng(seed)
    floor = np.column_stack([rng.uniform(0, 4, 4000), rng.uniform(0, 4, 4000), rng.normal(0, 0.004, 4000)])
    wall = np.column_stack([rng.uniform(0, 4, 3000), rng.normal(4.0, 0.004, 3000), rng.uniform(0, 2, 3000)])
    box = rng.uniform(0, 0.4, (1500, 3)) + [1.5, 1.5, 0.6]
    return np.vstack([floor, wall, box]), np.repeat([1, 2, 3], [4000, 3000, 1500])


def test_class_list_round_trip_and_dataset_config():
    classes = ClassList("indoor")
    classes.set(40, 'say "hi"', (1, 2, 3), labels.IGNORE)
    again = ClassList.loads(classes.dumps())
    assert again.items == classes.items and again.role(1) == labels.FREE_ROLE and again.name(40) == 'say "hi"'
    kitti = ClassList.loads('labels:\n  0: "unlabeled"\n  10: "car"\n  40: "road"\ncolor_map: # bgr\n  10: [245, 150, 100]\n')
    assert kitti.numbers() == [10, 40] and kitti.rgb(10) == (100, 150, 245) and kitti.role(40) == labels.FREE_ROLE
    assert len(ClassList("semantickitti")) > 25 and ClassList("las").name(2) == "ground"
    classes.ensure(np.array([0, 1, 77]))
    assert 77 in classes and classes.palette(77).shape == (78, 3)
    with pytest.raises(ValueError):
        classes.set(0, "zero")


def test_label_layer_rules_and_undo():
    layer = LabelLayer(10)
    assert layer.assign(np.arange(5), 3) == 5 and layer.dirty
    assert layer.allowed(np.arange(10), "unlabeled").tolist() == [5, 6, 7, 8, 9]
    assert layer.allowed(np.arange(10), "only", 3).tolist() == [0, 1, 2, 3, 4]
    assert layer.allowed(np.arange(10), locked={3}).tolist() == [5, 6, 7, 8, 9]
    depth = layer.undo_depth()
    layer.assign([4, 5], 7)
    layer.assign([5, 6], 8, inst=2)
    layer.squash(depth)
    assert layer.cls.tolist() == [3, 3, 3, 3, 7, 8, 8, 0, 0, 0] and layer.undo_depth() == depth + 1
    assert layer.undo() and layer.cls.tolist() == [3] * 5 + [0] * 5 and not layer.inst.any()
    assert layer.redo() and layer.cls[5] == 8 and layer.inst[6] == 2
    assert layer.assign([4], 7) == 0 and layer.counts() == {0: 3, 3: 4, 7: 1, 8: 2}
    layer.assign([9], 4, pending=True)
    assert layer.pending[9] and layer.confirm() == 1 and not layer.pending.any() and layer.cls[9] == 4
    layer.mark_saved()
    assert not layer.dirty and layer.next_instance() == 3


def test_vote_majority_ties_and_dominant_classes():
    groups = np.array([5, 5, 5, 9, 9, 9, 9, 2, 2, 7])
    cls = np.array([1, 1, 2, 3, 3, 4, 4, 0, 6, 0])
    unique, winner, purity = labels.vote(groups, cls)
    assert unique.tolist() == [2, 5, 7, 9] and winner.tolist() == [6, 1, 0, 3]
    assert np.allclose(purity, [1.0, 2 / 3, 1.0, 0.5])
    assert labels.vote(groups, cls, priority=[4])[1].tolist() == [6, 1, 0, 4]
    _, winner, purity = labels.vote(groups, cls, dominant=[2])
    assert winner.tolist() == [6, 2, 0, 3] and np.isclose(purity[1], 1 / 3)


def test_plane_cluster_and_growth_find_the_parts_of_a_scene():
    points, truth = scene()
    floor_seed = int(np.argmin(np.linalg.norm(points[:4000, :2] - [2, 2], axis=1)))
    floor = labels.plane_at(points, floor_seed, 0.3, 0.03)
    assert (truth[floor] == 1).mean() > 0.97 and len(floor) > 3800

    rest = np.flatnonzero(truth != 1)
    box_seed = int(np.flatnonzero(truth[rest] == 3)[0])
    cluster = rest[labels.cluster_at(points[rest], box_seed, 0.12)]
    assert set(truth[cluster]) == {3} and len(cluster) == 1500
    assert set(truth[rest[labels.small_groups(points[rest], 0.12, 2000)]]) == {3}

    near = np.flatnonzero(np.linalg.norm(points - points[floor_seed], axis=1) < 3.5)
    grown = near[labels.grow(points[near], int(np.flatnonzero(near == floor_seed)[0]), 0.15, 20)]
    assert (truth[grown] == 1).mean() > 0.95 and len(grown) > 1000


def test_review_helpers_find_mistakes_and_fill_gaps():
    points, truth = scene(1)
    cls = truth.astype(np.uint16)
    wrong = np.array([10, 500, 4500])
    cls[wrong] = 9
    assert set(wrong) <= set(labels.disagreeing(points, cls).tolist())
    cls = truth.astype(np.uint16)
    holes = np.arange(0, len(cls), 7)
    cls[holes] = 0
    ids, guess = labels.suggest(points, cls, 0.3)
    assert len(ids) > 0.95 * len(holes) and (guess == truth[ids]).mean() > 0.97
    moved = labels.transfer(points, truth, points + 0.01, 0.05, classes=[1, 2])
    assert (moved[truth == 3] == 0).all() and (moved[truth == 1] == 1).mean() > 0.99


def test_boxes_follow_instances():
    angle = np.radians(30)
    local = np.random.default_rng(2).uniform([-2, -0.5, 0], [2, 0.5, 1], (4000, 3))
    turn = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    points = np.column_stack([local[:, :2] @ turn.T + [5, 3], local[:, 2]])
    centre, size, yaw = labels.oriented_box(points)
    assert np.allclose(centre, [5, 3, 0.5], atol=0.05) and np.allclose(sorted(size), [1, 1, 4], atol=0.05)
    assert abs((yaw - angle + np.pi / 2) % np.pi - np.pi / 2) < 0.03
    found = labels.boxes(points, np.full(4000, 6), np.repeat([0, 4], 2000))
    assert len(found) == 1 and found[0][:2] == (6, 4) and found[0][5] == 2000


@pytest.mark.parametrize("extension", ["pcd", "ply", "xyz", "las", "laz"])
def test_labels_travel_inside_point_files(tmp_path, extension):
    pytest.importorskip("laspy") if extension in ("las", "laz") else None
    xyz = np.round(np.random.default_rng(3).uniform(-5, 5, (50, 3)), 3)
    base = np.zeros(50, np.dtype([("x", "f4"), ("y", "f4"), ("z", "f4"), ("intensity", "f4")]))
    for axis, name in enumerate("xyz"):
        base[name] = xyz[:, axis]
    base["intensity"] = np.arange(50)
    cls, inst = (np.arange(50) % 5).astype(np.uint16), (np.arange(50) % 3).astype(np.uint32)
    path = str(tmp_path / f"scan.{extension}")
    table = formats.with_labels(xyz, base, cls, inst)
    formats.save_cloud(path, xyz, table)
    back_xyz, back = formats.read_cloud(path)
    assert np.allclose(back_xyz, xyz, atol=2e-3)
    read_cls, read_inst = formats.table_labels(back)
    assert read_cls.tolist() == cls.tolist()
    if extension != "xyz":
        assert read_inst.tolist() == inst.tolist() and back["intensity"].tolist() == base["intensity"].tolist()
    if extension in ("las", "laz"):
        assert back["classification"].tolist() == cls.tolist()
        formats.save_cloud(path, back_xyz, back)
        again = formats.read_cloud(path)[1]
        assert formats.table_labels(again)[0].tolist() == cls.tolist() and again.dtype.names == back.dtype.names


def test_existing_label_field_is_reused(tmp_path):
    table = np.zeros(4, np.dtype([("x", "f4"), ("y", "f4"), ("z", "f4"), ("Classification", "u1")]))
    table["Classification"] = [2, 2, 6, 0]
    assert formats.label_fields(table) == ("Classification", None)
    out = formats.with_labels(formats._columns(table), table, np.array([1, 2, 3, 4], np.uint16), np.zeros(4, np.uint32))
    assert out.dtype.names == table.dtype.names and out["Classification"].tolist() == [1, 2, 3, 4]
    assert table["Classification"].tolist() == [2, 2, 6, 0]


def test_label_files(tmp_path):
    cls, inst = np.array([0, 40, 10, 10], np.uint16), np.array([0, 0, 1, 2], np.uint32)
    for name in ("000000.label", "scan.pcd.labels.npz"):
        path = str(tmp_path / name)
        formats.write_label_file(path, cls, inst)
        read_cls, read_inst = formats.read_label_file(path, 4)
        assert read_cls.tolist() == cls.tolist() and read_inst.tolist() == inst.tolist()
    assert np.fromfile(str(tmp_path / "000000.label"), np.uint32).tolist() == [0, 40, 10 | 1 << 16, 10 | 2 << 16]
    with pytest.raises(ValueError):
        formats.read_label_file(str(tmp_path / "000000.label"), 5)
    assert formats.label_sidecar("a/b.pcd") == "a/b.pcd.labels.npz"


def make_sequence(folder, count=4, per_frame=300):
    """KITTI-style folder: a wall seen from a sensor that moves 1 m along x per frame."""
    rng = np.random.default_rng(4)
    os.makedirs(folder / "velodyne")
    world = np.column_stack([rng.uniform(0, 10, per_frame), np.full(per_frame, 5.0), rng.uniform(0, 2, per_frame)])
    lines = []
    for index in range(count):
        local = world - [index, 0, 0]
        np.column_stack([local, np.full(per_frame, index)]).astype("<f4").tofile(str(folder / "velodyne" / f"{index:06d}.bin"))
        lines.append(f"1 0 0 {index} 0 1 0 0 0 0 1 0")
    (folder / "poses.txt").write_text("\n".join(lines) + "\n")
    return world


def test_sequence_merges_frames_by_pose_and_keeps_labels_per_frame(tmp_path):
    world = make_sequence(tmp_path / "seq")
    sequence = frames.Sequence(str(tmp_path / "seq"))
    assert len(sequence) == 4 and sequence.poses.shape == (4, 4, 4)
    assert formats.kind(str(tmp_path / "seq")) == formats.CLOUD and formats.detect(str(tmp_path / "seq")) == formats.FRAMES
    xyz, table, starts = sequence.merge([1, 3])
    assert starts.tolist() == [0, 300, 600] and np.allclose(xyz[:300], world, atol=1e-4) and np.allclose(xyz[300:], world, atol=1e-4)
    assert table["frame"][[0, 599]].tolist() == [1, 3] and table["intensity"][[0, 599]].tolist() == [1, 3]

    assert not sequence.labels(1)[0].any()
    sequence.save_labels(1, np.full(300, 50, np.uint16), np.zeros(300, np.uint32))
    assert sequence.label_path(1).endswith(os.path.join("seq", "labels", "000001.label"))
    assert sequence.labels(1)[0].tolist() == [50] * 300 and not sequence.labels(2)[0].any()


def test_poses_as_quaternions_and_frames_without_poses(tmp_path):
    (tmp_path / "t.tum").write_text("# time x y z qx qy qz qw\n0.0 1 2 3 0 0 0.7071068 0.7071068\n")
    pose = frames.read_poses(str(tmp_path / "t.tum"))[0][0]
    assert np.allclose(frames.apply(pose, np.array([[1.0, 0, 0]])), [[1, 3, 3]], atol=1e-5)
    formats.save_cloud(str(tmp_path / "a.pcd"), np.zeros((3, 3)) + 1)
    formats.save_cloud(str(tmp_path / "b.pcd"), np.zeros((2, 3)) + 2)
    sequence = frames.Sequence(str(tmp_path))
    assert sequence.poses is None and len(sequence.merge([0, 1])[0]) == 5
    assert sequence.label_path(0).endswith("a.pcd.labels.npz")
    with pytest.raises(ValueError):
        frames.Sequence(str(tmp_path / "nothing")) if os.makedirs(tmp_path / "nothing") is None else None


def test_voxel_labels_keep_edits_apart_from_the_vote():
    keys = pack(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]]))
    voxels = labels.VoxelLabels(keys[::-1], [3, 2, 1], [1.0, 0.5, 0.9])
    assert voxels.get(keys).tolist() == [1, 2, 3] and voxels.any and not voxels.dirty
    assert voxels.mixed(keys, 0.6).tolist() == [keys[1]]
    fresh = pack(np.array([[9, 9, 9]]))
    assert voxels.set(np.concatenate([keys[:2], fresh]), 7) == 3 and voxels.dirty
    assert voxels.get(np.concatenate([keys, fresh])).tolist() == [7, 7, 3, 7]
    assert voxels.edited()[0].tolist() == sorted([keys[0], keys[1], fresh[0]])
    assert voxels.mixed(keys, 0.6).tolist() == []
    depth = voxels.undo_depth()
    voxels.set(keys[2:], 9)
    voxels.set(keys[:1], 3)
    voxels.squash(depth)
    assert voxels.undo() and voxels.get(keys).tolist() == [7, 7, 3]
    assert voxels.undo() and voxels.get(keys).tolist() == [1, 2, 3] and not voxels.dirty
    assert voxels.redo() and voxels.get(keys).tolist() == [7, 7, 3]
    voxels.set(keys[:1], 1)
    assert voxels.edited()[0].tolist() == sorted([keys[1], fresh[0]])
    assert voxels.counts(keys) == {3: 1, 7: 1, 1: 1}


def labeled_cloud():
    """Points in 0.1 m voxels: a floor voxel row, a wall voxel with one person point inside, and a person apart."""
    rng = np.random.default_rng(5)
    xyz = np.vstack([rng.uniform([0, 0, 0], [0.6, 0.1, 0.1], (60, 3)),
                     rng.uniform([0.0, 0.5, 0.5], [0.1, 0.6, 0.6], (10, 3)),
                     rng.uniform([2.0, 2.0, 0.5], [2.1, 2.1, 0.6], (5, 3))])
    cls = np.repeat(np.array([1, 2, 7], np.uint16), [60, 10, 5])
    cls[60] = 7
    inst = np.zeros(75, np.uint32)
    inst[60:70] = 4
    table = np.zeros(75, np.dtype([("x", "f4"), ("y", "f4"), ("z", "f4"), ("intensity", "f4")]))
    for axis, name in enumerate("xyz"):
        table[name] = xyz[:, axis]
    table["intensity"] = np.arange(75)
    return xyz, table, cls, inst


def test_points_come_back_with_their_own_labels():
    xyz, table, cls, inst = labeled_cloud()
    classes = labels.ClassList("indoor")
    keys, winner, purity = convert.vote_voxels(xyz, cls, 0.1, classes)
    wall = convert.point_keys(xyz[60:61], 0.1)[0]
    assert winner[keys == wall].tolist() == [2] and np.isclose(purity[keys == wall][0], 0.9)
    classes.set(7, "person", role=labels.IGNORE, wins=True)
    assert convert.vote_voxels(xyz, cls, 0.1, classes)[1][keys == wall].tolist() == [7]

    voxel_map = VoxelMap(np.unique(keys), 0.1)
    restored = convert.restore(xyz, table, 0.1, voxel_map, cls, inst, labels.VoxelLabels(keys, winner, purity))
    assert np.array_equal(restored["xyz"], xyz) and restored["table"].tobytes() == table.tobytes()
    assert restored["cls"].tolist() == cls.tolist() and restored["inst"].tolist() == inst.tolist()
    assert restored["added"] == restored["dropped"] == restored["relabeled"] == 0

    person = convert.point_keys(xyz[70:], 0.1)[0]
    outside = cls == 7
    kept = np.unique(convert.point_keys(xyz[~outside], 0.1))
    voxel_map = VoxelMap(kept, 0.1)
    votes = labels.VoxelLabels(*convert.vote_voxels(xyz[~outside], cls[~outside], 0.1, classes))
    assert person not in voxel_map.occupied
    restored = convert.restore(xyz, table, 0.1, voxel_map, cls, inst, votes, outside)
    assert np.array_equal(restored["xyz"], xyz) and restored["cls"].tolist() == cls.tolist()

    floor = convert.point_keys(xyz[:1], 0.1)[0]
    new = pack(np.array([[30, 30, 30]]))
    voxel_map.apply(add=new, remove=[floor])
    votes.set([wall], 5)
    votes.set(new, 2)
    restored = convert.restore(xyz, table, 0.1, voxel_map, cls, inst, votes, outside)
    gone = convert.point_keys(xyz, 0.1) == floor
    survivors = np.flatnonzero(~gone)
    assert restored["dropped"] == int(gone.sum()) and restored["added"] == 1
    assert np.array_equal(restored["xyz"][:-1], xyz[survivors]) and np.allclose(restored["xyz"][-1], 3.05)
    expected = cls[survivors].copy()
    in_wall = convert.point_keys(xyz[survivors], 0.1) == wall
    expected[in_wall & ~outside[survivors]] = 5
    assert restored["cls"].tolist() == expected.tolist() + [2]
    assert restored["relabeled"] == 9 and restored["relabeled_voxels"] == 1
    assert restored["inst"][:-1][in_wall & ~outside[survivors]].tolist() == [0] * 9
    assert restored["table"]["intensity"][:-1].tolist() == table["intensity"][survivors].tolist()


def test_classes_decide_what_a_grid_shows():
    classes = labels.ClassList("indoor")
    keys = pack(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 5], [3, 0, 5], [0, 0, 5]]))
    cls = np.array([1, 1, 2, 7, 0], np.uint16)
    obstacles, free = convert.split_by_role(keys, cls, classes)
    assert sorted(obstacles.tolist()) == sorted(keys[[2, 4]].tolist()) and sorted(free.tolist()) == sorted(keys[:2].tolist())
    grid = convert.voxels_to_grid(obstacles, 0.1, 0.3, 1.0, free_keys=free)
    assert grid.cells[0].tolist() == [OCCUPIED, FREE, OCCUPIED] and grid.counts()[UNKNOWN] == 0


def test_raw_recordings_take_poses_from_gnss_and_calibration(tmp_path):
    drive = tmp_path / "2011_01_01" / "2011_01_01_drive_0001_sync"
    scans, oxts = drive / "velodyne_points" / "data", drive / "oxts" / "data"
    scans.mkdir(parents=True)
    oxts.mkdir(parents=True)
    (tmp_path / "2011_01_01" / "calib_imu_to_velo.txt").write_text("calib_time: x\nR: 1 0 0 0 1 0 0 0 1\nT: -0.8 0.3 -0.8\n")
    wall = np.column_stack([np.linspace(-20, 20, 400), np.full(400, 6.0), np.linspace(-1, 1, 400)])
    lat0, lon0 = 49.0, 8.4
    metres_per_degree = 6378137.0 * np.pi / 180 * np.cos(np.radians(lat0))
    for index in range(3):
        yaw = 0.1 * index
        east = 2.0 * index
        rotation = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
        sensor = np.array([east, 0.0, 0.0]) + rotation @ np.array([0.8, -0.3, 0.8])
        local = (wall - sensor) @ rotation
        np.column_stack([local, np.zeros(400)]).astype("<f4").tofile(str(scans / f"{index:010d}.bin"))
        row = [lat0, lon0 + east / metres_per_degree, 100.0, 0.0, 0.0, yaw] + [0.0] * 24
        (oxts / f"{index:010d}.txt").write_text(" ".join(f"{v:.12f}" for v in row) + "\n")
    for chosen in (drive, scans):
        sequence = frames.Sequence(str(chosen))
        assert sequence.folder == str(drive) and len(sequence) == 3
        xyz, _, starts = sequence.merge([0, 1, 2])
        assert np.abs(xyz[:400] - xyz[800:]).max() < 0.02 and np.abs(xyz[:400] - xyz[400:800]).max() < 0.02
    assert sequence.label_path(2).endswith(os.path.join("2011_01_01_drive_0001_sync", "labels", "0000000002.label"))


def test_frames_from_any_dataset_layout(tmp_path):
    """Timestamp-named PCD frames with a denser TUM trajectory, in natural order, plus other pose layouts."""
    folder = tmp_path / "export"
    folder.mkdir()
    wall = np.column_stack([np.linspace(-10, 10, 200), np.full(200, 4.0), np.linspace(0, 2, 200)])
    stamps = [1700000000.0 + 0.1 * i for i in (2, 10, 25)]
    speed = 3.0
    for stamp in stamps:
        x = speed * (stamp - 1700000000.0)
        formats.save_cloud(str(folder / f"scan_{stamp:.6f}.pcd"), wall - [x, 0, 0])
    trajectory = ["# timestamp tx ty tz qx qy qz qw"]
    trajectory += [f"{1700000000.0 + 0.05 * k:.6f} {speed * 0.05 * k:.6f} 0 0 0 0 0 1" for k in range(0, 61)]
    (folder / "trajectory.tum").write_text("\n".join(trajectory) + "\n")
    sequence = frames.Sequence(str(folder))
    assert sequence.layout == "folder" and sequence.pose_source == "trajectory.tum"
    xyz, _, _ = sequence.merge([0, 1, 2])
    assert np.abs(xyz[:200] - xyz[400:]).max() < 1e-3 and np.abs(xyz[:200] - xyz[200:400]).max() < 1e-3

    numbered = tmp_path / "numbered"
    numbered.mkdir()
    for index in (1, 2, 10):
        formats.save_cloud(str(numbered / f"frame_{index}.pcd"), wall)
    (numbered / "poses.csv").write_text("x,y,z,roll,pitch,yaw\n0,0,0,0,0,0\n1,0,0,0,0,0\n2,0,0,0,0,1.5707963\n")
    sequence = frames.Sequence(str(numbered))
    assert sequence.names == ["frame_1", "frame_2", "frame_10"]
    assert np.allclose(frames.apply(sequence.poses[2], np.array([[1.0, 0, 0]])), [[2, 1, 0]], atol=1e-6)
    sequence.drop_poses()
    assert sequence.poses is None and len(sequence.merge([0, 2])[0]) == 400

    matrices = tmp_path / "poses16.txt"
    matrices.write_text("1 0 0 5 0 1 0 0 0 0 1 0 0 0 0 1\n" * 3)
    poses, times = frames.read_poses(str(matrices))
    assert times is None and np.allclose(poses[:, 0, 3], 5)
    assert frames.name_time("1700000000123456789") == pytest.approx(1700000000.123456789)
    assert frames.name_time("cloud_1700000000.25") == pytest.approx(1700000000.25)

    scan = tmp_path / "n015.pcd.bin"
    np.arange(50, dtype="<f4").tofile(str(scan))
    xyz, table = formats.read_cloud(str(scan))
    assert table.dtype.names == ("x", "y", "z", "intensity", "ring") and len(xyz) == 10
