"""S4 compile (tools/semantic/compile_plan.py): plan structure + probe sections -> feature tree -> exact solid."""
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/semantic"))
sys.path.insert(0, str(ROOT / "tools/tree"))
import compile_plan as C  # noqa: E402
import analyse as A  # noqa: E402
import tree as T  # noqa: E402


def score(tree, m):
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    return A.measure(tree, m, tol, T.occupancy(m, m.bounds, n=60))


@pytest.fixture(scope="module")
def plate():
    b = trimesh.creation.box((40, 30, 10))
    for x in (-10, 10):
        c = trimesh.creation.cylinder(radius=3, height=20, sections=64); c.apply_translation((x, 0, 0))
        b = b.difference(c)
    return b


@pytest.fixture(scope="module")
def stepped():
    """Two levels along Z: a 40 x 30 x 6 base and a 20 x 15 x 4 block on top, a d=6 through hole in both."""
    a = trimesh.creation.box((40, 30, 6))
    t = trimesh.creation.box((20, 15, 4)); t.apply_translation((0, 0, 5))
    h = trimesh.creation.cylinder(radius=3, height=30, sections=64)
    return a.union(t).difference(h)


PLAN_Z = {"base": {"op": "extrude", "axis": "Z"}, "undo": []}


def test_single_level_plate(plate):
    tree = C.compile_plan(PLAN_Z, plate)
    pads = [f for f in tree["features"] if f["op"] == "pad"]
    assert len(pads) == 1 and pads[0]["axis"] == "Z"
    r = score(tree, plate)
    assert r["iou"] > 0.98, r


def test_two_levels(stepped):
    tree = C.compile_plan(PLAN_Z, stepped)
    assert len([f for f in tree["features"] if f["op"] == "pad"]) == 2
    r = score(tree, stepped)
    assert r["iou"] > 0.98, r


def test_axis_from_plan_is_used(plate):
    rot = plate.copy(); rot.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    tree = C.compile_plan({"base": {"op": "extrude", "axis": "Y"}, "undo": []}, rot)
    assert tree["features"][0]["axis"] == "Y"
    assert score(tree, rot)["iou"] > 0.98
