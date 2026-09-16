"""Stepped extrusion (2.5D with several height levels along one axis).
1. for each axis, slice at N heights and give each slice a signature (loop count, material area);
   group contiguous heights with the same signature into levels; pick the axis with the fewest levels;
2. each level: profile from its mid slice (lines + arcs, as auto2d), prism over [z_lo, z_hi] of the level,
   where level boundaries sit midway between the last slice of one level and the first of the next;
3. fuse the level prisms, unify same domain; validate and write STEP.
usage: python3 auto25.py <stl> <out.step> [N]"""
import sys, time, random, math
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, loops, dedupe
from auto2d import section2d, loop_area, segment_loop, build_wire
from radial_fillets import augment
from OCP.gp import gp_Pnt, gp_Vec
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.ShapeFix import ShapeFix_Face
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
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs, STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static

def material_area(tri, ax, h):
    Ls = [dedupe(l) for l in loops(section2d(tri, ax, h)) if len(l) > 3]
    areas = sorted((abs(loop_area(np.r_[l, l[:1]])) for l in Ls), reverse=True)
    areas = [a for a in areas if a > 1e-3]
    if not areas: return 0, 0.0, []
    # material = outer loops minus holes; approximate by nesting order: largest positive, alternate by containment count
    return len(areas), sum(areas), Ls

def levels_for_axis(tri, ax, lo, hi, N):
    hs = lo[ax] + (np.arange(N) + 0.5) / N * (hi[ax] - lo[ax])
    sig = []
    for h in hs:
        n, a, _ = material_area(tri, ax, h)
        sig.append((n, a))
    lv = []  # [start_idx, end_idx]
    for i, (n, a) in enumerate(sig):
        if lv and sig[lv[-1][0]][0] == n and abs(sig[lv[-1][0]][1] - a) <= 0.002 * max(a, 1e-9):
            lv[-1][1] = i
        else:
            lv.append([i, i])
    return hs, sig, lv

LOOP_CACHE = []   # loops already used by earlier levels; a matching loop is reused verbatim

def snap_loops(Ls, tol):
    # adjacent levels traced from different slices differ by ~0.01 mm; fusing them leaves sliver ring faces that
    # STEP cannot carry (p14: 56 two-wire planar faces with near-equal loop areas). Reuse the identical polyline.
    out = []
    for L in Ls:
        aL = abs(loop_area(np.r_[L, L[:1]])); cL = L.mean(0); hit = None
        for C in LOOP_CACHE:
            aC = abs(loop_area(np.r_[C, C[:1]]))
            if abs(aC - aL) > 2e-3 * max(aC, aL) or np.linalg.norm(C.mean(0) - cL) > tol * 5: continue
            # every point of L within tol*5 of C's points (symmetric enough for near-identical outlines)
            idx = np.linspace(0, len(L) - 1, min(len(L), 60)).astype(int)
            d = np.min(np.linalg.norm(L[idx][:, None, :] - C[None, :, :], axis=2), axis=1)
            if d.max() <= tol * 5: hit = C; break
        if hit is None: LOOP_CACHE.append(L); out.append(L)
        else: out.append(hit)
    return out

def build_level(tri, ax, z_lo, z_hi, h_mid):
    Ls = [dedupe(l) for l in loops(section2d(tri, ax, h_mid)) if len(l) > 3]
    Ls = [l for l in Ls if abs(loop_area(np.r_[l, l[:1]])) > 1e-3]
    import auto2d as _a2s
    Ls = snap_loops(Ls, max(_a2s.LINE_TOL, 0.02))
    if not Ls: return None, 0
    Ls.sort(key=lambda l: -abs(loop_area(np.r_[l, l[:1]])))
    # nesting: a loop is a hole if it lies inside an odd number of larger loops (test one point)
    def inside(pt, L):
        x, y = pt; c = False; n = len(L)
        for i in range(n):
            x1, y1 = L[i]; x2, y2 = L[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-300) + x1: c = not c
        return c
    depth = [sum(1 for j in range(i) if inside(Ls[i][0], Ls[j])) for i in range(len(Ls))]
    solids = []
    for i, L in enumerate(Ls):
        if depth[i] % 2: continue
        holes = [Ls[j] for j in range(len(Ls)) if depth[j] == depth[i] + 1 and inside(Ls[j][0], L)]
        import auto2d as _a2
        base_tol = _a2.LINE_TOL; f = None
        for shrink in (1, 4, 16, 64):   # a coarse outline can cross a hole: back off until the face checks valid
            _a2.LINE_TOL = _a2.ARC_TOL = max(0.02, base_tol / shrink)
            wires = [build_wire(*segment_loop(l), ax, z_lo) for l in [L] + holes]
            mf = BRepBuilderAPI_MakeFace(wires[0], True)
            for w in wires[1:]: mf.Add(w)
            f = mf.Face(); sff = ShapeFix_Face(f); sff.FixOrientation(); sff.Perform(); f = sff.Face()
            if BRepCheck_Analyzer(f, True).IsValid():
                if shrink > 1: print("    face valid after tolerance /%d (%.4f)" % (shrink, _a2.LINE_TOL), flush=True)
                break
            if _a2.LINE_TOL <= 0.02: break
        _a2.LINE_TOL = _a2.ARC_TOL = base_tol
        d = [0.0, 0.0, 0.0]; d[ax] = z_hi - z_lo
        solids.append(BRepPrimAPI_MakePrism(f, gp_Vec(*d)).Shape())
    return solids, len(Ls)

def repair_step_shape(shape):
    """Repair the sliver faces the level fuse leaves at its junctions after a STEP round trip.

    Adjacent levels are prisms of outlines traced at different slice heights, so the fuse exposes
    thin shelf faces bounded by two near-coincident arcs. The STEP reader reparametrises those
    arcs by a few 1e-13, which is enough to tip BRepCheck_Wire::SelfIntersect (a domain-based
    intersection on the periodic circle pcurves) into a false SelfIntersectingWire. Replacing each
    conic arc with a non-periodic BSpline removes the periodic pcurve the test mis-reads;
    SameParameter then rebuilds the pcurves and ShapeFix_Shape repairs the wires. The geometry is
    unchanged (ApproxCurve tolerance 1e-9: volume shifts by <1e-6 %)."""
    from OCP.BRep import BRep_Builder, BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepLib import BRepLib
    from OCP.Geom import Geom_TrimmedCurve
    from OCP.GeomAbs import GeomAbs_C1, GeomAbs_Line
    from OCP.GeomConvert import GeomConvert_ApproxCurve
    from OCP.ShapeFix import ShapeFix_Shape
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    b = BRep_Builder()
    # Only the edges of the faces that actually came back invalid. Converting every conic in the
    # shape also works, but it costs the thing this tool exists to produce: a circular edge is an
    # editable parameter (select it, re-fillet it, read a hole off it), a BSpline through the same
    # points is not. Measured on mechparts/39: 12 faces are broken, yet the blanket pass replaced
    # 302 of 572 edges; on /6, 8 faces and 899 of 2458 edges. Scoped here to those faces only.
    from OCP.BRepCheck import BRepCheck_Analyzer as _An
    from OCP.TopAbs import TopAbs_FACE as _FACE
    _an = _An(shape, True)
    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, _FACE, faces)
    edges = TopTools_IndexedMapOfShape()
    for fi in range(1, faces.Extent() + 1):
        f_ = faces.FindKey(fi)
        if not _an.IsValid(f_):
            TopExp.MapShapes_s(f_, TopAbs_EDGE, edges)
    for i in range(1, edges.Extent() + 1):
        e = TopoDS.Edge_s(edges.FindKey(i))
        ac = BRepAdaptor_Curve(e)
        if ac.GetType() == GeomAbs_Line:
            continue
        t0, t1 = ac.FirstParameter(), ac.LastParameter()
        try:
            ap = GeomConvert_ApproxCurve(Geom_TrimmedCurve(BRep_Tool.Curve_s(e, 0.0, 0.0), t0, t1),
                                         1e-9, GeomAbs_C1, 200, 14)
        except Exception:  # noqa: BLE001 - a degenerate arc must not abort the whole repair
            continue
        if ap.IsDone():
            b.UpdateEdge(e, ap.Curve(), BRep_Tool.Tolerance_s(e))
    BRepLib.SameParameter_s(shape, 1e-7, True)
    sfx = ShapeFix_Shape(shape)
    sfx.SetPrecision(1e-6)
    sfx.SetMaxTolerance(1.0)
    sfx.SetMinTolerance(1e-7)
    wt = sfx.FixWireTool()
    wt.ModifyTopologyMode = True
    wt.ModifyGeometryMode = True
    wt.FixSelfIntersectionMode = 1
    wt.FixSelfIntersectingEdgeMode = 1
    wt.FixIntersectingEdgesMode = 1
    wt.FixNonAdjacentIntersectingEdgesMode = 1
    wt.FixReorderMode = 1
    wt.FixConnectedMode = 1
    wt.FixEdgeCurvesMode = 1
    wt.FixSameParameterMode = 1
    wt.FixSmallMode = 1
    sfx.FixFaceTool().FixWireMode = 1
    sfx.FixSolidMode = 1
    sfx.FixShellTool().FixFaceMode = 1
    sfx.Perform()
    return sfx.Shape()

def main():
    t0 = time.time()
    tri = load(sys.argv[1]); N = int(sys.argv[3]) if len(sys.argv) > 3 else 80
    lo = tri.reshape(-1, 3).min(0); hi = tri.reshape(-1, 3).max(0)
    # segmentation tolerance scales with the part: 0.02 mm is right for a 100 mm part, absurd for a 5 m one
    import auto2d as _a2
    diag = float(np.linalg.norm(hi - lo))
    _a2.LINE_TOL = _a2.ARC_TOL = max(0.02, 2e-4 * diag)
    print("part diagonal %.1f -> segmentation tolerance %.4f" % (diag, _a2.LINE_TOL), flush=True)
    best = None
    for ax in range(3):
        hs, sig, lv = levels_for_axis(tri, ax, lo, hi, N)
        # prefer few levels; ignore 1-sample transition levels when counting
        real = [l for l in lv if l[1] - l[0] + 1 >= 2]
        score = (len(real), len(lv))
        print("axis %s levels %d (runs>=2: %d)" % ("XYZ"[ax], len(lv), len(real)), flush=True)
        if best is None or score < best[0]: best = (score, ax, hs, sig, lv)
    _, ax, hs, sig, lv = best
    import os
    if os.environ.get("AXIS") in ("0", "1", "2"):
        ax = int(os.environ["AXIS"]); hs, sig, lv = levels_for_axis(tri, ax, lo, hi, N)
    step = hs[1] - hs[0]
    # merge 1-sample transition runs into the neighbour whose signature is closest in area
    runs = [l[:] for l in lv]
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            if r[1] - r[0] + 1 < 2:
                a = sig[r[0]][1]
                nb = [j for j in (i - 1, i + 1) if 0 <= j < len(runs)]
                j = min(nb, key=lambda j: abs(sig[runs[j][0]][1] - a))
                runs[j] = [min(runs[j][0], r[0]), max(runs[j][1], r[1])]
                runs.pop(i); changed = True; break
    print("chosen axis %s, %d levels after merging transitions" % ("XYZ"[ax], len(runs)), flush=True)
    # refine every level boundary by bisection on the section signature between the neighbouring samples:
    # the step height of a machined level is a single z, not "somewhere between two samples"
    def same_level(h, ref):
        n, a, _ = material_area(tri, ax, h)
        return n == ref[0] and abs(a - ref[1]) <= 0.002 * max(ref[1], 1e-9)
    bounds = {}
    for k in range(len(runs) - 1):
        i_last, i_next = runs[k][1], runs[k + 1][0]
        ref_lo = sig[(runs[k][0] + runs[k][1]) // 2]
        a, b = hs[i_last], hs[i_next]
        for _ in range(14):
            m = 0.5 * (a + b)
            if same_level(m, ref_lo): a = m
            else: b = m
        bounds[k] = 0.5 * (a + b)
    parts = []
    for k, (i0, i1) in enumerate(runs):
        z_lo = lo[ax] if k == 0 else bounds[k - 1]
        z_hi = hi[ax] if k == len(runs) - 1 else bounds[k]
        # profile from the most central slice of the run
        h_mid = hs[(i0 + i1) // 2]
        solids, nl = build_level(tri, ax, z_lo, z_hi, h_mid)
        print("  level %d: z %.3f..%.3f loops %d solids %d area %.2f" % (k, z_lo, z_hi, nl, len(solids or []), sig[(i0 + i1) // 2][1]), flush=True)
        parts.extend(solids or [])
    shape = parts[0]
    for s in parts[1:]:
        shape = BRepAlgoAPI_Fuse(shape, s).Shape()
    import os
    if os.environ.get("NOUNIFY") != "1":
        u = ShapeUpgrade_UnifySameDomain(shape, True, True, False); u.Build(); shape = u.Shape()
    if os.environ.get("FIXWRITE") == "1":
        from OCP.ShapeFix import ShapeFix_Shape
        sfx0 = ShapeFix_Shape(shape); sfx0.Perform(); shape = sfx0.Shape()
        print("ShapeFix_Shape before write", flush=True)
    if not BRepCheck_Analyzer(shape, True).IsValid():
        from OCP.ShapeFix import ShapeFix_Shape
        sfx = ShapeFix_Shape(shape); sfx.Perform(); shape = sfx.Shape()
        print("final shape invalid -> ShapeFix_Shape: valid now %s" % BRepCheck_Analyzer(shape, True).IsValid(), flush=True)
    shape = augment(shape, tri)   # radial fillets have no representation in this stepped builder
    census = {"plane": 0, "cylinder": 0, "torus": 0, "cone": 0, "other": 0}
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        ty = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()
        census["plane" if ty == GeomAbs_Plane else "cylinder" if ty == GeomAbs_Cylinder else "torus" if ty == GeomAbs_Torus else "cone" if ty == GeomAbs_Cone else "other"] += 1
        ex.Next()
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g)
    mvol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
    print("model valid %s volume %.3f mesh %.3f delta %.3f%% faces %s  [%.1fs]" % (
        BRepCheck_Analyzer(shape, True).IsValid(), g.Mass(), mvol, 100 * (g.Mass() - mvol) / mvol, census, time.time() - t0), flush=True)
    b = BRep_Builder(); comp = TopoDS_Compound(); b.MakeCompound(comp)
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        b.Add(comp, ex.Current()); ex.Next()
    verts = np.unique(tri.reshape(-1, 3).round(6), axis=0); random.seed(5); dd = []
    for i in random.sample(range(len(verts)), min(600, len(verts))):
        ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*verts[i])).Vertex(), comp); ds.Perform(); dd.append(ds.Value())
    dd = np.array(dd)
    print("mesh->model faces: mean %.4f p95 %.4f max %.4f" % (dd.mean(), np.percentile(dd, 95), dd.max()), flush=True)
    if os.environ.get("DUMP_BREP"):
        from OCP.BRepTools import BRepTools
        BRepTools.Write_s(shape, os.environ["DUMP_BREP"]); print("dumped", os.environ["DUMP_BREP"], flush=True)
    Interface_Static.SetCVal_s("write.step.schema", "AP214")
    w = STEPControl_Writer(); w.Transfer(shape, STEPControl_AsIs); ok = w.Write(sys.argv[2]) == IFSelect_RetDone
    r = STEPControl_Reader(); r.ReadFile(sys.argv[2]); r.TransferRoots()
    back = r.OneShape(); anb = BRepCheck_Analyzer(back, True)
    if not anb.IsValid():
        back = repair_step_shape(back)
        w = STEPControl_Writer()
        w.Transfer(back, STEPControl_AsIs)
        ok = w.Write(sys.argv[2]) == IFSelect_RetDone
        r = STEPControl_Reader()
        r.ReadFile(sys.argv[2])
        r.TransferRoots()
        back = r.OneShape()
        anb = BRepCheck_Analyzer(back, True)
        print("STEP re-read invalid -> repaired, now valid %s" % anb.IsValid(), flush=True)
    nbad = 0
    exb = TopExp_Explorer(back, TopAbs_FACE)
    while exb.More():
        rb = anb.Result(exb.Current())
        if rb is not None and any(str(x).split(".")[-1] != "BRepCheck_NoError" for x in rb.Status()): nbad += 1
        exb.Next()
    print("STEP %s; re-read valid %s invalid faces %d" % (ok, anb.IsValid(), nbad), flush=True)

if __name__ == "__main__":
    main()
