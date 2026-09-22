"""Rewrite revolved-circle faces of a STEP file as the exact tori they are.

A fillet built by revolving an arc comes out of OCCT as SURFACE_OF_REVOLUTION over a B-spline
profile: geometrically a torus (to 1e-8), but not an analytic face, so it counts as lost. OCCT's
writer cannot emit a torus whose major radius is below its minor one (a convex round on a small
boss: part 6, R 1.46 < r 2.54) -- it falls back to the revolution -- so the fix is made in the
STEP text: TOROIDAL_SURFACE, or DEGENERATE_TOROIDAL_SURFACE when R <= r. The rewrite is kept
only if the re-read solid has the same validity, face count and volume (1e-5 relative).
"""
import os
import re

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.ShapeAnalysis import ShapeAnalysis_CanonicalRecognition
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Circ, gp_Pnt, gp_Vec

TOL = 1e-6


def _read(path):
    r = STEPControl_Reader()
    if r.ReadFile(str(path)) != 1:        # IFSelect_RetDone
        return None
    r.TransferRoots()
    return r.OneShape()


def _faces(shape):
    e = TopExp_Explorer(shape, TopAbs_FACE)
    while e.More():
        yield TopoDS.Face_s(e.Current()); e.Next()


def _summary(shape):
    # adaptive integration: the default is 0.2% off on a revolved B-spline, the very face rewritten here
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g, 1e-9, False)
    return BRepCheck_Analyzer(shape).IsValid(), sum(1 for _ in _faces(shape)), g.Mass()


def _torus(face):
    """(axis point, axis dir, R, r, outer) when the face is a circle revolved about a coplanar axis."""
    a = BRepAdaptor_Surface(face)
    if not str(a.GetType()).endswith("SurfaceOfRevolution"):
        return None
    c = gp_Circ()
    if not ShapeAnalysis_CanonicalRecognition(
            BRepBuilderAPI_MakeEdge(a.Surface().Surface().BasisCurve()).Edge()).IsCircle(TOL, c):
        return None
    ax = a.AxeOfRevolution(); o, d = ax.Location(), gp_Vec(ax.Direction())
    if abs(d.Dot(gp_Vec(c.Axis().Direction()))) > TOL:          # profile plane must contain the axis
        return None
    h = gp_Vec(o, c.Location()).Dot(d)
    foot = gp_Pnt(o.X() + h * d.X(), o.Y() + h * d.Y(), o.Z() + h * d.Z())
    R, r = foot.Distance(c.Location()), c.Radius()
    # which part of a spindle torus the face uses: its points lie on the circle of their OWN
    # meridian half-plane (outer, "apple") or of the opposite one (inner, "lemon")
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    p = a.Value((u0 + u1) / 2, (v0 + v1) / 2)
    w = gp_Vec(foot, p); w = w - d.Multiplied(w.Dot(d))
    rho = w.Magnitude()
    outer = abs(((rho - R) ** 2 + (gp_Vec(foot, p).Dot(d)) ** 2) ** 0.5 - r) <= \
        abs(((rho + R) ** 2 + (gp_Vec(foot, p).Dot(d)) ** 2) ** 0.5 - r)
    return foot, d, R, r, outer


def _num(s):
    return [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)]


def canonicalize_step(path):
    """Rewrite in place; return how many revolution faces became tori (0 when nothing changed)."""
    shape = _read(path)
    if shape is None:
        return 0
    tori = [t for t in map(_torus, _faces(shape)) if t]
    if not tori:
        return 0
    text = open(path, errors="replace").read()
    ent = dict(re.findall(r"#(\d+)\s*=\s*([^;]*);", text))
    nxt = max(map(int, ent)) + 1
    add, n = [], 0
    for rid, body in list(ent.items()):
        m = re.match(r"SURFACE_OF_REVOLUTION\s*\(\s*'[^']*'\s*,\s*#\d+\s*,\s*#(\d+)\s*\)", body)
        if not m:
            continue
        a1 = re.match(r"AXIS1_PLACEMENT\s*\(\s*'[^']*'\s*,\s*#(\d+)\s*,\s*#(\d+)\s*\)", ent.get(m.group(1), ""))
        if not a1:
            continue
        pt, dr = _num(ent[a1.group(1)].split("(", 2)[-1]), _num(ent[a1.group(2)].split("(", 2)[-1])
        if len(pt) < 3 or len(dr) < 3:
            continue
        P, D = gp_Pnt(*pt[-3:]), gp_Vec(*dr[-3:]).Normalized()
        hits = [t for t in tori if abs(abs(D.Dot(t[1])) - 1) <= TOL
                and gp_Vec(t[0], P).Crossed(t[1]).Magnitude() <= TOL * max(1.0, abs(t[2]) + t[3])]
        params = {(round(t[2], 9), round(t[3], 9), t[4]) for t in hits}
        if len(params) != 1:                  # none, or two different tori on one axis: ambiguous
            continue
        foot, d, R, r, outer = hits[0]
        x = gp_Vec(1, 0, 0) if abs(d.X()) < 0.9 else gp_Vec(0, 1, 0)
        x = (x - d.Multiplied(x.Dot(d))).Normalized()
        p, dd, rd, ax = nxt, nxt + 1, nxt + 2, nxt + 3; nxt += 4
        add += [f"#{p}=CARTESIAN_POINT('',({foot.X()!r},{foot.Y()!r},{foot.Z()!r}));",
                f"#{dd}=DIRECTION('',({d.X()!r},{d.Y()!r},{d.Z()!r}));",
                f"#{rd}=DIRECTION('',({x.X()!r},{x.Y()!r},{x.Z()!r}));",
                f"#{ax}=AXIS2_PLACEMENT_3D('',#{p},#{dd},#{rd});"]
        new = (f"TOROIDAL_SURFACE('',#{ax},{R!r},{r!r})" if R > r else
               f"DEGENERATE_TOROIDAL_SURFACE('',#{ax},{R!r},{r!r},{'.T.' if outer else '.F.'})")
        text = re.sub(rf"#{rid}\s*=\s*SURFACE_OF_REVOLUTION[^;]*;", f"#{rid}={new};", text, count=1)
        n += 1
    if not n:
        return 0
    i = text.index("DATA;") + len("DATA;")
    tmp = f"{path}.canon.tmp"
    open(tmp, "w").write(text[:i] + "\n" + "\n".join(add) + text[i:])
    before, after = _summary(shape), (_summary(s) if (s := _read(tmp)) is not None else None)
    if not after or after[0] != before[0] or after[1] != before[1] \
            or abs(after[2] - before[2]) > 1e-5 * max(1.0, abs(before[2])):
        os.remove(tmp)
        return 0
    os.replace(tmp, path)
    return n


if __name__ == "__main__":
    import sys
    print(canonicalize_step(sys.argv[1]))
