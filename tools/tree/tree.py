"""Feature tree (JSON) -> exact solid, and how well that solid explains the mesh.

The tree is the product: the LLM and the owner decide its STRUCTURE, deterministic code fills its numbers, and
one tree compiles to every output (STEP here, FreeCAD in fcstd.py). Format:

  {"units": "mm", "features": [
    {"id": "F1", "op": "pad" | "pocket", "label": "Plate", "axis": "X"|"Y"|"Z", "at": 0.0,
     "length": 6.0 | "through",                      # pad/pocket go from `at` along +axis (negative: -axis)
     "loops": [[{"t": "line", "p": [[u, v], [u, v]]},  # loop 0 = outline, the rest = holes in the sketch
                {"t": "arc", "p": [[u, v], [u, v], [u, v]]},        # start, a point on it, end
                {"t": "circle", "c": [u, v], "r": 2.0}], ...]},
    {"id": "F3", "op": "round" | "chamfer", "label": "...", "size": 0.5,
     "on": "F1", "cap": "top" | "bottom" | "both", "loops": "outer" | "inner" | "all"}]}

Sketch coordinates (u, v) are right-handed around the axis: X -> (Y, Z), Y -> (Z, X), Z -> (X, Y).
"""
import json
import sys

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment
from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

AX = {"X": 0, "Y": 1, "Z": 2}
UV = {"X": (1, 2), "Y": (2, 0), "Z": (0, 1)}
BIG = 1e4                                            # "through": far past any part


def to3(axis, u, v, h):
    p = [0.0, 0.0, 0.0]
    a, b = UV[axis]
    p[a], p[b], p[AX[axis]] = float(u), float(v), float(h)
    return p


def _wire(axis, h, loop):
    w = BRepBuilderAPI_MakeWire()
    P = lambda q: gp_Pnt(*to3(axis, q[0], q[1], h))
    for s in loop:
        if s["t"] == "line":
            e = BRepBuilderAPI_MakeEdge(GC_MakeSegment(P(s["p"][0]), P(s["p"][1])).Value()).Edge()
        elif s["t"] == "arc":
            e = BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(*(P(q) for q in s["p"])).Value()).Edge()
        else:
            n = [0.0, 0.0, 0.0]; n[AX[axis]] = 1.0
            e = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(P(s["c"]), gp_Dir(*n)), float(s["r"]))).Edge()
        w.Add(e)
    if not w.IsDone():
        raise ValueError("sketch loop does not close")
    return w.Wire()


def _offset_in(w, d):
    """The planar wire offset inward by d (mitred corners: a sharp corner stays sharp, as a chamfer leaves it)."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.GeomAbs import GeomAbs_Intersection
    area = lambda x: (lambda g: (BRepGProp.SurfaceProperties_s(BRepBuilderAPI_MakeFace(x, True).Face(), g), g.Mass())[1])(GProp_GProps())
    best = None
    for s in (d, -d):                                  # the sign that shrinks depends on the wire's orientation
        mk = BRepOffsetAPI_MakeOffset(w, GeomAbs_Intersection); mk.Perform(s)
        if mk.IsDone() and mk.Shape().ShapeType().name == "TopAbs_WIRE":
            ww = TopoDS.Wire_s(mk.Shape())
            if best is None or area(ww) < area(best):
                best = ww
    return best


def tapered(f, ch):
    """A pad whose outline rims are chamfered, built as one ruled loft: inset outline -> outline -> outline -> inset.
    Edge chamfers fail on near-tangent sketch junctions (OCCT refuses the whole chain even at 0.05 mm); this
    never selects an edge, and it is how a CAD user draws it too (a tapered pad)."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    axis, at, L = f["axis"], f["at"], float(f["length"])
    lo, hi = min(at, at + L), max(at, at + L)
    cb, ct = ch.get("bottom", 0.0), ch.get("top", 0.0)
    ws = []
    for h, inset in ((lo, cb), (lo + cb, 0), (hi - ct, 0), (hi, ct)):
        w = _wire(axis, h, f["loops"][0])
        if inset:
            w = _offset_in(w, inset)
            if w is None:
                return None
        if not ws or abs(h - ws[-1][0]) > 1e-9:
            ws.append((h, w))
    ts = BRepOffsetAPI_ThruSections(True, True)
    for _, w in ws:
        ts.AddWire(w)
    ts.CheckCompatibility(True); ts.Build()
    if not ts.IsDone() or not BRepCheck_Analyzer(ts.Shape()).IsValid():
        return None
    s = ts.Shape()
    for loop in f["loops"][1:]:                        # holes in the sketch stay straight
        g = dict(f, loops=[loop], length="through"); s = BRepAlgoAPI_Cut(s, prism(g)).Shape()
    return s


def prism(f):
    """The pad/pocket body alone: its sketch face swept along the axis."""
    axis, L = f["axis"], f["length"]
    at, L = (f["at"] - BIG / 2, BIG) if L == "through" else (f["at"], float(L))
    w0 = _wire(axis, at, f["loops"][0])
    if _signed_area(f["loops"][0]) < 0:
        w0.Reverse()
    mk = BRepBuilderAPI_MakeFace(w0, True)
    for loop in f["loops"][1:]:
        w = _wire(axis, at, loop)
        if _signed_area(loop) > 0:                   # holes run clockwise, whatever order their source gave
            w.Reverse()
        mk.Add(w)
    v = [0.0, 0.0, 0.0]; v[AX[axis]] = L
    return BRepPrimAPI_MakePrism(mk.Face(), gp_Vec(*v)).Shape()


def _signed_area(loop):
    """Shoelace area of a loop in (u, v): > 0 counter-clockwise. A circle counts as counter-clockwise (OCCT's)."""
    if len(loop) == 1 and loop[0]["t"] == "circle":
        return 1.0
    P = np.concatenate([_arc_pts(*x["p"], n=12)[:-1] if x["t"] == "arc" else np.array(x["p"][:1]) for x in loop])
    return float(0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1]))


def _edges(shape):
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        yield TopoDS.Edge_s(ex.Current()); ex.Next()


def _mid(e):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    c = BRepAdaptor_Curve(e)
    p = c.Value((c.FirstParameter() + c.LastParameter()) / 2)
    return np.array([p.X(), p.Y(), p.Z()])


def _loop_dist(loop, q):
    """2D distance from q to a sketch loop (arcs sampled)."""
    pts = []
    for s in loop:
        if s["t"] == "circle":
            t = np.linspace(0, 2 * np.pi, 180)
            pts += list(np.c_[s["c"][0] + s["r"] * np.cos(t), s["c"][1] + s["r"] * np.sin(t)])
        else:
            a, b = np.array(s["p"][0]), np.array(s["p"][-1])
            if s["t"] == "arc":
                pts += list(_arc_pts(*s["p"]))
            else:
                pts += list(a + np.linspace(0, 1, 40)[:, None] * (b - a))
    return float(np.min(np.linalg.norm(np.array(pts) - q, axis=1)))


def _arc_pts(a, m, b, n=60):
    a, m, b = map(np.asarray, (a, m, b))
    A = np.array([[2 * (m - a)[0], 2 * (m - a)[1]], [2 * (b - a)[0], 2 * (b - a)[1]]])
    c = np.linalg.solve(A, [m @ m - a @ a, b @ b - a @ a])
    ang = lambda p: np.arctan2(*(p - c)[::-1])
    t0, tm, t1 = ang(a), ang(m), ang(b)
    ccw = (tm - t0) % (2 * np.pi) < (t1 - t0) % (2 * np.pi)
    span = (t1 - t0) % (2 * np.pi) if ccw else -((t0 - t1) % (2 * np.pi))
    t = t0 + np.linspace(0, 1, n) * span
    r = np.linalg.norm(a - c)
    return np.c_[c[0] + r * np.cos(t), c[1] + r * np.sin(t)]


def cap_planes(tree, mod):
    f = next(x for x in tree["features"] if x["id"] == mod["on"])
    if f["length"] == "through":
        return f["axis"], []
    lo, hi = sorted((f["at"], f["at"] + float(f["length"])))
    return f["axis"], {"top": [hi], "bottom": [lo], "both": [lo, hi]}[mod.get("cap", "both")]


def modifier_edges(shape, tree, mod, tol):
    """The edges a round/chamfer names, found by geometry on the FINAL solid (never by index: indices die on the
    next edit): the rims of the flat faces lying in the cap planes of feature `on`; "outer" = their outer wire,
    "inner" = their holes. Works whatever pads made the rim (one outline, or a ring and a tail fused)."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_WIRE
    axis, caps = cap_planes(tree, mod)
    k, which = AX[axis], mod.get("loops", "outer")
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = TopoDS.Face_s(ex.Current()); ex.Next()
        srf = BRepAdaptor_Surface(face)
        if srf.GetType() != GeomAbs_Plane:
            continue
        pl = srf.Plane(); n = pl.Axis().Direction(); o = pl.Location()
        if abs([n.X(), n.Y(), n.Z()][k]) < 0.999 or not any(abs([o.X(), o.Y(), o.Z()][k] - z) < tol for z in caps):
            continue
        outer = BRepTools.OuterWire_s(face)
        wx = TopExp_Explorer(face, TopAbs_WIRE)
        while wx.More():
            w = TopoDS.Wire_s(wx.Current()); wx.Next()
            is_outer = w.IsSame(outer)
            if which == "all" or (which == "outer") == is_outer:
                for e in _edges(w):
                    if not any(e.IsSame(x) for x in out):
                        out.append(e)
    return out


def apply_modifier(shape, tree, mod, tol):
    edges = modifier_edges(shape, tree, mod, tol)
    if not edges:
        return shape, "no edges matched"
    def build(es, size):
        try:
            mk = BRepFilletAPI_MakeFillet(shape) if mod["op"] == "round" else BRepFilletAPI_MakeChamfer(shape)
            for e in es:
                mk.Add(size, e)
            mk.Build()
            if mk.IsDone() and BRepCheck_Analyzer(mk.Shape()).IsValid():
                return mk.Shape()
        except Exception:                            # noqa: BLE001 -- OCCT raises StdFail on refusal
            pass
        return None
    size = float(mod["size"])
    for k in (1.0, 0.995, 0.98, 0.95, 0.85):         # OCCT refuses a round that eats a whole face (a full round): shrink
        s = build(edges, size * k)
        if s is not None:
            return s, None if k == 1.0 else f"built at {size * k:.4g} instead of {size:.4g} (OCCT refuses the exact size)"
    # some edges refuse (tangent chains, edges shorter than the size): keep the ones that build together.
    # ponytail: greedy, O(n) builds; fine for tens of edges
    keep = []
    for e in edges:
        if build(keep + [e], size) is not None:
            keep.append(e)
    if keep:
        return build(keep, size), f"{len(edges) - len(keep)} of {len(edges)} edges refused"
    return shape, f"{mod['op']} refused on {len(edges)} edges"


_PREFIX = {}                                  # prefix hash -> (shape, notes, tapered_ok), oldest first
_PREFIX_MAX = 96


def compile_tree(tree, tol=None):
    """Tree -> (shape, notes per feature id). Features tagged with different "body" values are
    separate solids (a print-in-place assembly): each body is compiled on its own and the result
    is their compound."""
    groups = {}
    for f in tree["features"]:
        groups.setdefault(f.get("body", ""), []).append(f)
    if len(groups) <= 1:
        return _compile_body(tree, tol)
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    comp, bld, notes, n = TopoDS_Compound(), BRep_Builder(), {}, 0
    bld.MakeCompound(comp)
    for fs in groups.values():
        s, nt = _compile_body({"units": tree.get("units", "mm"), "features": fs}, tol)
        notes.update(nt)
        if s is not None:
            bld.Add(comp, s)
            n += 1
    return (comp if n else None), notes


def _compile_body(tree, tol=None):
    """One body's tree -> (solid, notes per feature id). A feature that fails is skipped and noted.
    Compiled prefixes are cached: a candidate that appends or inserts one feature rebuilds only
    from there (the analysis compiles ~40 trees that mostly share their first features). Same
    booleans on the same inputs, so the result equals a fresh compile."""
    import hashlib
    import json as _json
    feats = tree["features"]
    taper = {}                                         # pad id -> {cap: chamfer}: rim chamfers built into the pad
    for f in feats:
        if f["op"] == "chamfer" and f.get("loops", "outer") == "outer":
            on = next((g for g in feats if g["id"] == f.get("on")), None)
            pads = [g for g in feats if g["op"] == "pad"]
            if on and on["op"] == "pad" and on["length"] != "through" and len(pads) == 1:   # one pad: its own rim
                for cap in (("top", "bottom") if f.get("cap", "both") == "both" else (f["cap"],)):
                    taper.setdefault(on["id"], {})[cap] = float(f["size"])
    h = hashlib.sha1((_json.dumps(taper, sort_keys=True) + f"|{tol}").encode())
    keys = []
    for f in feats:                          # a pad's body depends on the taper map: in every key
        h.update(_json.dumps(f, sort_keys=True).encode())
        keys.append(h.hexdigest())
    shape, notes, tapered_ok, start = None, {}, set(), 0
    for i in range(len(feats) - 1, -1, -1):
        if keys[i] in _PREFIX:
            shape, notes, tapered_ok = _PREFIX[keys[i]]
            notes, tapered_ok, start = dict(notes), set(tapered_ok), i + 1
            break
    for i in range(start, len(feats)):
        shape = _step(feats[i], shape, tree, taper, tapered_ok, notes, tol)
        _PREFIX[keys[i]] = (shape, dict(notes), set(tapered_ok))
        while len(_PREFIX) > _PREFIX_MAX:
            _PREFIX.pop(next(iter(_PREFIX)))
    if shape is not None:
        u = ShapeUpgrade_UnifySameDomain(shape, True, True, True); u.Build(); shape = u.Shape()
    return shape, notes


def _step(f, shape, tree, taper, tapered_ok, notes, tol):
    """One feature applied to the shape so far (notes and tapered_ok updated in place)."""
    try:
        if f["op"] in ("pad", "pocket"):
            p = tapered(f, taper[f["id"]]) if f["id"] in taper else None
            if p is not None:
                tapered_ok.add(f["id"])
            p = p if p is not None else prism(f)
            if not BRepCheck_Analyzer(p).IsValid():    # an invalid body makes OCCT booleans explode (44 GB)
                notes[f["id"]] = "invalid sketch (self-intersecting outline): skipped"
                return shape
            if shape is None:
                return p if f["op"] == "pad" else None
            return (BRepAlgoAPI_Fuse if f["op"] == "pad" else BRepAlgoAPI_Cut)(shape, p).Shape()
        if f["op"] == "chamfer" and f.get("on") in tapered_ok and f.get("loops", "outer") == "outer":
            return shape                               # already in the pad
        if f["op"] in ("round", "chamfer") and shape is not None:
            shape, n = apply_modifier(shape, tree, f, tol or 1e-3)
            if n:
                notes[f["id"]] = n
    except Exception as e:                            # noqa: BLE001
        notes[f["id"]] = f"failed: {e}"[:200]
    return shape


def volume(shape):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g); return g.Mass()


def tessellate(shape, defl):
    # sequential: the parallel mesher's thread pool outlives the call and deadlocks a later fork
    BRepMesh_IncrementalMesh(shape, defl, False, 0.3, False)
    V, F = [], []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = TopoDS.Face_s(ex.Current()); loc = TopLoc_Location()
        t = BRep_Tool.Triangulation_s(face, loc)
        if t is not None:
            tr = loc.Transformation(); o = len(V)
            V += [(lambda p: (p.X(), p.Y(), p.Z()))(t.Node(i).Transformed(tr)) for i in range(1, t.NbNodes() + 1)]
            for i in range(1, t.NbTriangles() + 1):
                a, b, c = t.Triangle(i).Get()
                F.append((o + a - 1, o + c - 1, o + b - 1) if face.Orientation().value == 1 else (o + a - 1, o + b - 1, o + c - 1))
        ex.Next()
    # (0, 3) when the shape is empty: 1-D empties broke trimesh in deviation (mechparts/7, a residual trial)
    return np.array(V, dtype=float).reshape(-1, 3), np.array(F, dtype=int).reshape(-1, 3)


_MESH_KD = {}


def deviation(mesh, shape, tol):
    """Per mesh face: distance from its centre to the rebuilt surface. And the other way: rebuilt surface points
    farther than tol from the mesh (material or cuts the mesh does not have). Sampled, KD-tree: fast, ~spacing."""
    import trimesh
    from scipy.spatial import cKDTree
    V, F = tessellate(shape, tol / 2)
    sm = trimesh.Trimesh(V, F, process=False)
    n = int(min(400000, max(50000, sm.area / (tol / 3) ** 2)))
    # plain random sampling: the even variant spent 106 of 145 s rejecting close points (gate profile)
    sp, _ = trimesh.sample.sample_surface(sm, n) if len(F) else (np.zeros((1, 3)), None)
    d_mesh = cKDTree(sp).query(mesh.triangles_center)[0]
    nm = int(min(400000, max(50000, mesh.area / (tol / 3) ** 2)))
    key = (id(mesh), nm)
    if key not in _MESH_KD:                            # the mesh never changes during an analysis: sample it once
        mp, _ = trimesh.sample.sample_surface(mesh, nm)
        _MESH_KD.clear(); _MESH_KD[key] = cKDTree(np.r_[mp, mesh.vertices])
    d_solid = _MESH_KD[key].query(sp)[0]
    w = mesh.area_faces
    return {"face_dist": d_mesh, "solid_pts": sp, "solid_dist": d_solid, "solid_mesh": sm,
            "explained": float(w[d_mesh < tol].sum() / w.sum()), "extra": float((d_solid > tol).mean()),
            "tol": tol}


def feature_faces(mesh, tree, shape, tol):
    """Which mesh faces each feature makes (for highlighting): faces on the surface of its pad/pocket body, the
    later feature winning; a modifier gets the faces near its edges."""
    from scipy.spatial import cKDTree
    import trimesh
    c = mesh.triangles_center
    owner = np.full(len(c), -1)
    for i, f in enumerate(tree["features"]):
        try:
            if f["op"] in ("pad", "pocket"):
                if f["length"] == "through":
                    g = dict(f); lo, hi = mesh.bounds[:, AX[f["axis"]]]
                    g.update(at=float(lo - tol), length=float(hi - lo + 2 * tol)); body = prism(g)
                else:
                    body = prism(f)
                V, F = tessellate(body, tol / 2)
                sp, _ = trimesh.sample.sample_surface(trimesh.Trimesh(V, F, process=False), 60000)
                owner[cKDTree(sp).query(c)[0] < tol] = i
            elif f["op"] in ("round", "chamfer"):
                es = modifier_edges(shape, tree, f, tol) if shape is not None else []
                pts = np.array([_mid(e) for e in es]) if es else None
                if pts is not None:
                    owner[cKDTree(pts).query(c)[0] < 3 * float(f["size"]) + tol] = i
        except Exception:                              # noqa: BLE001 -- highlighting is best effort
            pass
    return owner


def section_region(mesh, axis, h):
    """A trimesh's section across `axis` at h, as a shapely region in (u, v) (even-odd over its loops)."""
    from shapely.geometry import Polygon
    k = AX[axis]; nrm = np.zeros(3); nrm[k] = 1; o = np.zeros(3); o[k] = h
    sec = mesh.section(plane_origin=o, plane_normal=nrm)
    if sec is None:
        return Polygon()
    mu, mv = UV[axis]; acc = Polygon()
    for P in sec.discrete:
        P = np.asarray(P)
        if len(P) >= 4:
            acc = acc.symmetric_difference(Polygon(np.c_[P[:, mu], P[:, mv]]).buffer(0))
    return acc.buffer(0)


def solid_region(shape, axis, h, defl=0.02):
    return _solid_region(shape, axis, h, defl)[0]


def _solid_region(shape, axis, h, defl=0.02):
    """The exact section of an OCCT solid across `axis` at h, as a shapely region in (u, v): the plane's section
    edges, polygonised, each cell kept if the solid classifier puts it inside. No tessellation involved: a
    tessellated model leaks at face seams (3413 open edges on the gate) and its sections read nonsense."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.gp import gp_Pln
    from OCP.TopAbs import TopAbs_IN
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize, unary_union
    k = AX[axis]; mu, mv = UV[axis]
    o = [0.0, 0.0, 0.0]; o[k] = h; nv = [0.0, 0.0, 0.0]; nv[k] = 1.0
    sec = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(*o), gp_Dir(*nv)), False)
    sec.Approximation(True); sec.Build()
    if not sec.IsDone():
        return Polygon(), False
    lines = []
    for e in _edges(sec.Shape()):
        c = BRepAdaptor_Curve(e); d = GCPnts_QuasiUniformDeflection(c, defl)
        if not d.IsDone() or d.NbPoints() < 2:
            continue
        P = [d.Value(i) for i in range(1, d.NbPoints() + 1)]
        # round: two edges meeting at a vertex differ in the last bits (-47.283000000000015 vs -47.283), and
        # polygonize needs the loop to close exactly
        lines.append(LineString([(round([p.X(), p.Y(), p.Z()][mu], 6), round([p.X(), p.Y(), p.Z()][mv], 6)) for p in P]))
    if not lines:
        return Polygon(), True
    # approximated section curves end up to ~0.13 mm apart (mechparts/37: a 2425 mm2 slice read 446): snap every
    # endpoint to the centroid of the endpoints within 0.2 % of the part's size so the loops close
    from scipy.spatial import cKDTree
    E = np.array([c for ln in lines for c in (ln.coords[0], ln.coords[-1])])
    snap = 2e-3 * float(np.ptp(E, axis=0).max() or 1.0)
    groups = cKDTree(E).query_ball_point(E, snap)
    target = np.array([E[g].mean(axis=0) for g in groups])
    fixed = []
    for j, ln in enumerate(lines):
        c = np.array(ln.coords)
        c[0], c[-1] = target[2 * j], target[2 * j + 1]
        fixed.append(LineString(np.round(c, 6)))
    lines = fixed
    deg = {}
    for ln in lines:                                   # every loop end must meet another edge end
        for c in (ln.coords[0], ln.coords[-1]):
            deg[c] = deg.get(c, 0) + 1
    closed = all(v % 2 == 0 for v in deg.values())
    keep = []
    for cell in polygonize(unary_union(lines)):
        q = cell.representative_point(); p3 = [0.0, 0.0, 0.0]; p3[mu], p3[mv], p3[k] = q.x, q.y, h
        if BRepClass3d_SolidClassifier(shape, gp_Pnt(*p3), 1e-7).State() == TopAbs_IN:
            keep.append(cell)
    return (unary_union(keep).buffer(0) if keep else Polygon()), closed


def occupancy(mesh, bounds, n=40, region=None):
    """Inside/outside on a grid (n slices along the longest axis, same spacing across): volume tests that survive
    sliver triangles (ray tests ran out of memory on the gate mesh)."""
    import shapely
    lo, hi = bounds; k = int(np.argmax(hi - lo)); axis = "XYZ"[k]; mu, mv = UV[axis]
    g = (hi[k] - lo[k]) / n
    us = np.arange(lo[mu] + g / 2, hi[mu], g); vs = np.arange(lo[mv] + g / 2, hi[mv], g)
    U, W = np.meshgrid(us, vs, indexing="ij")
    region = region or (lambda a, h: section_region(mesh, a, h))
    return np.stack([shapely.contains_xy(region(axis, lo[k] + g * (i + 0.5)), U, W) for i in range(n)])


def _exact_area(shape, axis, h, eps):
    """The solid's cross-section area at h, exactly: the volume of its common with a thin slab, over the slab."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    k = AX[axis]
    lo = [-BIG, -BIG, -BIG]; lo[k] = h - eps / 2
    size = [2 * BIG, 2 * BIG, 2 * BIG]; size[k] = eps
    slab = BRepPrimAPI_MakeBox(gp_Pnt(*lo), *size).Shape()
    return volume(BRepAlgoAPI_Common(shape, slab).Shape()) / eps


def checked_region(shape, axis, h, eps):
    """solid_region, or None when its area disagrees with the exact section area by more than 3 %: section edges
    sometimes do not close into loops (mechparts/23: slices read 0 of 1717 mm2 even after snapping)."""
    r, closed = _solid_region(shape, axis, h)
    if closed:                                         # loops closed: trusted without the (slower) exact check
        return r
    ex = _exact_area(shape, axis, h, eps)
    return r if abs(r.area - ex) <= 0.03 * max(ex, 1e-9) + 1e-6 else None


def volume_iou(mesh, shape, tol, occ_mesh=None):
    """Volume overlap of the solid and the mesh on the occupancy grid. A slice whose solid section cannot be
    trusted (checked_region -> None) is left out on both sides instead of counted as empty."""
    import shapely
    a = occ_mesh if occ_mesh is not None else occupancy(mesh, mesh.bounds)
    lo, hi = mesh.bounds; k = int(np.argmax(hi - lo)); axis = "XYZ"[k]; mu, mv = UV[axis]
    n = a.shape[0]; g = (hi[k] - lo[k]) / n
    us = np.arange(lo[mu] + g / 2, hi[mu], g); vs = np.arange(lo[mv] + g / 2, hi[mv], g)
    U, W = np.meshgrid(us, vs, indexing="ij")
    inter = union = 0
    for i in range(n):                                 # same grid as the mesh's occupancy
        r = checked_region(shape, axis, lo[k] + g * (i + 0.5), g / 50)
        if r is None:
            continue
        b = shapely.contains_xy(r, U, W)
        inter += int(np.logical_and(a[i], b).sum()); union += int(np.logical_or(a[i], b).sum())
    return float(inter / max(union, 1))


def write_step(shape, path):
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    w = STEPControl_Writer(); w.Transfer(shape, STEPControl_AsIs); w.Write(str(path))


if __name__ == "__main__":
    import trimesh
    t = json.load(open(sys.argv[1])); m = trimesh.load(sys.argv[2], force="mesh")
    tol = 3e-3 * float(np.linalg.norm(m.extents))
    s, notes = compile_tree(t, tol)
    d = deviation(m, s, tol)
    print(json.dumps({"valid": BRepCheck_Analyzer(s).IsValid(), "volume": volume(s), "mesh_volume": float(m.volume),
                      "explained": d["explained"], "extra": d["extra"], "notes": notes}))
