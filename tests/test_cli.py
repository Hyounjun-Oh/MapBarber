import numpy as np
import pytest

from mapbarber import __main__ as cli
from mapbarber import formats, grid
from mapbarber.grid import FREE, OCCUPIED
from mapbarber.voxels import pack


@pytest.fixture
def voxel_file(tmp_path):
    room = [(x, y, z) for x in range(20) for y in range(20) for z in range(5) if x in (0, 19) or y in (0, 19)]
    keys = pack(np.array(room + [(50, 50, 2)]))
    path = str(tmp_path / "room.bt")
    formats.save_voxels(path, keys, 0.1)
    return path


def test_info_and_island_removal(tmp_path, voxel_file, capsys):
    out = str(tmp_path / "clean.ot")
    assert cli.main([voxel_file, "--info", "--remove-islands", "2", "-o", out]) == 0
    text = capsys.readouterr().out
    assert "voxel map" in text and "removed 1 voxels in 1 islands" in text
    assert len(formats.load_voxels(out)[0]) == 76 * 5


def test_voxels_to_grid_and_back(tmp_path, voxel_file):
    yaml = str(tmp_path / "floor.yaml")
    cli.main([voxel_file, "--z-band", "0.0", "0.25", "-o", yaml])
    flat = grid.load(yaml)
    assert flat.counts()[OCCUPIED] == 77 and flat.shape == (51, 51)
    walls = str(tmp_path / "walls.bt")
    cli.main([yaml, "--wall-height", "0.3", "-o", walls])
    assert len(formats.load_voxels(walls)[0]) == 77 * 3


def test_cloud_outliers_and_voxelize(tmp_path):
    rng = np.random.default_rng(0)
    xyz = np.vstack([rng.uniform(0, 1, (3000, 3)), [[9.0, 9.0, 9.0]]])
    source = str(tmp_path / "scan.ply")
    formats.save_cloud(source, xyz)
    cleaned = str(tmp_path / "clean.pcd")
    cli.main([source, "--remove-outliers", "8", "3", "-o", cleaned])
    assert len(formats.read_cloud(cleaned)[0]) < len(xyz)
    voxels = str(tmp_path / "scan.bt")
    cli.main([cleaned, "-r", "0.25", "-o", voxels])
    keys, resolution = formats.load_voxels(voxels)
    assert resolution == pytest.approx(0.25) and len(keys) == 64


def test_grid_speckles(tmp_path):
    cells = np.full((30, 30), FREE, np.uint8)
    cells[10, 10] = OCCUPIED
    cells[0, :] = OCCUPIED
    source = str(tmp_path / "map.yaml")
    grid.save(source, grid.GridMap(cells, 0.05))
    out = str(tmp_path / "clean.yaml")
    cli.main([source, "--clear-speckles", "3", "-o", out])
    assert grid.load(out).counts()[OCCUPIED] == 30
