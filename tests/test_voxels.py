import numpy as np

from mapbarber.voxels import VoxelMap, pack, ray_pick


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
