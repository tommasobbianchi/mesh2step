"""recon_tools (rt): one construction per junction family, exact analytic faces after the STEP round trip
(spec specs/recon-tools.md)."""
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import junction_shapes as js  # noqa: E402
cq = js.cq

TOP = cq.Plane(origin=(0, 0, 2), xDir=(1, 0, 0), normal=(0, 0, 1))     # top face of the 30 x 30 x 4 plate


def plate():
    return cq.Workplane("XY").box(30, 30, 4)


def roundtrip(w, tmp_path, name):
    """STEP out, canonicalize (as the loop does), read back: faces kinds + junctions."""
    import canon
    import junctions
    p = js.step(w, tmp_path / f"{name}.step")
    canon.canonicalize_step(p)
    r = junctions.extract(p)
    kinds = Counter()
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    for f in canon._faces(canon._read(p)):
        kinds[str(BRepAdaptor_Surface(f).GetType()).split("_")[-1]] += 1
    assert canon._summary(canon._read(p))[0], "solid is not valid"
    assert set(kinds) <= {"Plane", "Cylinder", "Cone", "Torus", "Sphere"}, kinds       # nothing non-analytic
    return r


def blends(r, sig):
    return [b for b in r["blends"] if b["sig"] == sig]


def test_boss_with_fillet_and_round(tmp_path):
    import recon_tools as rt
    r = roundtrip(rt.boss(plate(), TOP, (0, 0), 5.0, 8.0, base_fillet=1.5, top_round=1.0), tmp_path, "boss")
    assert [round(b["radius"], 6) for b in blends(r, "blend:torus|cylinder+plane|fillet")] == [1.5]
    assert [round(b["radius"], 6) for b in blends(r, "blend:torus|cylinder+plane|round")] == [1.0]


def test_spindle_round_survives_the_step_round_trip(tmp_path):
    """Part 6: a 2.54 round on a radius-4 boss is a torus with R 1.46 < r 2.54."""
    import recon_tools as rt
    r = roundtrip(rt.boss(plate(), TOP, (0, 0), 4.0, 8.0, top_round=2.54), tmp_path, "spindle")
    assert [round(b["radius"], 4) for b in blends(r, "blend:torus|cylinder+plane|round")] == [2.54]


def test_hole_with_chamfer(tmp_path):
    import recon_tools as rt
    r = roundtrip(rt.hole(plate(), TOP, (0, 0), 3.0, mouth_chamfer=1.0), tmp_path, "chamfer")
    assert any(j["sig"] == "cone|plane|circle|convex" for j in r["junctions"])


def test_hole_with_round_mouth(tmp_path):
    import recon_tools as rt
    r = roundtrip(rt.hole(plate(), TOP, (0, 0), 3.0, mouth_round=1.0), tmp_path, "round")
    assert [round(b["radius"], 6) for b in blends(r, "blend:torus|cylinder+plane|round")] == [1.0]


def test_blind_hole_depth(tmp_path):
    import recon_tools as rt
    w = rt.hole(plate(), TOP, (0, 0), 3.0, depth=2.5)
    assert abs(w.val().Volume() - (30 * 30 * 4 - 3.141592653589793 * 9 * 2.5)) < 1e-3


def test_counterbore(tmp_path):
    import recon_tools as rt
    r = roundtrip(rt.counterbore(plate(), TOP, (0, 0), 2.0, 4.0, 1.5), tmp_path, "cbore")
    radii = sorted(round(j["radius"], 6) for j in r["junctions"] if j["curve"] == "circle")
    assert 2.0 in radii and 4.0 in radii
    assert any(j["sig"] == "cylinder|plane|circle|concave" for j in r["junctions"])   # bore wall meets bore floor


def test_ring_fillet_on_an_existing_tube(tmp_path):
    import recon_tools as rt
    tube = plate().union(cq.Workplane(TOP).circle(5.0).extrude(8.0))
    r = roundtrip(rt.ring_fillet(tube, TOP, (0, 0), 5.0, 2.0), tmp_path, "ring")
    assert [round(b["radius"], 6) for b in blends(r, "blend:torus|cylinder+plane|fillet")] == [2.0]


def test_edge_round(tmp_path):
    import recon_tools as rt
    r = roundtrip(rt.edge_round(cq.Workplane("XY").box(20, 20, 10), "|Z", 2.0), tmp_path, "edges")
    assert len(blends(r, "blend:cylinder|plane+plane|round")) == 4


@pytest.mark.parametrize("name", ["boss", "hole", "counterbore", "ring_fillet", "edge_round"])
def test_every_tool_documents_itself(name):
    import recon_tools as rt
    doc = getattr(rt, name).__doc__ or ""
    assert len(doc) > 80        # the model reads these docstrings in its brief
