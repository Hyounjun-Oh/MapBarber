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
    target = after + rng.normal(0, 0.005, after.shape)
    coarse, _, _ = tracking.align(before, target, reach=1.0)
    fine, fitness, rms = tracking.align(before @ coarse[:3, :3].T + coarse[:3, 3], target, reach=0.25)
    transform = fine @ coarse
    assert fitness > 0.99 and rms < 0.03
    assert np.allclose(transform[:3, 3], [0.6, -0.2, 0.05], atol=0.03)
    assert np.arctan2(transform[1, 0], transform[0, 0]) == pytest.approx(0.12, abs=0.01)
    assert tracking.align(before[:2], after, 0.5)[1] == 0.0
    capped, _, _ = tracking.align(before, target, reach=1.0, turn_limit=np.radians(3))
    assert abs(np.arctan2(capped[1, 0], capped[0, 0])) <= np.radians(3) + 1e-9


def seen_from(points, normals, sensor, limit=0.35):
    """Points of a surface whose side faces the sensor."""
    away = sensor - points
    away /= np.linalg.norm(away, axis=1, keepdims=True)
    return np.einsum("ij,ij->i", normals, away) > limit


def shell(rng, count=4000):
    """Surface points and outward normals of a 4 x 1.8 x 1.5 m box centred on the origin."""
    side = rng.integers(0, 3, count)
    sign = rng.choice([-1.0, 1.0], count)
    local = rng.uniform([-2, -0.9, -0.75], [2, 0.9, 0.75], (count, 3))
    normals = np.zeros((count, 3))
    for axis, half in enumerate((2.0, 0.9, 0.75)):
        pick = side == axis
        local[pick, axis] = half * sign[pick]
        normals[pick, axis] = sign[pick]
    return local, normals


def test_follow_a_moving_object_and_lose_one_that_left():
    rng = np.random.default_rng(1)
    first = car(rng, [10, 5, 0.75], 0.3)
    box = boxes.fit(first, cls=10, instance=4)
    c, s = np.cos(0.05), np.sin(0.05)
    moved = (first - [10, 5, 0.75]) @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]).T + [11.0, 5.4, 0.75]
    other = car(rng, [30, 5, 0.75], 0.0)
    clutter = rng.uniform([0, -10, 0.2], [40, 20, 3], (300, 3))
    scene = np.vstack([moved + rng.normal(0, 0.01, moved.shape), other, clutter])
    track = tracking.Track(box, first)
    found = track.follow(track.first, scene)
    assert found is not None and found["score"] > 0.75 and found["fitness"] > 0.9
    assert np.allclose(track.box(found["pose"])["center"], [11.0, 5.4, 0.75], atol=0.1)
    assert (found["members"] < len(moved)).mean() > 0.97 and np.isin(np.arange(len(moved)), found["members"]).mean() > 0.95
    assert tracking.Track(box, first).follow(track.first, np.vstack([other, clutter])) is None


def test_the_box_grows_to_the_whole_object_as_the_view_changes():
    """A car drives past the sensor: first only its front is seen, then its side, then its back."""
    rng = np.random.default_rng(3)
    local, normals = shell(rng)
    sensor = np.array([0.0, -9.0, 1.2])
    centres = [np.array([-15.0 + 1.5 * k, 0.0, 0.75]) for k in range(21)]
    frames = {}
    for index, centre in enumerate(centres):
        world = local + centre
        visible = world[seen_from(world, normals, sensor, limit=0.6)]
        frames[index] = visible + rng.normal(0, 0.01, visible.shape)
    first_box = boxes.fit(frames[0], cls=10, instance=7)
    assert min(first_box["size"][:2]) < 1.0, "the first view shows only one face"
    track = tracking.Track(first_box, frames[0])
    track.run(list(frames), 0, lambda frame: (np.arange(len(frames[frame])), frames[frame]), reach=2.0, gap=0.5)
    assert sorted(track.results) == list(frames), "every frame, the first included, is fitted against the finished model"
    for index, centre in enumerate(centres):
        box = track.box_in(index)
        assert np.allclose(box["size"], [4.0, 1.8, 1.5], atol=0.35), (index, box["size"])
        assert np.allclose(box["center"], centre, atol=0.3), (index, box["center"], centre)
        assert abs(np.sin(box["yaw"])) < 0.12 and np.cos(box["yaw"]) > 0, "the box points the way the car drives"
        assert len(track.results[index]["ids"]) >= 0.98 * len(frames[index]), f"frame {index}: points left unlabelled"
        assert track.results[index]["score"] > 0.5


def test_an_object_that_changes_shape_gets_a_box_per_frame():
    rng = np.random.default_rng(4)
    frames = {}
    for index in range(5):
        spread = 0.25 + 0.15 * (index % 2)
        frames[index] = rng.uniform([-spread, -0.25, 0.0], [spread, 0.25, 1.7], (300, 3)) + [3.0 + 0.4 * index, 1.0, 0.0]
    track = tracking.Track(boxes.fit(frames[0], cls=30, instance=2), frames[0], rigid=False)
    track.run(list(frames), 0, lambda frame: (np.arange(300), frames[frame]), gap=0.3)
    assert sorted(track.results) == list(frames)
    widths = [max(track.box_in(index)["size"][:2]) for index in frames]
    assert max(widths) - min(widths) > 0.2, "the box follows the changing shape"
    for index in frames:
        assert np.allclose(track.box_in(index)["center"][:2], [3.0 + 0.4 * index, 1.0], atol=0.15)
        assert len(track.results[index]["ids"]) == 300


def test_a_wall_beside_the_object_is_not_swallowed():
    rng = np.random.default_rng(5)
    local, _ = shell(rng, 3000)
    wall = np.column_stack([rng.uniform(-30, 30, 6000), np.full(6000, 1.15), rng.uniform(0, 3, 6000)])
    first = local + [0, 0, 0.75]
    track = tracking.Track(boxes.fit(first, cls=10, instance=1), first)
    scene = np.vstack([local + [0.3, 0, 0.75], wall])
    found = track.follow(track.first, scene, gap=0.5)
    assert found is not None and found["merged"] and found["left"] > 100
    taken = found["members"]
    assert np.isin(np.arange(3000), taken).mean() > 0.98
    assert (taken >= 3000).sum() < 150, "the wall beside the object is not taken"
    assert np.allclose(track.high - track.low, [4.0, 1.8, 1.5], atol=0.45), "and the box does not creep along it"


def test_tracking_from_a_middle_frame_reaches_both_ends():
    rng = np.random.default_rng(6)
    local, normals = shell(rng)
    sensor = np.array([0.0, -9.0, 1.2])
    frames = {}
    for index in range(15):
        world = local + [-10.5 + 1.5 * index, 0.0, 0.75]
        frames[index] = world[seen_from(world, normals, sensor, limit=0.6)]
    track = tracking.Track(boxes.fit(frames[7], cls=10, instance=3), frames[7])
    track.run(list(frames), 7, lambda frame: (np.arange(len(frames[frame])), frames[frame]), reach=2.0, gap=0.5)
    assert sorted(track.results) == list(frames)
    sizes = np.array([track.box_in(index)["size"] for index in frames])
    assert np.ptp(sizes, axis=0).max() < 1e-9 and np.allclose(sizes[0], [4.0, 1.8, 1.5], atol=0.35)
    for index in frames:
        assert np.allclose(track.box_in(index)["center"][:2], [-10.5 + 1.5 * index, 0.0], atol=0.3), index
