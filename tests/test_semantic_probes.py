"""S3 probes (tools/semantic/probes.py): deterministic measurements on synthetic parts with known answers."""
import sys
from pathlib import Path

import pytest
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/semantic"))
import probes as P  # noqa: E402


@pytest.fixture(scope="module")
def plate():
    """40 x 30 x 10 plate, two through holes d=6 at x=+-10 along Z."""
    b = trimesh.creation.box((40, 30, 10))
    for x in (-10, 10):
        c = trimesh.creation.cylinder(radius=3, height=20, sections=64)
        c.apply_translation((x, 0, 0))
        b = b.difference(c)
    return b


@pytest.fixture(scope="module")
def bushing():
    """Turned part about Z: OD 30, bore 12, height 20."""
    o = trimesh.creation.cylinder(radius=15, height=20, sections=96)
    i = trimesh.creation.cylinder(radius=6, height=30, sections=96)
    return o.difference(i)


def test_bbox(plate):
    b = P.bbox(plate)
    assert b["size"] == pytest.approx([40, 30, 10], abs=1e-6)


def test_thickness(plate):
    assert P.thickness(plate, "Z") == pytest.approx(10, abs=0.05)


def test_section_circles_finds_the_holes(plate):
    cs = P.section_circles(plate, "Z", 0.5)
    holes = sorted(cs, key=lambda c: c["c"][0])
    assert len(holes) == 2
    assert [h["d"] for h in holes] == pytest.approx([6, 6], abs=0.15)
    assert [h["c"][0] for h in holes] == pytest.approx([-10, 10], abs=0.1)


def test_count_holes(plate, bushing):
    assert P.count_holes(plate, "Z") == 2
    assert P.count_holes(bushing, "Z") == 1


def test_revolve_axis(plate, bushing):
    assert P.revolve_axis(bushing) == "Z"
    assert P.revolve_axis(plate) is None


def test_normalize_plan_sorts_undo_by_stage():
    plan = {"undo": [{"step": 1, "stage": "subtractive", "op": "hole"},
                     {"step": 2, "stage": "finish", "op": "fillet"},
                     {"step": 3, "stage": "additive", "op": "boss"},
                     {"step": 4, "stage": "subtractive", "op": "pocket"}]}
    out = P.normalize_plan(plan)
    assert [u["op"] for u in out["undo"]] == ["fillet", "hole", "pocket", "boss"]
    assert [u["step"] for u in out["undo"]] == [1, 2, 3, 4]
    assert [u["op"] for u in plan["undo"]][0] == "hole"          # input untouched


def test_count_holes_finds_a_blind_hole_off_the_mid_plane():
    """10 mm plate, a d=4 blind hole 3 mm deep from the top at x=12, plus a through hole d=6 at x=-10."""
    b = trimesh.creation.box((40, 30, 10))
    t = trimesh.creation.cylinder(radius=3, height=20, sections=64); t.apply_translation((-10, 0, 0))
    bl = trimesh.creation.cylinder(radius=2, height=6, sections=64); bl.apply_translation((12, 0, 5))
    m = b.difference(t).difference(bl)
    assert P.count_holes(m, "Z") == 2


def test_count_holes_all_axes_finds_a_cross_hole():
    """10 mm plate: a through hole d=6 along Z at x=-10, and a cross hole d=4 along X through the side wall."""
    b = trimesh.creation.box((40, 30, 10))
    t = trimesh.creation.cylinder(radius=3, height=20, sections=64); t.apply_translation((-10, 0, 0))
    x = trimesh.creation.cylinder(radius=2, height=60, sections=64)
    x.apply_transform(trimesh.transformations.rotation_matrix(1.5707963, (0, 1, 0))); x.apply_translation((0, 8, 0))
    m = b.difference(t).difference(x)
    assert P.count_holes(m, "Z") == 1
    assert P.count_holes_all(m) == 2
