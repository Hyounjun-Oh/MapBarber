"""Malformed input, extreme values and failed writes must end in a clear error, never in damage."""
import os

import numpy as np
import pytest

from mapbarber import __main__ as cli
from mapbarber import convert, formats, grid, octree
from mapbarber.grid import FREE, OCCUPIED, UNKNOWN, GridMap
from mapbarber.voxels import pack, voxelize


def test_cells_outside_the_grid_are_refused():
    with pytest.raises(ValueError, match="outside the supported range"):
        pack(np.array([[0, 0, 40000]]))
    with pytest.raises(ValueError, match="outside the supported range"):
        pack(np.array([[-32769, 0, 0]]))
    assert len(pack(np.array([[-32768, 0, 32767]]))) == 1
    far = GridMap(np.array([[OCCUPIED]], np.uint8), 0.05, (5000.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="outside the supported range"):
        convert.grid_to_voxels(far, 1.0)
    assert len(voxelize(np.array([[1e9, 0.0, 0.0], [0.1, 0.1, 0.1]]), 0.05)) == 1


@pytest.mark.parametrize("content", [b"P5", b"P5 3", b"P5\n# never ends", b"P5 3 3 255", b"P5 2 2 255\n\x00",
                                     b"P5 0 5 255\n", b"P5 x y 255\n", b"P2 2 2 255\n1 2 3", b"P5 999999 999999 255\n"])
def test_malformed_pgm_ends_in_an_error(tmp_path, content):
    path = tmp_path / "bad.pgm"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        grid.read_pgm(str(path))


def test_pgm_with_windows_line_endings(tmp_path):
    path = tmp_path / "crlf.pgm"
    path.write_bytes(b"P5\r\n2 2\r\n255\n" + bytes([0, 254, 205, 0]))
    assert grid.read_pgm(str(path)).tolist() == [[0, 254], [205, 0]]


def test_large_origin_and_fine_resolution_survive_saving(tmp_path):
    cells = np.full((4, 5), FREE, np.uint8)
    original = GridMap(cells, 0.0123456789, (123456.789012345, -987654.321098765, 0.123456789012345))
    path = str(tmp_path / "far.yaml")
    grid.save(path, original)
    loaded = grid.load(path)
    assert loaded.origin == original.origin and loaded.resolution == original.resolution


def test_yml_name_is_kept(tmp_path):
    path = str(tmp_path / "map.yml")
    grid.save(path, GridMap(np.full((3, 3), FREE, np.uint8), 0.05))
    assert sorted(os.listdir(tmp_path)) == ["map.pgm", "map.yml"]
    assert grid.load(path).shape == (3, 3)


def test_failed_save_leaves_the_previous_files_untouched(tmp_path, monkeypatch):
    path = str(tmp_path / "map.yaml")
    grid.save(path, GridMap(np.full((3, 3), FREE, np.uint8), 0.05))
    before = {name: (tmp_path / name).read_bytes() for name in os.listdir(tmp_path)}

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(grid, "render", broken)
    with pytest.raises(OSError):
        grid.save(path, GridMap(np.full((9, 9), OCCUPIED, np.uint8), 0.1))
    assert {name: (tmp_path / name).read_bytes() for name in os.listdir(tmp_path)} == before

    voxels = str(tmp_path / "map.bt")
    keys = pack(np.array([[1, 2, 3]]))
    octree.write_bt(voxels, keys, 0.05)
    good = open(voxels, "rb").read()
    monkeypatch.setattr(octree, "_preorder", broken)
    with pytest.raises(OSError):
        octree.write_bt(voxels, pack(np.array([[4, 5, 6], [7, 8, 9]])), 0.05)
    assert open(voxels, "rb").read() == good and not [n for n in os.listdir(tmp_path) if ".part" in n]


def test_projection_leaves_unobserved_cells_unknown():
    keys = pack(np.array([[0, 0, 0], [3, 2, 1]]))
    assert convert.voxels_to_grid(keys, 0.1).counts() == [0, 2, 10]
    assert convert.voxels_to_grid(keys, 0.1, empty=FREE).counts() == [10, 2, 0]
    assert UNKNOWN == 2


def test_cli_handles_nan_points_and_reports_errors(tmp_path, capsys):
    rng = np.random.default_rng(2)
    xyz = np.vstack([rng.uniform(0, 1, (500, 3)), [[np.nan, 0.0, 0.0]], [[7.0, 7.0, 7.0]]])
    source, out = str(tmp_path / "scan.xyz"), str(tmp_path / "clean.pcd")
    np.savetxt(source, xyz)
    assert cli.main([source, "--remove-outliers", "8", "3", "-o", out]) == 0
    cleaned, _ = formats.read_cloud(out)
    assert np.isfinite(cleaned).all() and len(cleaned) < 501
    assert cli.main([source, "-r", "0", "-o", str(tmp_path / "bad.bt")]) == 1
    assert "greater than zero" in capsys.readouterr().err


def test_resolution_is_written_exactly(tmp_path):
    path = str(tmp_path / "fine.bt")
    octree.write_bt(path, pack(np.array([[1, 2, 3]])), 0.0123456789)
    assert octree.read_bt(path)[1] == 0.0123456789
