import numpy as np
import pytest

from mapbarber import formats, octree
from mapbarber.voxels import centers, pack, unpack


@pytest.fixture
def keys():
    rng = np.random.default_rng(7)
    scattered = rng.integers(-60, 60, size=(4000, 3))
    block = np.stack(np.meshgrid(np.arange(8, 24), np.arange(-16, 0), np.arange(0, 16), indexing="ij"), -1).reshape(-1, 3)
    return np.unique(pack(np.vstack([scattered, block])))


@pytest.mark.parametrize("ext", ["bt", "ot", "pcd", "ply", "xyz", "csv", "npy", "npz"])
def test_voxel_round_trip(tmp_path, keys, ext):
    path = str(tmp_path / f"map.{ext}")
    formats.save_voxels(path, keys, 0.05)
    loaded, resolution = formats.load_voxels(path, resolution=0.05)
    assert resolution == pytest.approx(0.05)
    assert np.array_equal(loaded, keys)


def test_octree_prunes_full_blocks(tmp_path):
    r = np.arange(0, 16)
    cube = pack(np.stack(np.meshgrid(r, r, r, indexing="ij"), -1).reshape(-1, 3))
    path = str(tmp_path / "cube.bt")
    octree.write_bt(path, cube, 0.05)
    with open(path, "rb") as f:
        size = int(next(line for line in f.read().split(b"\n") if line.startswith(b"size")).split()[1])
    assert size < 32
    assert np.array_equal(octree.read_bt(path)[0], cube)


def test_empty_octree(tmp_path):
    for ext in ("bt", "ot"):
        path = str(tmp_path / f"empty.{ext}")
        formats.save_voxels(path, np.zeros(0, np.int64), 0.1)
        loaded, resolution = formats.load_voxels(path)
        assert len(loaded) == 0 and resolution == pytest.approx(0.1)


def test_kind_detection(tmp_path, keys):
    backup = str(tmp_path / "map.bt.bak_20240101")
    octree.write_bt(backup, keys, 0.05)
    assert formats.detect(backup) == "bt" and formats.kind(backup) == formats.VOXEL
    archive, points = str(tmp_path / "voxels.npz"), str(tmp_path / "points.npz")
    formats.save_voxels(archive, keys, 0.05)
    formats.save_cloud(points, centers(keys, 0.05))
    assert formats.kind(archive) == formats.VOXEL
    assert formats.kind(points) == formats.CLOUD
    assert formats.kind("scan.pcd") == formats.CLOUD
    assert formats.kind("floor.yaml") == formats.GRID and formats.kind("floor.pgm") == formats.GRID
    with pytest.raises(ValueError):
        formats.kind("notes.docx")


@pytest.mark.parametrize("ext", ["pcd", "ply"])
def test_cloud_keeps_every_field(tmp_path, ext):
    table = np.zeros(50, np.dtype([("x", "f4"), ("y", "f4"), ("z", "f4"), ("intensity", "f4"), ("ring", "u2")]))
    rng = np.random.default_rng(1)
    for name in ("x", "y", "z", "intensity"):
        table[name] = rng.normal(size=50)
    table["ring"] = np.arange(50)
    path = str(tmp_path / f"scan.{ext}")
    formats.save_cloud(path, formats._columns(table), table)
    xyz, loaded = formats.read_cloud(path)
    assert loaded.dtype.names == table.dtype.names
    assert np.array_equal(loaded["ring"], table["ring"]) and np.allclose(loaded["intensity"], table["intensity"])
    assert np.allclose(xyz, formats._columns(table))


def test_ascii_point_files(tmp_path):
    points = np.array([[0.01, 0.02, 0.03], [1.0, -1.0, 0.5], [0.26, 0.26, 0.26]])
    pcd = tmp_path / "cloud.pcd"
    pcd.write_text("# .PCD v0.7\nVERSION 0.7\nFIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n"
                   "WIDTH 3\nHEIGHT 1\nPOINTS 3\nDATA ascii\n" + "".join(f"{x} {y} {z} 1.0\n" for x, y, z in points))
    ply = tmp_path / "cloud.ply"
    ply.write_text("ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
                   "property uchar red\nelement face 0\nend_header\n" + "".join(f"{x} {y} {z} 255\n" for x, y, z in points))
    txt = tmp_path / "cloud.txt"
    txt.write_text("x, y, z\n" + "".join(f"{x}, {y}, {z}\n" for x, y, z in points))
    for path in (pcd, ply, txt):
        xyz, _ = formats.read_cloud(str(path))
        assert np.allclose(xyz, points, atol=1e-6)


def test_resolution_estimate(keys):
    assert formats.estimate_resolution(centers(keys, 0.05)) == pytest.approx(0.05)


def test_pack_round_trip():
    ijk = np.array([[-32768, 0, 32767], [1, -1, 0]])
    assert np.array_equal(unpack(pack(ijk)), ijk)


def test_damaged_and_empty_files_raise_clear_errors(tmp_path, keys):
    whole = str(tmp_path / "map.bt")
    octree.write_bt(whole, keys, 0.05)
    with open(whole, "rb") as f:
        data = f.read()
    cut = tmp_path / "cut.bt"
    cut.write_bytes(data[:len(data) // 2])
    with pytest.raises(ValueError, match="truncated"):
        formats.load_voxels(str(cut))
    notes = tmp_path / "notes.txt"
    notes.write_text("no numbers here\n")
    with pytest.raises(ValueError, match="no x, y, z"):
        formats.read_cloud(str(notes))


def test_xyz_text_with_colours(tmp_path):
    path = tmp_path / "coloured.xyz"
    path.write_text("0 0 0 255 0 0\n1 0 0 0 128 255\n")
    xyz, table = formats.read_cloud(str(path))
    assert xyz.shape == (2, 3)
    assert table["red"].tolist() == [255, 0] and table["green"].tolist() == [0, 128] and table["blue"].tolist() == [0, 255]
    out = str(tmp_path / "coloured.ply")
    formats.save_cloud(out, xyz, table)
    assert formats.read_cloud(out)[1]["blue"].tolist() == [0, 255]
    plain = tmp_path / "plain.xyz"
    plain.write_text("0 0 0\n1 2 3 7\n")
    assert formats.read_cloud(str(plain))[1] is None
