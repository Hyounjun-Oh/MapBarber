"""Every file in demo/ opens as the intended map type; the deliberately broken ones fail with a clear message."""
import os

import numpy as np
import pytest

from mapbarber import formats, grid

DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo")
pytestmark = pytest.mark.skipif(not os.path.isdir(DEMO), reason="demo/ not present")


def path(name):
    return os.path.join(DEMO, name)


def test_voxel_variants_agree():
    reference, resolution = formats.load_voxels(path("office_octomap.bt"))
    assert resolution == pytest.approx(0.05) and len(reference) > 100_000
    for name in ("office_octomap_with_free.bt", "office_color.ot", "office_octomap.bt.bak_20250101_090000",
                 "office_voxels.npz"):
        assert formats.kind(path(name)) == formats.VOXEL
        keys, _ = formats.load_voxels(path(name))
        assert np.array_equal(keys, reference), name


def test_point_clouds():
    expected = {"map_cloud.pcd": ("x", "y", "z", "intensity", "rgb"), "depth_frame.pcd": ("x", "y", "z", "rgb"),
                "lidar_sweep.ply": ("x", "y", "z", "intensity", "ring", "time"),
                "colored_points.xyz": ("x", "y", "z", "red", "green", "blue"), "survey_points.csv": None,
                "cloud_points.npy": None}
    for name, fields in expected.items():
        assert formats.kind(path(name)) == formats.CLOUD
        xyz, table = formats.read_cloud(path(name))
        assert len(xyz) > 100
        assert (table.dtype.names if table is not None else None) == fields, name
    xyz, _ = formats.read_cloud(path("depth_frame.pcd"))
    assert len(xyz) == 320 * 240 and 0 < np.isfinite(xyz).all(axis=1).sum() < len(xyz)


def test_grids():
    warehouse = grid.load(path("warehouse_map.yaml"))
    assert warehouse.shape == (800, 1000) and warehouse.origin == (-25.0, -20.0, 0.0)
    mask = grid.load(path("keepout_mask.yaml"))
    assert mask.meta["mode"] == "raw" and mask.counts() == [23200, 4800, 2000]


def test_png_grid_with_negate():
    pytest.importorskip("vtkmodules")
    lab_yaml, lab_png = grid.load(path("lab_map.yaml")), grid.load(path("lab_map.png"))
    assert lab_yaml.meta["negate"] == 1 and lab_yaml.origin[2] == pytest.approx(0.35)
    assert np.array_equal(lab_yaml.cells, lab_png.cells)


@pytest.mark.parametrize("name, message", [("broken_truncated.bt", "truncated"), ("not_a_map.yaml", "not a map"),
                                           ("not_points.txt", "no x, y, z")])
def test_broken_files(name, message):
    with pytest.raises(ValueError, match=message):
        if formats.kind(path(name)) == formats.GRID:
            grid.load(path(name))
        elif formats.kind(path(name)) == formats.VOXEL:
            formats.load_voxels(path(name))
        else:
            formats.read_cloud(path(name))


def test_drive_sequence_and_its_predictions():
    from mapbarber import frames, labels
    sequence = frames.Sequence(path("drive"))
    assert len(sequence) == 16 and sequence.poses is not None
    classes = labels.ClassList.load(path(os.path.join("drive", "labels.yaml")))
    assert classes.role(1) == labels.FREE_ROLE and classes.role(7) == labels.IGNORE and classes.dominant() == [7]
    for index in (0, 15):
        xyz, table = sequence.load(index)
        guess, _ = formats.read_label_file(path(os.path.join("drive", "predictions", sequence.names[index] + ".label")), len(xyz))
        assert len(xyz) > 8000 and set(np.unique(guess)) <= set(classes.numbers())
    merged, _, _ = sequence.merge([0, 15])
    assert np.abs(merged[:, 1]).max() < 10
