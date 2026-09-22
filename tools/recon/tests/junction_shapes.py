"""Small parts with known junctions, shared by the junction/toolbox/tree acceptance tests (docs/JUNCTIONS.md).

Each builder returns a CadQuery Workplane; step()/stl() write it out. Every expected signature below is
what the definitions in docs/JUNCTIONS.md say the part contains.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cqshim  # noqa: F401,E402  (cadquery on this box)
import cadquery as cq  # noqa: E402


def box():                      # 12 x plane|plane|line|convex
    return cq.Workplane("XY").box(20, 20, 10)


def l_block():                  # adds plane|plane|line|concave (the inside corner of the L)
    return cq.Workplane("XY").box(20, 20, 10).cut(cq.Workplane("XY").box(10, 10, 10).translate((5, 5, 5)))


def rounded_box(r=2.0):         # 4 x blend:cylinder|plane+plane|round, radius r
    return cq.Workplane("XY").box(20, 20, 10).edges("|Z").fillet(r)


def plate_with_hole(r=3.0):     # 2 x cylinder|plane|circle|convex, radius r, coaxial
    return cq.Workplane("XY").box(30, 30, 6).faces(">Z").workplane().hole(2 * r)


def boss_with_base_fillet(R=5.0, f=1.5):   # blend:torus|cylinder+plane|fillet, radius f
    w = cq.Workplane("XY").box(30, 30, 4).faces(">Z").workplane().circle(R).extrude(8)
    return w.edges(cq.selectors.RadiusNthSelector(0)).edges(cq.selectors.BoxSelector((-R - 1, -R - 1, 1.9), (R + 1, R + 1, 2.1))).fillet(f)


def boss_with_top_round(R=5.0, f=1.0):     # blend:torus|cylinder+plane|round, radius f
    return cq.Workplane("XY").circle(R).extrude(8).faces(">Z").edges().fillet(f)


def chamfered_hole(r=3.0, c=1.0):          # cone|plane|circle|convex at the mouth
    return cq.Workplane("XY").box(30, 30, 6).faces(">Z").workplane().hole(2 * r).faces(">Z").edges("%CIRCLE").chamfer(c)


def step(w, path):
    cq.exporters.export(w, str(path), exportType="STEP")
    return Path(path)


def stl(w, path, tol=0.005, ang=0.05):
    cq.exporters.export(w, str(path), exportType="STL", tolerance=tol, angularTolerance=ang)
    return Path(path)
