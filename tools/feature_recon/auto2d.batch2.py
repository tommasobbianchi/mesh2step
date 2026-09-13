"""Automatic feature-level reconstruction of an extrusion (2.5D) part from its STL.
1. pick the extrusion axis (section perimeter invariant at 30/50/70%);
2. slice at mid-height; split every loop into exact lines and circular arcs;
3. build OCC wires (arcs through 3 loop points, shared end vertices), a face with holes, and a prism
   over the part's extent along the axis;
4. measure each loop's inward offset d(t) near both end faces from slices, classify as fillet
   (d = rho - sqrt(rho^2 - (rho - t)^2)) or chamfer (d = c - t), and apply it to that loop's end edges;
5. validate (BRepCheck, volume vs mesh, mesh->model distance sample) and write STEP.
usage: python3 auto2d.py <stl> <out.step>"""
import sys, math, struct, time, random
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, loops, dedupe, fit_circle
from OCP.gp import gp_Pnt, gp_Vec, gp_Dir, gp_Ax2, gp_Trsf, gp_Circ
from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace,
                                BRepBuilderAPI_MakeVertex, BRepBuilderAPI_Transform)
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet, BRepFilletAPI_MakeChamfer
from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Wire
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Cone
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs, STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.TopoDS import TopoDS_Compound
from OCP.BRep import BRep_Builder

LINE_TOL, ARC_TOL = 0.02, 0.02

def section2d(tri, ax, h):
    o = [i for i in range(3) if i != ax]
    d = tri[:, :, ax] - h
    s = np.where(d < 0, -1, 1)
    m = (s[:, 0] != s[:, 1]) | (s[:, 1] != s[:, 2])
    segs = []
    for t, dd in zip(tri[m], d[m]):
        pts = []
        for i in range(3):
            j = (i + 1) % 3
            if (dd[i] < 0) != (dd[j] < 0):
                u = dd[i] / (dd[i] - dd[j]); p = t[i] + u * (t[j] - t[i]); pts.append(p[o])
        if len(pts) == 2: segs.append((pts[0], pts[1]))
    return segs

def loop_area(L):
    return 0.5 * np.sum(L[:-1, 0] * L[1:, 1] - L[1:, 0] * L[:-1, 1])

def segment_loop(L):
    """split a closed polyline into ('line', i0, i1) / ('arc', i0, i1, centre, R) index runs, greedy, from the sharpest corner"""
    L = dedupe(L)
    if np.linalg.norm(L[0] - L[-1]) < 1e-6: L = L[:-1]
    n = len(L)
    ang = np.array([abs(math.atan2(*(lambda u, v: (u[0] * v[1] - u[1] * v[0], u @ v))(L[k] - L[k - 1], L[(k + 1) % n] - L[k]))) for k in range(n)])
    s = int(np.argmax(ang)); L = np.r_[L[s:], L[:s], L[s:s + 1]]; n = len(L)
    prims = []; i = 0
    while i < n - 1:
        j = i + 1; kind = ("line",)
        while j + 1 < n:
            P = L[i:j + 2]; a, b = P[0], P[-1]; ab = b - a; lab = np.linalg.norm(ab)
            dl = np.abs((P[:, 0] - a[0]) * ab[1] - (P[:, 1] - a[1]) * ab[0]).max() / lab if lab > 1e-9 else 1e9
            if dl <= LINE_TOL and kind[0] == "line":
                j += 1; continue
            if len(P) >= 4:
                c, r, dev = fit_circle(P)
                if dev <= ARC_TOL and r < 1e4:
                    j += 1; kind = ("arc",); continue
            break
        if kind[0] == "arc":
            c, r, dev = fit_circle(L[i:j + 1]); prims.append(("arc", i, j, c, r))
        else:
            prims.append(("line", i, j))
        i = j
    # merge consecutive arcs of the same circle and consecutive collinear lines
    out = []
    for p in prims:
        if out and p[0] == "arc" and out[-1][0] == "arc" and np.linalg.norm(p[3] - out[-1][3]) < 0.05 and abs(p[4] - out[-1][4]) < 0.05:
            q = out[-1]; c, r, _ = fit_circle(L[q[1]:p[2] + 1]); out[-1] = ("arc", q[1], p[2], c, r)
        elif out and p[0] == "line" and out[-1][0] == "line":
            q = out[-1]; P = L[q[1]:p[2] + 1]; a, b = P[0], P[-1]; ab = b - a; lab = np.linalg.norm(ab)
            if lab > 1e-9 and np.abs((P[:, 0] - a[0]) * ab[1] - (P[:, 1] - a[1]) * ab[0]).max() / lab <= LINE_TOL:
                out[-1] = ("line", q[1], p[2])
            else:
                out.append(p)
        else:
            out.append(p)
    return L, out

def to3d(p2, ax, h):
    v = [0.0, 0.0, 0.0]; o = [i for i in range(3) if i != ax]
    v[o[0]], v[o[1]], v[ax] = p2[0], p2[1], h
    return gp_Pnt(*v)

def build_wire(L, prims, ax, h):
    mw = BRepBuilderAPI_MakeWire(); verts = {}
    def vtx(i):
        if i not in verts: verts[i] = BRepBuilderAPI_MakeVertex(to3d(L[i], ax, h)).Vertex()
        return verts[i]
    n_last = len(L) - 1
    if len(prims) == 1 and prims[0][0] == "arc":
        # the whole loop is one circle (a round hole or boss): a full circle edge, no 3-point arc
        _, i0, i1, c, r = prims[0]
        d = [0.0, 0.0, 0.0]; d[ax] = 1.0
        circ = gp_Circ(gp_Ax2(to3d(c, ax, h), gp_Dir(*d)), float(r))
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circ).Edge()).Wire()
    for p in prims:
        i0, i1 = p[1], p[2]
        k1 = 0 if i1 == n_last else i1          # closing vertex is the start vertex
        e = None
        if p[0] == "arc":
            im = (i0 + i1) // 2
            mk = GC_MakeArcOfCircle(to3d(L[i0], ax, h), to3d(L[im], ax, h), to3d(L[i1], ax, h))
            if mk.IsDone() and im not in (i0, i1):
                e = BRepBuilderAPI_MakeEdge(mk.Value(), vtx(i0), vtx(k1)).Edge()
        if e is None:   # line, or an arc too short/degenerate to construct
            e = BRepBuilderAPI_MakeEdge(vtx(i0), vtx(k1)).Edge()
        mw.Add(e)
    return mw.Wire()

def main():
    t0 = time.time()
    tri = load(sys.argv[1]); lo = tri.reshape(-1, 3).min(0); hi = tri.reshape(-1, 3).max(0); size = hi - lo
    # 1. axis
    best = None
    for ax in range(3):
        per = []
        for f in (0.3, 0.5, 0.7):
            segs = section2d(tri, ax, lo[ax] + f * size[ax])
            per.append(sum(np.linalg.norm(b - a) for a, b in segs))
        if min(per) > 0:
            var = (max(per) - min(per)) / max(per)
            if best is None or var < best[0]: best = (var, ax)
    var, ax = best
    import os
    if os.environ.get("AXIS") in ("0", "1", "2"):   # batch retry: force another candidate axis
        ax = int(os.environ["AXIS"])
        per = [sum(np.linalg.norm(b - a) for a, b in section2d(tri, ax, lo[ax] + f * size[ax])) for f in (0.3, 0.5, 0.7)]
        var = (max(per) - min(per)) / max(per) if min(per) > 0 else 1.0
    print("axis %s section-perimeter variation %.5f extent %.3f" % ("XYZ"[ax], var, size[ax]), flush=True)
    if var > 0.01:
        print("NOT AN EXTRUSION - stop"); return 2
    z0, z1 = lo[ax], hi[ax]; zm = 0.5 * (z0 + z1)
    # 2. mid section
    Ls = [dedupe(l) for l in loops(section2d(tri, ax, zm)) if len(l) > 3]
    Ls = [l for l in Ls if abs(loop_area(np.r_[l, l[:1]])) > 1e-3]
    Ls.sort(key=lambda l: -abs(loop_area(np.r_[l, l[:1]])))
    outer = Ls[0]; inners = Ls[1:]
    print("mid loops %d (outer + %d inner)" % (len(Ls), len(inners)), flush=True)
    seg = [segment_loop(l) for l in Ls]
    for k, (L, pr) in enumerate(seg):
        arcs = [p for p in pr if p[0] == "arc"]
        print("  loop %d: %d lines, %d arcs; radii %s" % (k, sum(1 for p in pr if p[0] == "line"), len(arcs),
              sorted(set(round(p[4], 3) for p in arcs))[:12]), flush=True)
    # 3. wires, face, prism
    wires = [build_wire(L, pr, ax, z0) for L, pr in seg]
    mf = BRepBuilderAPI_MakeFace(wires[0], True)
    for w in wires[1:]:
        mf.Add(w)
    face = mf.Face()
    sff = ShapeFix_Face(face); sff.FixOrientation(); sff.Perform(); face = sff.Face()
    dvec = [0.0, 0.0, 0.0]; dvec[ax] = z1 - z0
    solid = BRepPrimAPI_MakePrism(face, gp_Vec(*dvec)).Shape()
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(solid, g)
    print("prism valid %s volume %.3f" % (BRepCheck_Analyzer(solid, True).IsValid(), g.Mass()), flush=True)
    # 4. end treatments per loop: inward offset d(t) = (A_mid - A_t)/P_mid with the loop's material sign
    mid_areas = [loop_area(np.r_[L[:-1], L[:1]]) for L, pr in seg]
    mid_per = [np.sum(np.linalg.norm(np.diff(L, axis=0), axis=1)) for L, pr in seg]
    def match_loops(zz):
        cur = [dedupe(l) for l in loops(section2d(tri, ax, zz)) if len(l) > 3]
        out = []
        for L, pr in seg:
            c = L.mean(0)
            cand = min(cur, key=lambda l: np.linalg.norm(l.mean(0) - c) + abs(abs(loop_area(np.r_[l, l[:1]])) - abs(loop_area(np.r_[L, L[:1]]))) * 1e-3) if cur else None
            out.append(cand)
        return out
    T = z1 - z0
    # ponytail: range capped at 6 mm / 0.3T -- widening it to T/2 made 18/21/25/32 fit WORSE (area-offset proxy
    # breaks down at large offsets); full rounds (p16) need a real 3D treatment, not a wider search
    ts = [0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 1.6, 2.0, 2.5, 3.0, 4.0]
    ts = [t for t in ts if t < 0.3 * T]
    treat = []
    for end, sign in ((z0, +1), (z1, -1)):
        prof = []
        for t in ts:
            ml = match_loops(end + sign * t)
            prof.append([abs(abs(loop_area(np.r_[l, l[:1]])) - abs(mid_areas[k])) / mid_per[k] if l is not None else float("nan")
                         for k, l in enumerate(ml)])
        prof = np.array(prof)   # (t, loop) -> offset magnitude
        per_loop = []
        for k in range(len(seg)):
            d = prof[:, k]; t = np.array(ts)
            ok = np.isfinite(d)
            if not ok.any() or d[ok][0] < 0.01:
                per_loop.append(("none", 0.0)); continue
            best = ("none", 0.0, 1e9)
            for rho in np.arange(0.1, 6.01, 0.05):
                pred = np.where(t < rho, rho - np.sqrt(np.maximum(rho ** 2 - (rho - t) ** 2, 0)), 0)
                err = np.nanmean((pred - d) ** 2)
                if err < best[2]: best = ("fillet", rho, err)
            for c in np.arange(0.1, 6.01, 0.05):
                pred = np.maximum(c - t, 0); err = np.nanmean((pred - d) ** 2)
                if err < best[2]: best = ("chamfer", c, err)
            per_loop.append((best[0], round(best[1], 2), best[2]))
        treat.append(per_loop)
        print("end %s treatments per loop: %s" % ("start" if sign > 0 else "end", [(p[0], p[1]) for p in per_loop]), flush=True)
    # apply: collect end-face edges, assign each to the nearest loop, fillet/chamfer by that loop's measure
    fil = BRepFilletAPI_MakeFillet(solid); cha = BRepFilletAPI_MakeChamfer(solid)
    nf = nc = 0; seen = TopTools_IndexedMapOfShape()
    ex = TopExp_Explorer(solid, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current()); s = BRepAdaptor_Surface(f)
        if s.GetType() == GeomAbs_Plane:
            n = s.Plane().Axis().Direction(); comp = [n.X(), n.Y(), n.Z()][ax]
            if abs(abs(comp) - 1) < 1e-9:
                zpl = [s.Plane().Location().X(), s.Plane().Location().Y(), s.Plane().Location().Z()][ax]
                end_i = 0 if abs(zpl - z0) < abs(zpl - z1) else 1
                ee = TopExp_Explorer(f, TopAbs_EDGE)
                while ee.More():
                    e = TopoDS.Edge_s(ee.Current())
                    if not seen.Contains(e):
                        seen.Add(e)
                        c = BRepAdaptor_Curve(e); pm = c.Value(0.5 * (c.FirstParameter() + c.LastParameter()))
                        p2 = np.array([[pm.X(), pm.Y(), pm.Z()][i] for i in range(3) if i != ax])
                        k = int(np.argmin([np.min(np.linalg.norm(L - p2, axis=1)) for L, pr in seg]))
                        kind, val = treat[end_i][k][0], treat[end_i][k][1]
                        if kind == "fillet": fil.Add(min(val, 0.499 * (z1 - z0)), e); nf += 1
                        elif kind == "chamfer": cha.Add(val, e); nc += 1
                    ee.Next()
        ex.Next()
    if nf:
        fil.Build()
        print("fillets on %d edges: done %s" % (nf, fil.IsDone()), flush=True)
        if fil.IsDone(): solid = fil.Shape()
    if nc:
        cha2 = BRepFilletAPI_MakeChamfer(solid)  # rebuild on the current solid if fillets changed it
        print("chamfer edges requested %d (applied only when no fillet was applied first)" % nc, flush=True)
        if not nf:
            cha.Build(); print("chamfers done %s" % cha.IsDone(), flush=True)
            if cha.IsDone(): solid = cha.Shape()
    # 5. validate
    census = {"plane": 0, "cylinder": 0, "torus": 0, "cone": 0, "other": 0}
    ex = TopExp_Explorer(solid, TopAbs_FACE)
    while ex.More():
        ty = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()
        census["plane" if ty == GeomAbs_Plane else "cylinder" if ty == GeomAbs_Cylinder else "torus" if ty == GeomAbs_Torus else "cone" if ty == GeomAbs_Cone else "other"] += 1
        ex.Next()
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(solid, g)
    mvol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
    print("model valid %s volume %.3f mesh %.3f delta %.3f%% faces %s  [%.1fs]" % (
        BRepCheck_Analyzer(solid, True).IsValid(), g.Mass(), mvol, 100 * (g.Mass() - mvol) / mvol, census, time.time() - t0), flush=True)
    b = BRep_Builder(); comp = TopoDS_Compound(); b.MakeCompound(comp)
    ex = TopExp_Explorer(solid, TopAbs_FACE)
    while ex.More():
        b.Add(comp, ex.Current()); ex.Next()
    verts = np.unique(tri.reshape(-1, 3).round(6), axis=0); random.seed(4)
    dd = []
    for i in random.sample(range(len(verts)), min(800, len(verts))):
        ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*verts[i])).Vertex(), comp); ds.Perform(); dd.append(ds.Value())
    dd = np.array(dd)
    print("mesh->model faces: mean %.4f p95 %.4f max %.4f" % (dd.mean(), np.percentile(dd, 95), dd.max()), flush=True)
    Interface_Static.SetCVal_s("write.step.schema", "AP214")
    w = STEPControl_Writer(); w.Transfer(solid, STEPControl_AsIs); ok = w.Write(sys.argv[2]) == IFSelect_RetDone
    r = STEPControl_Reader(); r.ReadFile(sys.argv[2]); r.TransferRoots(); back = r.OneShape()
    print("STEP %s; re-read valid %s" % (ok, BRepCheck_Analyzer(back, True).IsValid()), flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
