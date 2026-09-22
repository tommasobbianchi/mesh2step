"""reverse.py: silhouette sketch -> extrude -> rounds, the design history of a prismatic part (Tommaso 2026-09-22).

Part 16 is the reference: a plate outline of arcs, extruded 20 mm, every outer edge fully rounded (r 9.95 = half the
thickness), holes sharp. reverse.py alone reproduces it at p95 0.025 mm, 8/8 curved, 0 non-analytic faces.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import junction_shapes as js  # noqa: E402
cq = js.cq


def _plate():
    """A stadium plate, 12 thick, outer edges rounded 5.9 (near-full round), one sharp through hole."""
    w = cq.Workplane("XY").slot2D(80, 30).extrude(12)
    w = w.faces(">Z").workplane().hole(10)
    w = w.newObject(w.faces(">Z").val().outerWire().Edges()).fillet(5.9)
    return w.newObject(w.faces("<Z").val().outerWire().Edges()).fillet(5.9)


def test_reverse_rebuilds_a_rounded_plate(tmp_path):
    import reverse
    truth = _plate().val()
    stl = js.stl(_plate(), tmp_path / "plate.stl", tol=0.01, ang=0.1)
    R = reverse.reverse(stl)
    assert R["axis"] == "Z" and len(R["holes"]) == 1
    assert abs(R["r_top"]["outer"] - 5.9) < 0.15 and R["r_top"]["holes"] == 0.0
    src, kinds = reverse.program(R)
    assert "arc" in kinds                                   # the slot ends are arcs, not chords
    ns = {"cq": cq}
    exec(src, ns)
    s = ns["result"].val()
    assert s.isValid()
    assert abs(s.Volume() - truth.Volume()) / truth.Volume() < 0.01
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    kinds = Counter(str(BRepAdaptor_Surface(f.wrapped).GetType()).split("_")[-1] for f in s.Faces())
    assert kinds["Torus"] >= 2 and set(kinds) <= {"Plane", "Cylinder", "Torus"}


def test_reverse_stacks_levels_of_a_stepped_part(tmp_path):
    """A stack of extrusions: one sketch per level between its flat faces (flange, boss, bore through both)."""
    import reverse
    w = (cq.Workplane("XY").rect(60, 40).extrude(8)
         .faces(">Z").workplane().circle(12).extrude(15)
         .faces(">Z").workplane().hole(8))
    truth = w.val()
    stl = js.stl(w, tmp_path / "stepped.stl", tol=0.01, ang=0.1)
    R = reverse.reverse(stl)
    assert R["axis"] == "Z" and len(R["levels"]) == 2
    src, _ = reverse.program(R)
    ns = {"cq": cq}
    exec(src, ns)
    s = ns["result"].val()
    assert s.isValid() and abs(s.Volume() - truth.Volume()) / truth.Volume() < 0.01


def test_facts_fits_arcs_on_a_coarse_mesh(tmp_path):
    """facts.py used auto2d.segment_loop, which turned coarse arcs into 1-segment lines; it now uses reverse.segment."""
    import json, subprocess
    # coarse like the corpus (part 16's arcs sag ~0.005 mm per chord). Much coarser (17 deg facets) still fails:
    # a mid-height section cuts the rounds' facets and its points scatter ~0.07 mm off the circle (> TOL 0.02)
    stl = js.stl(_plate(), tmp_path / "plate.stl", tol=0.02, ang=0.15)
    out = tmp_path / "facts.json"
    p = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "facts.py"), str(stl), str(out), "2"],
                       capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stderr[-1500:]
    segs = [list(s)[0] for lv in json.loads(out.read_text())["levels"] for lp in lv["loops"] for s in lp["segments"]]
    assert segs.count("arc") >= 3 and len(segs) <= 12, segs          # slot ends + hole, not dozens of chords
