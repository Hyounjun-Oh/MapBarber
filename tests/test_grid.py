import numpy as np
import pytest

from mapbarber import convert, grid
from mapbarber.grid import FREE, OCCUPIED, UNKNOWN
from mapbarber.voxels import pack, unpack


def sample():
    cells = np.full((40, 60), UNKNOWN, np.uint8)
    cells[5:35, 10:50] = FREE
    cells[5, 10:50] = OCCUPIED
    cells[20, 30] = OCCUPIED
    return grid.GridMap(cells, 0.05, (-1.0, 2.0, 0.0))


def test_yaml_and_pgm_round_trip(tmp_path):
    original = sample()
    path = str(tmp_path / "floor.yaml")
    grid.save(path, original)
    loaded = grid.load(path)
    assert np.array_equal(loaded.cells, original.cells)
    assert loaded.resolution == pytest.approx(0.05) and loaded.origin == pytest.approx((-1.0, 2.0, 0.0))
    bare = grid.load(str(tmp_path / "floor.pgm"))
    assert np.array_equal(bare.cells, original.cells)


def test_thresholds_follow_map_server(tmp_path):
    pixels = np.array([[0, 100, 205, 254]], np.uint8)
    assert grid.classify(pixels, {}).tolist() == [[OCCUPIED, UNKNOWN, UNKNOWN, FREE]]
    assert grid.classify(pixels, {"negate": 1}).tolist() == [[FREE, UNKNOWN, OCCUPIED, OCCUPIED]]
    raw = np.array([[0, 100, 50, 255]], np.uint8)
    assert grid.classify(raw, {"mode": "raw"}).tolist() == [[FREE, OCCUPIED, UNKNOWN, UNKNOWN]]


@pytest.mark.parametrize("meta", [{"free_thresh": 0.25}, {"negate": 1}, {"mode": "raw"}])
def test_render_reads_back(meta):
    cells = np.array([[FREE, OCCUPIED, UNKNOWN]], np.uint8)
    assert np.array_equal(grid.classify(grid.render(cells, meta), meta), cells)


def test_painting_and_undo():
    g = sample()
    before = g.snapshot()
    g.line((10, 12), (10, 40), 3, OCCUPIED)
    g.rectangle((25, 15), (30, 20), UNKNOWN)
    assert g.commit(before) > 0 and g.dirty
    assert (g.cells[9:12, 12:41] == OCCUPIED).all() and (g.cells[25:31, 15:21] == UNKNOWN).all()
    assert g.undo() and not g.dirty and g.redo() and g.dirty
    assert g.commit(g.snapshot()) == 0


def test_flood_speckles_and_trim():
    g = sample()
    cleared, groups = g.clear_speckles(1)
    assert (cleared, groups) == (1, 1) and g.cells[20, 30] == FREE
    g.flood(20, 30, UNKNOWN)
    assert g.counts()[FREE] == 0
    g = sample()
    assert g.trim() and g.shape == (30, 40)
    assert g.origin == pytest.approx((-1.0 + 10 * 0.05, 2.0 + 5 * 0.05, 0.0))
    assert g.world(0, 0) == pytest.approx((-0.5 + 0.025, 2.25 + 0.025))


def test_conversions():
    keys = pack(np.array([[0, 0, 0], [0, 0, 5], [3, 2, 1], [-2, 4, 1]]))
    flat = convert.voxels_to_grid(keys, 0.1, z_low=0.0, z_high=0.3)
    assert flat.shape == (5, 6) and flat.counts()[OCCUPIED] == 3
    assert flat.origin == pytest.approx((-0.2, 0.0, 0.0))
    walls, resolution = convert.grid_to_voxels(flat, 0.3)
    cells = unpack(walls)
    assert resolution == pytest.approx(0.1) and len(walls) == 9
    assert {tuple(c) for c in cells[:, :2].tolist()} == {(0, 0), (3, 2), (-2, 4)}
