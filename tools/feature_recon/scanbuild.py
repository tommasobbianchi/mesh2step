"""B-rep from a cleaned scan (denoise.py): one face per region ON its fitted analytic surface, bounded by the region's
own border in the cleaned mesh, sewn at the scan's noise.

Why not edgebuild: edgebuild solves every corner as the exact common point of its surfaces. On a scan, surfaces fitted
within the noise often share no such point (mechpart: ~40 of ~130 corners), so an exact-CAD builder cannot finish.
Here no corner is solved: a border between two regions is one curve through the cleaned mesh's border vertices, the
SAME curve for both faces, and sewing closes what the noise leaves open. The faces are exact planes, cylinders, cones,
spheres and tori; the edges follow the scan. Triangles in no region stay as small planar faces.

usage: scanbuild.py <clean.stl> <labels.npz> <out.step>        (one RESULT {json} line on stdout)"""
import json
import math
import os
import sys

import numpy as np
import trimesh
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon,
                                BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Sewing)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLib import BRepLib
from OCP.Geom import (Geom_ConicalSurface, Geom_CylindricalSurface, Geom_Plane, Geom_SphericalSurface,
                      Geom_ToroidalSurface)
from OCP.GeomAbs import GeomAbs_C2
from OCP.GeomAPI import GeomAPI_PointsToBSpline
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt
from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Shape
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS


def pnt(x):
    return gp_Pnt(*map(float, x))


def gdir(x):
    return gp_Dir(*map(float, x))


def frame(a):
    u = np.cross(a, [1.0, 0, 0] if abs(a[0]) < 0.9 else [0, 1.0, 0]); u /= np.linalg.norm(u)
    return u, np.cross(a, u)


def surface(s, P, nrm=None):
    """The region's fitted surface as an OCC surface; the seam and reference direction away from its vertices P."""
    k = s["kind"]
    if k == "plane":
        n = np.array(s["n"]); c = P.mean(0); c = c - (c @ n - s["d"]) * n
        if nrm is not None and n @ nrm < 0:
            n = -n                                     # the plane's normal as the region's: its loops then run outer-CCW
        return Geom_Plane(gp_Ax3(pnt(c), gdir(n), gdir(frame(n)[0])))
    if k == "sphere":
        # the region on the equator with the seam opposite it, as edgebuild.geom_surface: a pole inside the region
        # made ShapeFix_Face keep the complement (mechpart: 1413 mm2 for a 741 mm2 cap)
        o = np.array(s["o"]); d = P.mean(0) - o
        X = -d / np.linalg.norm(d) if np.linalg.norm(d) > 1e-9 else np.array([1.0, 0, 0])
        return Geom_SphericalSurface(gp_Ax3(pnt(o), gdir(frame(X)[0]), gdir(X)), float(s["R"]))
    a = np.array(s["a"]) / np.linalg.norm(s["a"]); o = np.array(s["o"])
    q = P - o; h = q @ a; radial = (q - np.outer(h, a)).mean(0)
    X = -radial / np.linalg.norm(radial) if np.linalg.norm(radial) > 1e-9 else frame(a)[0]   # seam opposite the region
    X = X - (X @ a) * a; X /= np.linalg.norm(X)
    if k == "cylinder":
        return Geom_CylindricalSurface(gp_Ax3(pnt(o + a * h.mean()), gdir(a), gdir(X)), float(s["R"]))
    if k == "cone":
        k1, k0 = s["k"]                                  # rho = k1 h + k0, h from o along a
        if k1 < 0:
            a, k1, h = -a, -k1, -h
        href = float(h.mean())
        return Geom_ConicalSurface(gp_Ax3(pnt(o + a * href), gdir(a), gdir(X)), math.atan(k1), k1 * href + k0)
    return Geom_ToroidalSurface(gp_Ax3(pnt(o + a * s["hc"]), gdir(a), gdir(X)), float(s["Rc"]), float(s["r"]))


def loops(F, label, L, twin):
    """Closed boundary loops of region L as vertex-id lists, following the faces' orientation."""
    out_he = {}
    for t in np.where(label == L)[0]:
        for i in range(3):
            a, b = int(F[t][i]), int(F[t][(i + 1) % 3])
            if label[twin[(b, a)]] != L:
                out_he.setdefault(a, []).append(b)
    used, result = set(), []
    for a0 in list(out_he):
        for b0 in out_he[a0]:
            if (a0, b0) in used:
                continue
            loop = [a0]; a, b = a0, b0
            while (a, b) not in used:
                used.add((a, b)); loop.append(b)
                nxt = [c for c in out_he.get(b, []) if (b, c) not in used]
                if not nxt:
                    break
                a, b = b, nxt[0]
            if loop[-1] == loop[0]:
                result.append(loop[:-1])
    return result


def _loop_winding(P, n):
    """How many times the polygon P winds about its centroid as seen along n (1 = simple loop)."""
    C = P.mean(0); u, v = frame(n)
    Q = np.stack([(P - C) @ u, (P - C) @ v], 1)
    a = np.arctan2(Q[:, 1], Q[:, 0])
    d = np.diff(np.append(a, a[0]))
    return float(abs(np.arctan2(np.sin(d), np.cos(d)).sum())) / (2 * math.pi)


def _seg_intersect(p, q, r, s):
    """True when segments pq and rs touch or cross (shared endpoints count: a pinched border is no border)."""
    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2, d3, d4 = o(r, s, p), o(r, s, q), o(p, q, r), o(p, q, s)
    if ((d1 > 0) != (d2 > 0) or d1 == 0 or d2 == 0) and ((d3 > 0) != (d4 > 0) or d3 == 0 or d4 == 0):
        return True
    return False


def _loops_intersect(XY):
    """True when any two boundary loops touch or cross each other (one loop's own closure included)."""
    segs = []
    for poly in XY:
        n = len(poly)
        segs.append([(poly[i], poly[(i + 1) % n]) for i in range(n)])
    for a in range(len(segs)):
        for b in range(a, len(segs)):
            for i, (p, q) in enumerate(segs[a]):
                for j, (r, s) in enumerate(segs[b]):
                    if a == b and (j == i or j == (i + 1) % len(segs[a]) or i == (j + 1) % len(segs[a])):
                        continue                      # adjacent segments of one loop always share a vertex
                    if _seg_intersect(p, q, r, s):
                        return True
    return False


def _sphere_outward_ok(f, o):
    """Majority vote over interior samples: do the face's oriented normals point away from the sphere centre?

    Sums cancel on nearly-closed caps, so each sample votes independently. The reference direction is exact
    (radial), which mesh area-weighted normals are not once a region wraps most of its sphere."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCP.gp import gp_Pnt2d
    from OCP.TopAbs import TopAbs_IN
    ad = BRepAdaptor_Surface(f)
    u0, u1, v0, v1 = ad.FirstUParameter(), ad.LastUParameter(), ad.FirstVParameter(), ad.LastVParameter()
    cls = BRepTopAdaptor_FClass2d(f, 1e-7)
    g = GProp_GProps(); BRepGProp.SurfaceProperties_s(f, g)
    sgn = 1.0 if g.Mass() >= 0 else -1.0   # orientation state of the face relative to its surface
    agree, disagree = 0, 0
    for u in np.linspace(u0, u1, 9)[1:-1]:
        for v in np.linspace(v0, v1, 9)[1:-1]:
            if cls.Perform(gp_Pnt2d(u, v)) != TopAbs_IN:
                continue
            pr = BRepLProp_SLProps(ad, u, v, 1, 1e-9)
            if not pr.IsNormalDefined():
                continue
            try:
                du, dv = pr.D1U(), pr.D1V()
            except Exception:                  # noqa: BLE001 - pole or seam sample: no tangent frame
                continue
            n = du.Crossed(dv)
            if n.Magnitude() < 1e-12:
                continue
            p = pr.Value()
            pv = np.array([p.X(), p.Y(), p.Z()]) - o
            if sgn * (n.X() * pv[0] + n.Y() * pv[1] + n.Z() * pv[2]) > 0:
                agree += 1
            else:
                disagree += 1
    return agree >= disagree


def _bad_topology(s, lps, V):
    """True when a region's border loops cannot bound one analytic face: a multi-loop sphere (closed-surface wire
    nesting fails in UV space), a sphere loop winding ~0x instead of once (a self-wrapping border), or plane loops
    that touch or cross (no clean outer+holes nesting)."""
    if s["kind"] == "sphere":
        if len(lps) > 1:
            return True
        if len(lps) == 1 and len(lps[0]) > 3:
            P = V[lps[0]]
            if _loop_winding(P, P.mean(0) - np.array(s["o"], float)) < 0.5:
                return True
        return False
    if s["kind"] == "plane" and len(lps) > 1:
        # centroid-in-polygon tests look clean on mechpart 1/5 yet both sew unorientable: test what OCCT needs,
        # pairwise loop intersection in the plane's own frame
        n = np.array(s["n"], float); n /= np.linalg.norm(n)
        u, v = frame(n)
        if _loops_intersect([np.stack([(V[lp] @ u), (V[lp] @ v)], 1) for lp in lps]):
            return True
    return False


def build(mesh, z, out, facet=frozenset()):
    V, F = mesh.vertices, mesh.faces
    diag = float(np.linalg.norm(mesh.extents))
    label = np.array(z["label"]).copy()
    surfs = json.loads(str(z["surf"]))
    # match the npz's per-face labels to this mesh by face centre (same mesh, maybe reordered)
    from scipy.spatial import cKDTree
    d, j = cKDTree(z["centres"]).query(mesh.triangles_center)
    label = np.where(d < 1e-6 * diag, label[j], -1)
    nreg = len(surfs)
    for t in np.where(label < 0)[0]:                   # a triangle in no region is its own planar face
        label[t] = nreg; nreg += 1
        nn = mesh.face_normals[t]
        surfs.append({"kind": "plane", "n": nn.tolist(), "d": float(nn @ V[F[t][0]])})
    twin = {}
    for t, f in enumerate(F):
        for i in range(3):
            twin[(int(f[i]), int(f[(i + 1) % 3]))] = t
    tol = float(z["tol"]) if "tol" in z.files else 1e-3 * diag
    vert = {}
    def vtx(i):
        if i not in vert:
            vert[i] = BRepBuilderAPI_MakeVertex(pnt(V[i])).Vertex()
        return vert[i]
    edges = {}
    def chain_edge(ids):
        """One edge through the border vertices ids, shared by both regions it separates."""
        key = tuple(ids) if ids[0] < ids[-1] or (ids[0] == ids[-1] and ids[1] < ids[-2]) else tuple(reversed(ids))
        rev = tuple(ids) != key
        if key not in edges:
            P = V[list(key)]
            e = None
            # ponytail: straight segments only (SB_BSPLINE=1 tries one B-spline per chain): the approximated spline's ends
            # missed the shared corner vertices, the wires did not close and plane faces came out 35x their region
            if len(key) > 2 and os.environ.get("SB_BSPLINE"):
                arr = TColgp_Array1OfPnt(1, len(key))
                for i_, p_ in enumerate(P):
                    arr.SetValue(i_ + 1, pnt(p_))
                try:
                    c = GeomAPI_PointsToBSpline(arr, 1, 3, GeomAbs_C2, max(tol * 0.1, 1e-4)).Curve()
                    mk = BRepBuilderAPI_MakeEdge(c, vtx(key[0]), vtx(key[-1]))
                    e = mk.Edge() if mk.IsDone() else None
                except Exception:                      # noqa: BLE001 - a degenerate chain: polyline below
                    e = None
            if e is None:                              # straight segments through the border vertices
                poly = BRepBuilderAPI_MakePolygon()
                for i_ in key:
                    poly.Add(vtx(i_))
                e = poly.Wire()
            edges[key] = e
        base = edges[key]
        if not rev:
            return base
        # the cached wire runs in canonical (vertex-id) order: rebuild it in the caller's traversal direction. A
        # bare Reversed() is not enough: TopExp_Explorer below yields edges in stored sequence order, ignoring the
        # wire-level orientation flag, so the loop would still feed canonical order downstream.
        seq = []
        ex0 = TopExp_Explorer(base, TopAbs_EDGE)
        while ex0.More():
            seq.append(TopoDS.Edge_s(ex0.Current())); ex0.Next()
        mw0 = BRepBuilderAPI_MakeWire()
        for e0 in reversed(seq):
            mw0.Add(TopoDS.Edge_s(e0.Reversed()))
        return mw0.Wire()

    faces, n_fail = [], 0
    for L in range(nreg):
        if not (label == L).any():
            continue
        lps = loops(F, label, L, twin)
        # borders that cannot bound one analytic face go straight to triangles, on every pass: reintroducing them
        # rebuilds the same invalid face (mechpart sphere 20 came back as an 8301 mm2 invalid cap)
        force_facet = _bad_topology(surfs[L], lps, V)
        wires = []
        for lp in (lps if not force_facet else []):
            nb = [int(label[twin[(lp[(i + 1) % len(lp)], lp[i])]]) for i in range(len(lp))]  # neighbour past edge i
            cuts = [i for i in range(len(lp)) if nb[i] != nb[i - 1]]
            if len(cuts) < 2:                          # one neighbour all round: split the loop in two edges
                cuts = [0, len(lp) // 2]
            # every edge of the loop into ONE list: MakeWire.Add(list) connects them in any order (a chain shared with
            # the neighbour is stored once, so on one side its segments come reversed and edge-by-edge Add stopped there)
            from OCP.TopTools import TopTools_ListOfShape
            lst = TopTools_ListOfShape()
            for ci, c0 in enumerate(cuts):
                c1 = cuts[(ci + 1) % len(cuts)]
                ids = [lp[i % len(lp)] for i in range(c0, c1 + (len(lp) if c1 <= c0 else 0) + 1)]
                ex = TopExp_Explorer(chain_edge(ids), TopAbs_EDGE)   # one B-spline edge, or a polyline's segments
                while ex.More():
                    lst.Append(ex.Current()); ex.Next()
            mw = BRepBuilderAPI_MakeWire(); mw.Add(lst)
            if mw.IsDone() and mw.Wire().Closed():
                wires.append(mw.Wire())
        if not wires and not force_facet:
            if os.environ.get("SB_DEBUG"):
                print(f"NOWIRES {L} {surfs[L]['kind']} loops {len(lps)} tris {int((label == L).sum())}",
                      file=sys.stderr, flush=True)
            n_fail += 1; continue
        P = V[np.unique(F[label == L])]
        nrm = (mesh.face_normals[label == L] * mesh.area_faces[label == L, None]).sum(0)
        gs = surface(surfs[L], P, nrm)
        nrm_ = (mesh.face_normals[label == L] * mesh.area_faces[label == L, None]).sum(0)
        # outer boundary first: on a plane the loop enclosing the most area, elsewhere the longest
        if surfs[L]["kind"] == "plane":
            npl = np.array(surfs[L]["n"]); npl = npl if npl @ nrm_ >= 0 else -npl
            wires.sort(key=lambda w: -_plane_area(w, npl))
            # outer counter-clockwise about the face normal, every hole clockwise (a hole running the outer's way made
            # the face "unorientable": 6 of 7 invalid faces on mechpart)
            wires = [w if (_plane_area(w, npl, True) > 0) == (i == 0) else TopoDS.Wire_s(w.Reversed())
                     for i, w in enumerate(wires)]
        else:
            wires.sort(key=lambda w: -_wire_len(w))
        if os.environ.get("SB_DEBUG"):
            print(f"face {L} {surfs[L]['kind']} loops {len(wires)} tris {int((label == L).sum())}", file=sys.stderr, flush=True)
        # the face must cover what the region covers: on a closed surface (sphere, torus, full cone) a loop bounds two
        # faces and OCCT may keep the other one (mechpart: a sphere face of 5698 mm2 for a 234 mm2 region). Both
        # orientations are tried; one within 25 % of the region's mesh area wins, else the region stays faceted.
        am = float(mesh.area_faces[label == L].sum())
        f, best_err = None, None; tried_a = []
        for ws in (() if force_facet else (wires, [TopoDS.Wire_s(w.Reversed()) for w in wires])):
            c = forked_face(gs, ws, max(tol, 1e-5 * diag), surfs[L]["kind"] in ("plane", "sphere"))
            if c is None:
                continue
            g_ = GProp_GProps(); BRepGProp.SurfaceProperties_s(c, g_)
            err = max(abs(abs(g_.Mass()) - am) - tol * tol, 0.0) / max(am, 1e-12)   # tol^2: slivers
            tried_a.append(round(g_.Mass(), 1))
            if best_err is None or err < best_err:
                f, best_err = c, err
        # validity is judged AFTER sewing (sewing fixes most edge tolerances: 7 of 914 faces invalid, against 69 regions
        # rejected when judged before, and ShapeFix_Shape per face rebuilt the edges so nothing sewed: 677 free edges)
        if f is not None and (best_err > 0.25 or L in facet):
            f = None                                   # wrong area, or invalid once sewn: the region stays faceted
        if f is None and os.environ.get("SB_DEBUG"):
            print(f"FAILED {L} {surfs[L]['kind']} loops {len(wires)} tris {int((label == L).sum())} mesh area {am:.1f} "
                  f"attempts {tried_a}", file=sys.stderr, flush=True)
        if f is None:                                  # OCCT crashed or refused: this region stays faceted
            n_fail += 1
            for t in np.where(label == L)[0]:
                poly = BRepBuilderAPI_MakePolygon(vtx(int(F[t][0])), vtx(int(F[t][1])), vtx(int(F[t][2])), True)
                mf = BRepBuilderAPI_MakeFace(poly.Wire(), True)
                if mf.IsDone():
                    faces.append((mf.Face(), L))
            continue
        if surfs[L]["kind"] == "sphere":
            # radial majority vote, not the mesh normal sum: once a region wraps most of its sphere the summed
            # normals cancel to noise and the face below comes out pointing inward, doubling the volume
            if not _sphere_outward_ok(f, np.array(surfs[L]["o"], float)):
                f = TopoDS.Face_s(f.Reversed())
        elif _face_normal(f) @ nrm < 0:              # the face looks where the region's triangles look
            f = TopoDS.Face_s(f.Reversed())
        faces.append((f, L))
        if os.environ.get("SB_DEBUG"):
            g_ = GProp_GProps(); BRepGProp.SurfaceProperties_s(f, g_)
            am = float(mesh.area_faces[label == L].sum())
            print(f"face {L} {surfs[L]['kind']} loops {len(wires)} area {g_.Mass():.1f} vs mesh {am:.1f}", file=sys.stderr, flush=True)
    sew = BRepBuilderAPI_Sewing(max(2 * tol, 1e-5 * diag))
    for f, _ in faces:
        sew.Add(f)
    sew.Perform()
    shape = sew.SewedShape()
    # tolerances fixed on the WHOLE sewn shell, where edges are shared (per face it rebuilt them: 677 free edges)
    wf = ShapeFix_Shape(shape); wf.SetPrecision(max(tol, 1e-5 * diag)); wf.SetMaxTolerance(3 * tol); wf.Perform()
    shape = wf.Shape()
    bad_regions = set(); why = {}
    for f_, L_ in faces:
        g_ = wf.Context().Apply(sew.Modified(f_))
        exg = TopExp_Explorer(g_, TopAbs_FACE)
        while exg.More():
            if not BRepCheck_Analyzer(exg.Current()).IsValid():
                bad_regions.add(L_)
                an = BRepCheck_Analyzer(exg.Current()); rs = an.Result(exg.Current())
                for st in rs.Status():
                    why[str(st).split(".")[-1]] = why.get(str(st).split(".")[-1], 0) + 1
            exg.Next()
    fix = ShapeFix_Shape(shape); fix.Perform(); shape = fix.Shape()
    # the largest sewn shell becomes the solid (a scan is one body); the others are reported, not kept
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from OCP.ShapeFix import ShapeFix_Solid
    shells = []
    ex = TopExp_Explorer(shape, TopAbs_SHELL)
    while ex.More():
        sh_ = TopoDS.Shell_s(ex.Current()); nf_ = 0; fx_ = TopExp_Explorer(sh_, TopAbs_FACE)
        while fx_.More():
            nf_ += 1; fx_.Next()
        shells.append((nf_, sh_)); ex.Next()
    shells.sort(key=lambda q: -q[0])
    solid = None
    if shells:
        from OCP.ShapeFix import ShapeFix_Shell
        fs = ShapeFix_Shell(shells[0][1]); fs.Perform()      # one consistent orientation across the shell
        sh0 = fs.Shell()
        sf = ShapeFix_Solid(BRepBuilderAPI_MakeSolid(sh0).Solid()); sf.Perform()
        ex = TopExp_Explorer(sf.Solid(), TopAbs_SOLID)
        if ex.More():
            solid = TopoDS.Solid_s(ex.Current()); BRepLib.OrientClosedSolid_s(solid)
    res = {"faces_in": len(faces), "faces_failed": n_fail, "bad_regions": sorted(bad_regions), "bad_why": why, "free_edges": sew.NbFreeEdges(),
           "shells": [q[0] for q in shells[:5]], "solid": solid is not None}
    target = solid if solid is not None else shape
    res["valid"] = bool(BRepCheck_Analyzer(target).IsValid())
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(target, g)
    res["volume"] = round(g.Mass(), 1); res["mesh_volume"] = round(float(mesh.volume), 1)
    kinds = {}
    ex = TopExp_Explorer(target, TopAbs_FACE); nfaces = 0
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    names = {0: "plane", 1: "cylinder", 2: "cone", 3: "sphere", 4: "torus"}
    while ex.More():
        t_ = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()
        kinds[names.get(int(t_), "other")] = kinds.get(names.get(int(t_), "other"), 0) + 1; nfaces += 1; ex.Next()
    res["faces"] = nfaces; res["kinds"] = kinds
    res["analytic_planes"] = sum(1 for _f, L_ in faces if surfs[L_]["kind"] == "plane" and int((label == L_).sum()) > 1
                                 and L_ < len(json.loads(str(z["surf"]))) and L_ not in facet)
    w = STEPControl_Writer(); w.Transfer(target, STEPControl_AsIs); w.Write(str(out))
    return res


def forked_face(gs, wires, prec, plane=False):
    """The face on surface gs bounded by wires, built in a forked child: OCCT segfaults on some (mechpart: a cone
    region bounded by one loop, as edgebuild's apex cone). None when the child dies or fails."""
    import tempfile
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape
    fd, path = tempfile.mkstemp(suffix=".brep"); os.close(fd)
    pid = os.fork()
    if pid == 0:
        try:
            # Direct MakeFace first for planes AND spheres: it trims by the wires as given, keeping the side the
            # wire orientation selects (an outward mesh gives CCW-from-outside loops, i.e. the cap). ShapeFix_Face
            # on the bare surface instead "repairs" UV orientation, which on a closed surface swaps the material
            # side: mechpart sphere caps selected at 540/209 mm2 came out as 8301/5740 mm2 complements downstream.
            # MakeFace refuses seam-crossing wires, so ShapeFix stays as fallback (and the 25 % area check guards).
            face = None
            if plane:
                mf = BRepBuilderAPI_MakeFace(gs, wires[0], True)
                for w in wires[1:]:
                    mf.Add(w)
                if mf.IsDone() and not mf.Face().IsNull():
                    face = mf.Face()
            if face is None:
                # ShapeFix_Face on the bare surface: it adds the wires, computes their curves on the surface (the
                # edges are 3D only) and the seam of a closed cylinder or torus band; MakeFace refuses exactly those
                fx = ShapeFix_Face(); fx.Init(gs, prec, True)
                for w in wires:
                    fx.Add(w)
                fx.Perform(); face = fx.Face()
            ok = BRepTools.Write_s(face, path)
            os._exit(0 if ok else 1)
        except BaseException:                          # noqa: BLE001
            os._exit(1)
    _, st = os.waitpid(pid, 0)
    try:
        if os.WIFEXITED(st) and os.WEXITSTATUS(st) == 0:
            from OCP.BRep import BRep_Builder
            sh = TopoDS_Shape()
            if BRepTools.Read_s(sh, path, BRep_Builder()):
                return TopoDS.Face_s(sh)
        return None
    finally:
        os.unlink(path)


def _plane_area(w, n, signed=False):
    """Area a closed wire encloses, projected on the plane with normal n (from its edges' sample points)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    pts = []
    from OCP.BRepTools import BRepTools_WireExplorer
    ex = BRepTools_WireExplorer(w)                     # edges in wire order and direction: the sign means something
    while ex.More():
        e_ = ex.Current(); c = BRepAdaptor_Curve(e_)
        us = np.linspace(c.FirstParameter(), c.LastParameter(), 8)
        from OCP.TopAbs import TopAbs_REVERSED as _R
        for u in (us[::-1] if e_.Orientation() == _R else us):
            p_ = c.Value(u); pts.append([p_.X(), p_.Y(), p_.Z()])
        ex.Next()
    P = np.array(pts); u_, v_ = frame(n); x, y = P @ u_, P @ v_
    a_ = 0.5 * float(x @ np.roll(y, -1) - y @ np.roll(x, -1))
    return a_ if signed else abs(a_)


def _face_normal(f):
    """True oriented normal of a face (area-weighted sum over a few interior samples)."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepLProp import BRepLProp_SLProps
    ad = BRepAdaptor_Surface(f)
    u0, u1, v0, v1 = ad.FirstUParameter(), ad.LastUParameter(), ad.FirstVParameter(), ad.LastVParameter()
    from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCP.gp import gp_Pnt2d
    from OCP.TopAbs import TopAbs_IN
    cls = BRepTopAdaptor_FClass2d(f, 1e-7)
    acc = np.zeros(3)
    for u in np.linspace(u0, u1, 9)[1:-1]:
        for v in np.linspace(v0, v1, 9)[1:-1]:
            if cls.Perform(gp_Pnt2d(u, v)) != TopAbs_IN:
                continue
            pr = BRepLProp_SLProps(ad, u, v, 1, 1e-9)
            if pr.IsNormalDefined():
                d = pr.Normal(); acc += [d.X(), d.Y(), d.Z()]
    g = GProp_GProps(); BRepGProp.SurfaceProperties_s(f, g)
    # the sign comes from the signed area, not the orientation flag: ShapeFix_Face on closed surfaces can return a
    # face whose wires run the wrong way yet marked FORWARD (mechpart spheres with correct area but inverted normals,
    # whose caps then doubled the solid's volume)
    return -acc if g.Mass() < 0 else acc


def _wire_len(w):
    g = GProp_GProps(); BRepGProp.LinearProperties_s(w, g); return g.Mass()


def build_until_valid(m, z, out, passes=3):
    """Regions whose face is invalid once sewn are rebuilt from their triangles, until none is."""
    facet = set()
    for _ in range(passes):
        r = build(m, z, out, frozenset(facet))
        if not r["bad_regions"] or set(r["bad_regions"]) <= facet:
            break
        facet |= set(r["bad_regions"])
    r["faceted_regions"] = len(facet)
    return r


if __name__ == "__main__":
    m = trimesh.load(sys.argv[1], force="mesh")
    print("RESULT " + json.dumps(build_until_valid(m, np.load(sys.argv[2]), sys.argv[3])))
