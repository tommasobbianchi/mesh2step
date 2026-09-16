"""Post-pass: add the radial partial cylinders (fillets) the 2D-profile extruders cannot represent.

auto2d/auto25g fit arcs in the extrusion plane, so a cylinder whose axis is radial (perpendicular
to the build axis) has no representation there. quads.classify still detects these patches
(paired triangles -> quads -> normals meeting on an axis): a partial cylinder of R~2 (mechparts/12)
or R~3 (mechparts/23), sweep 10..90 deg, axis horizontal. This pass takes each detected patch,
builds the fillet's corner wedge (bounded by the two tangent lines through the patch's angular
ends) and the patch's own cylinder, then replaces the solid inside that wedge with the cylinder
disk -- so the local surface becomes the cylinder the mesh shows.

Every patch is applied independently and kept only while the shape stays one valid solid; the whole
augmentation is kept only if it also holds the service gate (volume within 1%, p95 within 0.5% of
the diagonal, no previously built radius lost). Otherwise the original shape is returned untouched.
"""
import math

import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeVertex,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape

MAX_DV_PCT = 1.0
MAX_DIST_P95_REL = 0.005
RADIUS_MATCH = 0.01
SNAP_TOL = 0.1


def _built_radii(shape):
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fm)
    out = []
    for i in range(1, fm.Extent() + 1):
        s = BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i)))
        if s.GetType() == GeomAbs_Cylinder:
            out.append(s.Cylinder().Radius())
    return out


def _nsolids(shape):
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, m)
    return m.Extent()


def _free_edges(shape):
    ef = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, ef)
    return sum(1 for i in range(1, ef.Extent() + 1)
               if not BRep_Tool.Degenerated_s(TopoDS.Edge_s(ef.FindKey(i)))
               and ef.FindFromIndex(i).Extent() < 2)


def _volume(shape):
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return g.Mass()


def _mesh_volume(tri):
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)


def _p95(shape, tri, samples=200):
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fm)
    b = BRep_Builder()
    comp = TopoDS_Compound()
    b.MakeCompound(comp)
    for i in range(1, fm.Extent() + 1):
        b.Add(comp, fm.FindKey(i))
    verts = np.unique(tri.reshape(-1, 3), axis=0)
    pick = verts[np.linspace(0, len(verts) - 1, min(samples, len(verts))).astype(int)]
    dd = []
    for p in pick:
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex()
        ds = BRepExtrema_DistShapeShape(v, comp)
        ds.Perform()
        if ds.IsDone():
            dd.append(ds.Value())
    return float(np.percentile(dd, 95)) if dd else float("inf")


def _basis(d):
    a = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(d, a)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(d, e1)


def _patch_fit(V, d):
    """Fit the patch's own circle in the plane perpendicular to its axis.

    The points sit at coordinates of order 1e3, so the circle is fitted on mean-centred 2-D
    coordinates: fitting raw values makes the normal equations ill-conditioned and returns a
    wrong centre (measured: axis height 18 instead of 2 on a part spanning z 0..20)."""
    e1, e2 = _basis(d)
    P2 = np.c_[V @ e1, V @ e2]
    m2 = P2.mean(0)
    Q = P2 - m2
    A = np.c_[2 * Q[:, 0], 2 * Q[:, 1], np.ones(len(Q))]
    sol, *_ = np.linalg.lstsq(A, (Q ** 2).sum(1), rcond=None)
    cx, cy = sol[0] + m2[0], sol[1] + m2[1]
    rr = np.sqrt((P2[:, 0] - cx) ** 2 + (P2[:, 1] - cy) ** 2)
    r = float(rr.mean())
    res = float(np.abs(rr - r).mean())
    along = V @ d
    am = float(along.mean())
    ap = cx * e1 + cy * e2 + am * d
    ang = np.arctan2(P2[:, 1] - cy, P2[:, 0] - cx)
    aa = ang[np.argsort(ang)]
    gaps = np.diff(np.r_[aa, aa[0] + 2 * np.pi])
    gi = int(np.argmax(gaps))
    alo = aa[(gi + 1) % len(aa)]
    ahi = aa[gi]
    if ahi < alo:
        ahi += 2 * np.pi
    return ap, r, res, alo, ahi, float(along.min() - am), float(along.max() - am)


def _corner_and_cylinder(ap, d, r, alo, ahi, b0, b1, margin):
    """The corner wedge (triangle of the two tangent lines through the patch ends) and the patch's
    own cylinder, both as solids over the patch's axial span plus a margin."""
    e1, e2 = _basis(d)

    def pt(a, rad, ax_):
        return ap + rad * (math.cos(a) * e1 + math.sin(a) * e2) + ax_ * d

    def tangent(a):
        return -math.sin(a) * e1 + math.cos(a) * e2

    t0, t1 = pt(alo, r, 0), pt(ahi, r, 0)
    p0 = np.array([t0 @ e1, t0 @ e2])
    p1 = np.array([t1 @ e1, t1 @ e2])
    v0 = np.array([tangent(alo) @ e1, tangent(alo) @ e2])
    v1 = np.array([tangent(ahi) @ e1, tangent(ahi) @ e2])
    s, _ = np.linalg.solve(np.c_[v0, -v1], p1 - p0)
    c2 = p0 + s * v0

    def to3(p2, ax_):
        return ap + (p2[0] - (ap @ e1)) * e1 + (p2[1] - (ap @ e2)) * e2 + ax_ * d

    def g(p):
        return gp_Pnt(float(p[0]), float(p[1]), float(p[2]))

    z0, z1 = b0 - margin, b1 + margin
    P0, P1, PC = to3(p0, z0), to3(p1, z0), to3(c2, z0)
    mw = BRepBuilderAPI_MakeWire()
    mw.Add(BRepBuilderAPI_MakeEdge(g(P0), g(PC)).Edge())
    mw.Add(BRepBuilderAPI_MakeEdge(g(PC), g(P1)).Edge())
    mw.Add(BRepBuilderAPI_MakeEdge(g(P1), g(P0)).Edge())
    face = BRepBuilderAPI_MakeFace(mw.Wire(), True).Face()
    corner = BRepPrimAPI_MakePrism(face, gp_Vec(*(d * (z1 - z0)))).Shape()
    base = ap + z0 * d
    cyl = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(float(base[0]), float(base[1]), float(base[2])),
               gp_Dir(float(d[0]), float(d[1]), float(d[2]))), r, z1 - z0).Shape()
    return corner, cyl


def _candidates(tri):
    """(ap, d, r, alo, ahi, b0, b1, convex) for every radial cylinder patch worth building."""
    from quads import classify

    _, _, out = classify(tri)
    for o in out:
        if o[0] != "cylinder":
            continue
        d = np.array(o[3], float)
        d /= np.linalg.norm(d)
        if abs(d[2]) > 0.1:            # radial only: the extrusion builders already do axis-Z arcs
            continue
        V = tri[o[4]].reshape(-1, 3)
        if len(V) < 6:
            continue
        try:
            ap, r, res, alo, ahi, b0, b1 = _patch_fit(V, d)
        except Exception:  # noqa: BLE001 - a bad patch must not abort the pass
            continue
        if r < 0.5 or res > 0.01 * r or abs(r - float(o[2])) > 0.15 * float(o[2]):
            continue
        sweep = math.degrees(ahi - alo)
        if sweep < 10 or sweep > 120 or b1 - b0 < 0.2:
            continue
        T = tri[o[4]]
        n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        nn = np.linalg.norm(n, axis=1)
        g = nn > 1e-12
        n[g] /= nn[g, None]
        rel = T.mean(1) - ap
        rad = rel - np.outer(rel @ d, d)
        rn = np.linalg.norm(rad, axis=1)
        g &= rn > 1e-9
        rad[g] /= rn[g, None]
        dot = float((n[g] * rad[g]).sum(1).mean()) if g.any() else 0.0
        yield ap, d, r, alo, ahi, b0, b1, dot > 0


def _apply(shape, corner, cyl, convex):
    if convex:
        add = BRepAlgoAPI_Common(corner, cyl).Shape()
        rem = BRepAlgoAPI_Cut(corner, cyl).Shape()
    else:
        add = BRepAlgoAPI_Cut(corner, cyl).Shape()
        rem = BRepAlgoAPI_Common(corner, cyl).Shape()
    fused = BRepAlgoAPI_Fuse(shape, add).Shape()
    if fused.IsNull():
        return None
    out = BRepAlgoAPI_Cut(fused, rem).Shape()
    return None if out.IsNull() else out


def _passes_gate(shape, tri, before):
    if not BRepCheck_Analyzer(shape, True).IsValid():
        return False
    if _nsolids(shape) != 1 or _free_edges(shape) != 0:
        return False
    mvol = _mesh_volume(tri)
    if not mvol or abs(100.0 * (_volume(shape) - mvol) / mvol) > MAX_DV_PCT:
        return False
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    if _p95(shape, tri) > MAX_DIST_P95_REL * float(np.linalg.norm(hi - lo)):
        return False
    after = _built_radii(shape)
    return all(any(abs(r - a) <= RADIUS_MATCH * max(r, 1e-9) for a in after) for r in before)


def _axis_perp(ap, d, fap, fd):
    """Perpendicular distance between two axis points, or None when the directions differ."""
    if abs(abs(float(np.dot(d, fd))) - 1.0) > 1e-3:
        return None
    rel = ap - fap
    return float(np.linalg.norm(rel - float(np.dot(rel, fd)) * fd))


def _same_feature(f, ap, d, r, b0, b1):
    """True when a candidate duplicates a fillet already built in this pass.

    Identity is the axis LINE (direction and position) plus an overlapping axial span, not the
    radius: two fillets of equal radius on different edges are different features."""
    fap, fd, _fr, fb0, fb1 = f
    perp = _axis_perp(ap, d, fap, fd)
    if perp is None or perp > RADIUS_MATCH * max(r, 1e-9):
        return False
    t, ft = float(np.dot(ap, d)), float(np.dot(fap, d))
    return not (t + b1 < ft + fb0 or t + b0 > ft + fb1)


def _accepted(new):
    return (new is not None and BRepCheck_Analyzer(new, True).IsValid()
            and _nsolids(new) == 1 and _free_edges(new) == 0)


def _snap_axes(ap, d, r, built):
    """Axes of already-built fillets on the same edge line as this candidate.

    A short partial arc fits its circle centre to within a few percent of r, which is enough to
    put the wedge off the corner the builder left and tear the solid; borrowing the axis already
    established on the same line repairs it. Used only when the candidate's own axis fails."""
    for f in built:
        perp = _axis_perp(ap, d, f[0], f[1])
        if perp is not None and perp <= SNAP_TOL * max(r, 1e-9):
            yield f[0], f[1], f[2]


def augment(shape, tri, margin=0.02):
    """Replace each detected radial fillet's corner wedge with the patch's own cylinder.

    Returns the augmented shape only if it passes the gate; the original otherwise."""
    original = shape
    before = _built_radii(shape)
    applied = 0
    built = []
    for ap, d, r, alo, ahi, b0, b1, convex in _candidates(tri):
        if any(_same_feature(f, ap, d, r, b0, b1) for f in built):
            continue
        new = None
        for ap_, d_, r_ in ((ap, d, r), *_snap_axes(ap, d, r, built)):
            try:
                corner, cyl = _corner_and_cylinder(ap_, d_, r_, alo, ahi, b0, b1, margin)
                if not (BRepCheck_Analyzer(corner, True).IsValid()
                        and BRepCheck_Analyzer(cyl, True).IsValid()):
                    new = None
                    continue
                new = _apply(shape, corner, cyl, convex)
            except Exception:  # noqa: BLE001 - a failing patch must not abort the pass
                new = None
            if _accepted(new):
                break
            new = None
        if new is not None:
            shape = new
            applied += 1
            built.append((ap, d, r, b0, b1))
    if not applied:
        return original
    u = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    u.Build()
    if BRepCheck_Analyzer(u.Shape(), True).IsValid() and _nsolids(u.Shape()) == 1:
        shape = u.Shape()
    return shape if _passes_gate(shape, tri, before) else original
