"""Following boxed objects between frames: box overlap, point alignment and the score made of both."""
import numpy as np
import pytest

from mapbarber import boxes, tracking


def car(rng, centre, yaw, count=800, visible=None):
    """Points on the surface of a 4 x 1.8 x 1.5 m box; `visible` keeps only the side facing that direction."""
    side = rng.integers(0, 3, count)
    local = rng.uniform([-2, -0.9, -0.75], [2, 0.9, 0.75], (count, 3))
    for axis, half in enumerate((2.0, 0.9, 0.75)):
        pick = side == axis
        local[pick, axis] = half * rng.choice([-1, 1], int(pick.sum()))
    if visible is not None:
        local = local[local @ np.asarray(visible, float) > -0.2]
    c, s = np.cos(yaw), np.sin(yaw)
    turned = np.column_stack([c * local[:, 0] - s * local[:, 1], s * local[:, 0] + c * local[:, 1], local[:, 2]])
    return turned + centre


def test_iou_of_upright_boxes():
    a = {"center": [0, 0, 0], "size": [4, 2, 2], "yaw": 0.0}
    assert tracking.iou(a, a) == pytest.approx(1.0)
    assert tracking.iou(a, dict(a, center=[2, 0, 0])) == pytest.approx(1 / 3)
    assert tracking.iou(a, dict(a, center=[0, 0, 1])) == pytest.approx(1 / 3)
    assert tracking.iou(a, dict(a, center=[10, 0, 0])) == 0.0
    turned = dict(a, size=[2, 2, 2], yaw=np.pi / 4)
    square = dict(a, size=[2, 2, 2])
    assert tracking.iou(square, turned) == pytest.approx(0.7071, abs=1e-3)
    assert tracking.iou(a, dict(a, yaw=np.pi)) == pytest.approx(1.0)


def test_alignment_recovers_a_turn_and_a_shift():
    rng = np.random.default_rng(0)
    before = car(rng, [0, 0, 0.75], 0.0)
    c, s = np.cos(0.12), np.sin(0.12)
    after = before @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]).T + [0.6, -0.2, 0.05]
    transform, fitness, rms = tracking.align(before, after + rng.normal(0, 0.005, after.shape), reach=0.5)
    assert fitness > 0.99 and rms < 0.03
    assert np.allclose(transform[:3, 3], [0.6, -0.2, 0.05], atol=0.03)
    assert np.arctan2(transform[1, 0], transform[0, 0]) == pytest.approx(0.12, abs=0.01)
    assert tracking.align(before[:2], after, 0.5)[1] == 0.0


def test_follow_a_moving_object_and_lose_one_that_left():
    rng = np.random.default_rng(1)
    first = car(rng, [10, 5, 0.75], 0.3)
    box = boxes.fit(first, cls=10, instance=4)
    c, s = np.cos(0.05), np.sin(0.05)
    moved = (first - [10, 5, 0.75]) @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]).T + [11.0, 5.4, 0.75]
    other = car(rng, [30, 5, 0.75], 0.0)
    clutter = rng.uniform([0, -10, 0.2], [40, 20, 3], (300, 3))
    scene = np.vstack([moved + rng.normal(0, 0.01, moved.shape), other, clutter])
    found = tracking.follow(box, first, scene)
    assert found is not None and found["score"] > 0.8 and found["iou"] > 0.7 and found["fitness"] > 0.9
    assert np.allclose(found["box"]["center"], [11.0, 5.4, 0.75], atol=0.08)
    assert np.allclose(found["box"]["size"], box["size"]) and found["box"]["instance"] == 4
    assert (found["members"] < len(moved)).mean() > 0.97 and np.isin(np.arange(len(moved)), found["members"]).mean() > 0.95
    assert np.allclose(found["shift"], [1.0, 0.4, 0.0], atol=0.08)

    assert tracking.follow(box, first, np.vstack([other, clutter])) is None

    far = (first - [10, 5, 0.75]) + [14.5, 5.0, 0.75]
    assert tracking.follow(box, first, far, reach=1.0) is None
    again = tracking.follow(box, first, far, reach=1.0, shift=np.array([4.3, 0.0, 0.0]))
    assert again is not None and again["score"] > 0.8


def test_a_half_hidden_object_keeps_its_size_and_scores_lower():
    rng = np.random.default_rng(2)
    first = car(rng, [8, 0, 0.75], 0.0, count=1500)
    box = boxes.fit(first, cls=10, instance=1)
    partial = car(rng, [8.8, 0.1, 0.75], 0.0, count=1500, visible=[0, -1, 0])
    found = tracking.follow(box, first, partial)
    assert found is not None and np.allclose(found["box"]["size"], box["size"])
    assert np.allclose(found["box"]["center"][:2], [8.8, 0.1], atol=0.25)
    full = tracking.follow(box, first, first + [0.8, 0.1, 0.0])
    assert full["score"] > found["score"] > 0.3
