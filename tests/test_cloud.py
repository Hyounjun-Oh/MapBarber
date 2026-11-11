import numpy as np

from mapbarber import cloud


def scene():
    rng = np.random.default_rng(3)
    dense = rng.uniform(0, 1, size=(2000, 3))
    stray = np.array([[5.0, 5.0, 5.0], [-4.0, 0.0, 2.0], [0.5, 9.0, 0.5]])
    return np.vstack([dense, stray])


def test_remove_undo_redo():
    points = cloud.PointCloud(scene())
    assert points.remove([0, 1, 2]) == 3 and points.remove([1, 2]) == 0
    assert len(points) == 2000 and points.dirty and points.removed() == 3
    assert points.undo() and not points.dirty and not points.undo()
    assert points.redo() and len(points.surviving()[0]) == 2000
    points.mark_saved()
    assert not points.dirty


def test_outlier_filters_find_strays():
    points = scene()
    strays = {2000, 2001, 2002}
    assert strays <= set(cloud.statistical_outliers(points, 8, 3.0).tolist())
    assert strays <= set(cloud.sparse_points(points, 0.5, 2).tolist())


def test_downsample_keeps_one_point_per_cell():
    points = scene()
    surplus = cloud.downsample_surplus(points, 0.25)
    kept = np.delete(points, surplus, axis=0)
    cells = np.floor(kept / 0.25).astype(int)
    assert len(np.unique(cells, axis=0)) == len(kept) == len(np.unique(np.floor(points / 0.25).astype(int), axis=0))


def test_pick_along_ray():
    points = np.array([[0.0, 0.0, 5.0], [0.0, 0.0, 2.0], [1.0, 0.0, 1.0]])
    origin, direction = np.zeros(3), np.array([0.0, 0.0, 1.0])
    assert cloud.pick_along_ray(origin, direction, points, 0.01) == 1
    assert cloud.pick_along_ray(origin, -direction, points, 0.01) is None
