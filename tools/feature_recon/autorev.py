"""Turned (revolved) parts, step 1: the turned envelope.
1. axis: for X/Y/Z, slice perpendicular at many stations; fit a circle to the section points; the axis whose
   circle centres are most constant (and fits tightest) is the spin axis; centre = median centre;
2. profile: at each station the outer radius (max distance of section points to the axis) and, if the
   section has an inner loop around the axis, the bore radius (min distance); stations are dense;
3. build the (axial, radial) profile polygon, simplify it into lines (tolerance), revolve 360 deg;
4. validate like auto2d; the mesh->model distance shows where flats / cross holes still need cutting.
usage: python3 autorev.py <stl> <out.step> [stations]"""
import sys, time, random, math
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, fit_circle, loops, dedupe
from auto2d import section2d
from OCP.gp import gp_Pnt, gp_Ax1, gp_Dir, gp_Vec
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Cone
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static

def rdp(P, eps):
    if len(P) < 3: return P
    a, b = P[0], P[-1]; ab = b - a; L = np.linalg.norm(ab)
    d = np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])) / L if L > 1e-12 else np.linalg.norm(P - a, axis=1)
    i = int(np.argmax(d))
    if d[i] > eps:
        return np.r_[rdp(P[:i + 1], eps)[:-1], rdp(P[i:], eps)]
    return np.array([a, b])

def main():
    t0 = time.time()
    tri = load(sys.argv[1]); M = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    lo = tri.reshape(-1, 3).min(0); hi = tri.reshape(-1, 3).max(0)
    best = None
    for ax in range(3):
        cs = []
        for f in np.linspace(0.1, 0.9, 9):
            segs = section2d(tri, ax, lo[ax] + f * (hi[ax] - lo[ax]))
            if len(segs) < 8: continue
            Ls = [dedupe(l) for l in loops(segs) if len(l) > 3]
            if not Ls: continue
            P = max(Ls, key=lambda L: abs(0.5 * np.sum(L[:-1, 0] * L[1:, 1] - L[1:, 0] * L[:-1, 1])))
            c, r, dev = fit_circle(P)
            cs.append((c, r, dev))
        if len(cs) < 5: continue
        C = np.array([c for c, r, d in cs]); spread = np.linalg.norm(C - np.median(C, 0), axis=1)
        score = np.median(spread) / max(np.median([r for c, r, d in cs]), 1e-9)
        print("axis %s centre spread/radius %.4f (stations %d)" % ("XYZ"[ax], score, len(cs)), flush=True)
        if best is None or score < best[0]: best = (score, ax, np.median(C, 0))
    score, ax, cen = best
    o = [i for i in range(3) if i != ax]
    print("spin axis %s centre (%.3f, %.3f) score %.4f" % ("XYZ"[ax], cen[0], cen[1], score), flush=True)
    zs = np.linspace(lo[ax], hi[ax], M + 1)[1:-1]
    prof_out, prof_in = [], []
    for z in zs:
        segs = section2d(tri, ax, z)
        if not segs: continue
        P = np.array([p for s in segs for p in s]); r = np.linalg.norm(P - cen, axis=1)
        prof_out.append((z, r.max()))
        # bore = a closed loop that ENCLOSES the axis and is not the outermost loop; flats and cross holes
        # also bring points near the axis, but their loops do not contain the centre
        Ls = [dedupe(l) for l in loops(segs) if len(l) > 3]
        def encloses(L):
            x, y = cen; c = False; n = len(L)
            for i in range(n):
                x1, y1 = L[i]; x2, y2 = L[(i + 1) % n]
                if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-300) + x1: c = not c
            return c
        around = sorted((np.linalg.norm(L - cen, axis=1).max() for L in Ls if encloses(L)))
        prof_in.append((z, float(np.linalg.norm(min((L for L in Ls if encloses(L)), key=lambda L: np.linalg.norm(L - cen, axis=1).max()) - cen, axis=1).min()) if len(around) >= 2 else 0.0))
    po = np.array(prof_out); pi = np.array(prof_in)
    # closed profile polygon in the (axial, radial) half-plane: outer from start to end, inner back
    outer = np.r_[[[lo[ax], po[0, 1]]], po, [[hi[ax], po[-1, 1]]]]
    inner = np.r_[[[lo[ax], pi[0, 1]]], pi, [[hi[ax], pi[-1, 1]]]][::-1]
    eps = 0.01 * max(1.0, float(po[:, 1].max())) * 0.05
    outer_s = rdp(outer, eps); inner_s = rdp(inner, eps)
    poly2 = np.r_[outer_s, inner_s]
    print("profile: %d outer + %d inner vertices (rdp eps %.4f); max R %.3f, bore R range %.3f..%.3f" % (
        len(outer_s), len(inner_s), eps, po[:, 1].max(), pi[:, 1].min(), pi[:, 1].max()), flush=True)
    def P3(z, r):
        v = [0.0, 0.0, 0.0]; v[ax] = z; v[o[0]] = cen[0] + r; v[o[1]] = cen[1]; return gp_Pnt(*v)
    mp = BRepBuilderAPI_MakePolygon()
    last = None
    for z, r in poly2:
        q = P3(z, r)
        if last is None or q.Distance(last) > 1e-6:
            mp.Add(q); last = q
    mp.Close()
    face = BRepBuilderAPI_MakeFace(mp.Wire(), True).Face()
    d = [0.0, 0.0, 0.0]; d[ax] = 1.0; c3 = [0.0, 0.0, 0.0]; c3[o[0]], c3[o[1]] = cen[0], cen[1]
    shape = BRepPrimAPI_MakeRevol(face, gp_Ax1(gp_Pnt(*c3), gp_Dir(*d))).Shape()
    u = ShapeUpgrade_UnifySameDomain(shape, True, True, False); u.Build(); shape = u.Shape()
    census = {"plane": 0, "cylinder": 0, "torus": 0, "cone": 0, "other": 0}
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        ty = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()
        census["plane" if ty == GeomAbs_Plane else "cylinder" if ty == GeomAbs_Cylinder else "torus" if ty == GeomAbs_Torus else "cone" if ty == GeomAbs_Cone else "other"] += 1
        ex.Next()
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g)
    mvol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
    print("envelope valid %s volume %.3f mesh %.3f delta %.3f%% faces %s  [%.1fs]" % (
        BRepCheck_Analyzer(shape, True).IsValid(), g.Mass(), mvol, 100 * (g.Mass() - mvol) / mvol, census, time.time() - t0), flush=True)
    b = BRep_Builder(); comp = TopoDS_Compound(); b.MakeCompound(comp)
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        b.Add(comp, ex.Current()); ex.Next()
    verts = np.unique(tri.reshape(-1, 3).round(6), axis=0); random.seed(6); dd = []
    for i in random.sample(range(len(verts)), min(600, len(verts))):
        ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*verts[i])).Vertex(), comp); ds.Perform(); dd.append(ds.Value())
    dd = np.array(dd)
    print("mesh->envelope faces: mean %.4f p50 %.4f p90 %.4f max %.4f (large values = flats / cross holes not yet cut)" % (
        dd.mean(), np.median(dd), np.percentile(dd, 90), dd.max()), flush=True)
    Interface_Static.SetCVal_s("write.step.schema", "AP214")
    w = STEPControl_Writer(); w.Transfer(shape, STEPControl_AsIs)
    print("STEP %s" % (w.Write(sys.argv[2]) == IFSelect_RetDone), flush=True)

if __name__ == "__main__":
    main()
