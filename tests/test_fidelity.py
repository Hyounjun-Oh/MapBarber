"""Saving keeps what the file held: free space, occupancy values, colours, point fields, pixel values."""
import numpy as np
import pytest
from scipy import ndimage

from mapbarber import convert, formats, grid, loss, octree
from mapbarber.__main__ import main
from mapbarber.grid import FREE, OCCUPIED, UNKNOWN, GridMap
from mapbarber.voxels import OFFSET, pack


def leaves_for(cells, levels, values, colours=None, tree_id="OcTree"):
    bases = octree.morton_encode(np.asarray(cells) + OFFSET)
    return octree.Leaves(bases, np.asarray(levels), np.asarray(values, np.float32), colours, tree_id)


def free_cells(leaves):
    return int((8 ** leaves.levels[leaves.free]).sum())


def test_binary_octree_keeps_free_space_around_edits(tmp_path):
    path = str(tmp_path / "map.bt")
    occupied = pack(np.array([[0, 0, 0], [1, 0, 0]]))
    free = leaves_for([[8, 8, 8], [16, 0, 0]], [3, 0], [octree.FREE_LOG_ODDS] * 2)
    octree.write_bt(path, occupied, 0.1, free)
    keys, _, leaves = octree.read(path, "bt")
    assert np.array_equal(keys, occupied) and free_cells(leaves) == 513

    inside = pack(np.array([[9, 10, 11]]))
    octree.write_bt(path, np.union1d(occupied[:1], inside), 0.1, leaves)
    keys, _, leaves = octree.read(path, "bt")
    assert np.array_equal(keys, np.union1d(occupied[:1], inside))
    assert free_cells(leaves) == 512 and leaves.find(octree._codes_from_keys(inside))[0] == -1
    assert not loss.voxel_losses(leaves, "bt") and loss.voxel_losses(leaves, "pcd") == [(loss.FREE_SPACE, "")]


def test_full_octree_keeps_values_and_colours(tmp_path):
    path = str(tmp_path / "map.ot")
    cells = np.array([[0, 0, 0], [1, 0, 0], [5, 5, 5], [-3, 2, 7]])
    colours = np.array([[10, 20, 30], [40, 50, 60], [70, 80, 90], [0, 0, 0]], np.uint8)
    source = leaves_for(cells, [0, 0, 0, 0], [0.4, 2.2, 3.5, -0.7], colours, "ColorOcTree")
    keys = pack(cells[:3])
    octree.write_ot(path, np.union1d(keys, pack(np.array([[30, 30, 30]]))), 0.05, source)
    loaded, _, leaves = octree.read(path, "ot")
    assert leaves.tree_id == "ColorOcTree" and len(loaded) == 4
    row = leaves.find(octree._codes_from_keys(keys))
    assert np.allclose(np.sort(leaves.values[row]), [0.4, 2.2, 3.5])
    assert sorted(map(tuple, leaves.colours[row])) == sorted(map(tuple, colours[:3]))
    fresh = leaves.find(octree._codes_from_keys(pack(np.array([[30, 30, 30]]))))
    assert leaves.values[fresh[0]] == octree.OCCUPIED_LOG_ODDS and leaves.colours[fresh[0]].tolist() == [255] * 3
    assert leaves.values[leaves.free].tolist() == [np.float32(-0.7)]
    assert not loss.voxel_losses(leaves, "ot")
    assert {what for what, _ in loss.voxel_losses(leaves, "bt")} == {loss.VALUES, loss.COLOURS}
    assert octree.read_ot(path)[1] == 0.05


def test_equal_siblings_merge_only_when_their_values_agree(tmp_path):
    path = str(tmp_path / "block.ot")
    block = np.stack(np.meshgrid(*[np.arange(2)] * 3, indexing="ij"), -1).reshape(-1, 3)
    octree.write_ot(path, pack(block), 0.1, leaves_for(block, [0] * 8, [1.0] * 8))
    assert len(octree.read(path, "ot")[2]) == 1
    octree.write_ot(path, pack(block), 0.1, leaves_for(block, [0] * 8, [1.0] * 7 + [2.0]))
    assert len(octree.read(path, "ot")[2]) == 8


def test_scalar_point_fields_survive_next_to_wide_ones(tmp_path):
    dtype = np.dtype([("x", "f4"), ("y", "f4"), ("z", "f4"), ("intensity", "f4"), ("ring", "u2"),
                      ("stamp", "u8"), ("normal", "f4", (3,))])
    table = np.zeros(5, dtype)
    table["x"], table["intensity"], table["ring"] = np.arange(5), np.arange(5) * 0.5, np.arange(5)
    xyz = formats._columns(table)
    pcd, ply = str(tmp_path / "scan.pcd"), str(tmp_path / "scan.ply")
    formats.save_cloud(pcd, xyz, table)
    assert formats.read_cloud(pcd)[1].tobytes() == table.tobytes()
    assert not loss.cloud_losses(table, "pcd")
    formats.save_cloud(ply, xyz, table)
    back = formats.read_cloud(ply)[1]
    assert back.dtype.names == ("x", "y", "z", "intensity", "ring")
    assert back["intensity"].tolist() == table["intensity"].tolist() and back["ring"].tolist() == table["ring"].tolist()
    assert loss.cloud_losses(table, "ply") == [(loss.FIELDS, "stamp, normal")]
    assert loss.cloud_losses(table, "xyz") == [(loss.FIELDS, "intensity, ring, stamp, normal")]


def test_pcd_viewpoint_and_layout_are_kept(tmp_path):
    source, out = tmp_path / "frame.pcd", str(tmp_path / "out.pcd")
    rows = "\n".join(f"{i} {i} 1" for i in range(6))
    source.write_text("VERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH 3\nHEIGHT 2\n"
                      f"VIEWPOINT 1 2 3 0.5 0.5 0.5 0.5\nPOINTS 6\nDATA ascii\n{rows}\n")
    xyz, table = formats.read_cloud(str(source))
    formats.save_cloud(out, xyz, table)
    header = open(out, "rb").read().split(b"DATA")[0].decode()
    assert "VIEWPOINT 1 2 3 0.5 0.5 0.5 0.5" in header and "WIDTH 3\nHEIGHT 2" in header
    formats.save_cloud(out, xyz[:4], table[:4])
    header = open(out, "rb").read().split(b"DATA")[0].decode()
    assert "VIEWPOINT 1 2 3 0.5 0.5 0.5 0.5" in header and "WIDTH 4\nHEIGHT 1" in header


def test_ply_faces_are_reported(tmp_path):
    mesh = tmp_path / "mesh.ply"
    mesh.write_text("ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
                    "element face 1\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n")
    xyz, table = formats.read_cloud(str(mesh))
    assert len(xyz) == 3 and loss.cloud_losses(table, "ply") == [(loss.ELEMENTS, "face")]
    assert loss.cloud_losses(table[:2], "pcd") == [(loss.ELEMENTS, "face")]


def test_xyz_text_keeps_colours(tmp_path):
    source, out = tmp_path / "c.xyz", str(tmp_path / "d.xyz")
    source.write_text("0 0 0 255 0 0\n1 2 3 0 128 255\n")
    xyz, table = formats.read_cloud(str(source))
    formats.save_cloud(out, xyz, table)
    assert formats.read_cloud(out)[1]["blue"].tolist() == [0, 255] and not loss.cloud_losses(table, "xyz")


@pytest.mark.parametrize("mode", ["trinary", "scale", "raw"])
def test_untouched_grid_cells_keep_their_pixel_value(tmp_path, mode):
    pixels = np.array([[0, 30, 90, 140], [205, 220, 254, 255], [100, 17, 60, 250]], np.uint8)
    if mode == "raw":
        pixels = np.array([[0, 30, 90, 100], [255, 50, 7, 66], [100, 17, 60, 99]], np.uint8)
    grid.write_pgm(str(tmp_path / "m.pgm"), pixels)
    (tmp_path / "m.yaml").write_text(f"image: m.pgm\nmode: {mode}\nresolution: 0.05\norigin: [0, 0, 0]\n"
                                     "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n")
    loaded = grid.load(str(tmp_path / "m.yaml"))
    grid.save(str(tmp_path / "same.yaml"), loaded)
    assert np.array_equal(grid.read_pgm(str(tmp_path / "same.pgm")), pixels)

    before = loaded.snapshot()
    loaded.cells[0, 0] = OCCUPIED if loaded.cells[0, 0] != OCCUPIED else FREE
    loaded.commit(before)
    grid.save(str(tmp_path / "edit.yaml"), loaded)
    saved = grid.read_pgm(str(tmp_path / "edit.pgm"))
    changed = saved != pixels
    assert changed.sum() == 1 and changed[2, 0]
    assert np.array_equal(grid.load(str(tmp_path / "edit.yaml")).cells, loaded.cells)

    loaded.cells[:] = UNKNOWN
    loaded.cells[1, 1:3] = FREE
    assert loaded.trim() and loaded.pixels.shape == loaded.cells.shape == (1, 2)
    loaded.undo()


def test_yaml_comment_marks_inside_quotes_are_kept(tmp_path):
    grid.write_pgm(str(tmp_path / "floor #2.pgm"), np.full((2, 2), 254, np.uint8))
    (tmp_path / "m.yaml").write_text('image: "floor #2.pgm"  # second floor\nresolution: 0.1 # metres\norigin: [1, 2, 0]\n')
    loaded = grid.load(str(tmp_path / "m.yaml"))
    assert loaded.shape == (2, 2) and loaded.resolution == 0.1 and loaded.origin[:2] == (1.0, 2.0)


@pytest.mark.parametrize("degrees", [0, 15, 30, 45, 90, 117])
def test_rotated_wall_stays_closed(degrees):
    cells = np.full((40, 40), FREE, np.uint8)
    cells[20, 2:38] = OCCUPIED
    keys, resolution = convert.grid_to_voxels(GridMap(cells, 0.05, (1.0, -2.0, np.radians(degrees))), 0.05)
    from mapbarber.voxels import unpack
    flat = unpack(keys)[:, :2]
    image = np.zeros(flat.max(axis=0) - flat.min(axis=0) + 1, bool)
    image[tuple((flat - flat.min(axis=0)).T)] = True
    assert ndimage.label(image)[1] == 1
    length = np.hypot(*(flat.max(axis=0) - flat.min(axis=0))) * resolution
    assert abs(length - 36 * 0.05) < 0.15
    if degrees % 90 == 0:
        assert len(keys) == 36


def test_cli_says_what_the_output_cannot_hold(tmp_path, capsys):
    source = str(tmp_path / "map.bt")
    octree.write_bt(source, pack(np.array([[0, 0, 0]])), 0.1, leaves_for([[4, 4, 4]], [1], [octree.FREE_LOG_ODDS]))
    assert main([source, "--info"]) == 0
    assert "free cells  8" in capsys.readouterr().out
    assert main([source, "-o", str(tmp_path / "copy.bt")]) == 0
    assert "not stored" not in capsys.readouterr().err
    assert free_cells(octree.read(str(tmp_path / "copy.bt"), "bt")[2]) == 8
    assert main([source, "-o", str(tmp_path / "points.pcd")]) == 0
    assert "Free space" in capsys.readouterr().err
