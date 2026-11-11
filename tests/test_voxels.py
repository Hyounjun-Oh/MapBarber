import numpy as np

from mapbarber.voxels import VoxelMap, pack, ray_pick, unpack


def block(low, high):
    r = np.arange(low, high)
    return pack(np.stack(np.meshgrid(r, r, r, indexing="ij"), -1).reshape(-1, 3))


def test_apply_undo_redo():
    vmap = VoxelMap(block(0, 4), 0.1)
    assert vmap.apply(add=pack([[10, 10, 10], [0, 0, 0]])) == (1, 0)
    assert vmap.apply(remove=block(0, 2)) == (0, 8)
    assert vmap.apply(remove=pack([[50, 50, 50]])) == (0, 0)
    assert vmap.changes() == (1, 8) and vmap.dirty
    assert vmap.undo() and vmap.undo() and not vmap.undo()
    assert not vmap.dirty
    assert vmap.redo() and vmap.redo() and not vmap.redo()
    assert len(vmap) == 64 + 1 - 8
    vmap.mark_saved()
    assert not vmap.dirty


def test_islands():
    speck = pack([[20, 20, 20], [21, 21, 21]])
    vmap = VoxelMap(np.concatenate([block(0, 4), speck, pack([[-9, 0, 0]])]), 0.1)
    keys, count = vmap.islands(2)
    assert count == 2 and len(keys) == 3
    keys, count = vmap.islands(1)
    assert count == 1 and np.array_equal(keys, pack([[-9, 0, 0]]))


def test_ray_pick_returns_entry_face():
    boxes = np.array([[0.5, 0.5, 0.5], [0.5, 0.5, 2.5]])
    hit = ray_pick(np.array([0.5, 0.5, 10.0]), np.array([0.0, 0.0, -1.0]), boxes, 0.5)
    assert hit == (1, 2, 1)
    hit = ray_pick(np.array([-5.0, 0.4, 0.6]), np.array([1.0, 0.0, 0.0]), boxes, 0.5)
    assert hit == (0, 0, -1)
    assert ray_pick(np.array([5.0, 5.0, 5.0]), np.array([0.0, 0.0, 1.0]), boxes, 0.5) is None


def test_chunks_follow_edits_and_track_changes():
    rng = np.random.default_rng(5)
    keys = np.unique(pack(rng.integers(-200, 200, size=(20000, 3))))
    vmap = VoxelMap(keys, 0.1)
    assert len(vmap) == len(keys) and np.array_equal(vmap.occupied, keys) and len(vmap.chunks) > 50
    probe = np.concatenate([keys[:100], pack([[999, 999, 999], [-300, 5, 5]])])
    assert vmap.contains(probe).tolist() == [True] * 100 + [False, False]
    assert sum(len(vmap.keys(chunk)) for chunk in vmap.chunks) == len(keys)

    new = pack([[1000, 1000, 1000], [63, 0, 0], [64, 0, 0], [-1, -1, -1]])
    new = new[~vmap.contains(new)]
    added, removed = vmap.apply(add=new, remove=keys[:500])
    assert (added, removed) == (len(new), 500) and len(vmap) == len(keys) + len(new) - 500
    assert vmap.changes() == (len(new), 500) and vmap.dirty
    assert np.array_equal(vmap.saved, keys)
    assert len(vmap.touched) >= 1 and all(isinstance(chunk, int) for chunk in vmap.touched)
    vmap.apply(remove=new[:1])
    vmap.apply(add=keys[:10])
    assert vmap.changes() == (len(new) - 1, 490)
    while vmap.undo():
        pass
    assert not vmap.dirty and np.array_equal(vmap.occupied, keys)
    while vmap.redo():
        pass
    expected = np.union1d(np.setdiff1d(keys, keys[10:500]), new[1:])
    assert np.array_equal(vmap.occupied, expected)
    low, high = vmap.bounds()
    cells = unpack(expected)
    assert np.array_equal(low, cells.min(axis=0)) and np.array_equal(high, cells.max(axis=0))
    emptied = VoxelMap(pack([[5, 5, 5]]), 0.1)
    emptied.apply(remove=pack([[5, 5, 5]]))
    assert not emptied.chunks and len(emptied) == 0 and emptied.bounds() is None
