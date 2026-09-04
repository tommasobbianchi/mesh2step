"""Stage P — buildPrismSolid + tryStageP: one prism per slab, fuse, union, gate.

Port of ``refs/stl2step/src/refit_prism_build.cpp`` (1188 lines). This is a
TRANSCRIPTION, not a reimplementation: every helper below carries the
``refit_prism_build.cpp`` line it was copied from, and where the reference looks
odd it is still the specification.

The reference emits ``DIAG_PRISMBUILD`` lines to stderr gated on
``STL2STEP_PRISM_DIAG``; this port captures the same values into a ``PrismDiag``
record returned alongside the shape (the same decision ``prism.py`` /
``profile.py`` made for their diagnostic lines). The thread-local unify state
(``tUnifyV0`` … ``tUnifyG4``) becomes fields of ``PrismBuild``, which is threaded
through the two public entry points.

2D points are plain ``numpy`` shape-(2,) float64 (in place of ``gp_Pnt2d``), 3D
vectors are shape-(3,) float64; dot products use the scalar ``a*b + c*d + e*f``
path and angles use ``math.atan2``/``math.hypot`` to match the OCCT / libm
bit-exact behaviour of the reference (reusing ``profile.py``'s helpers).
"""
from __future__ import annotations

import math
from copy import copy, deepcopy
from dataclasses import dataclass, field

import numpy as np
from OCP.BOPAlgo import BOPAlgo_GlueEnum
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLib import BRepLib
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepTools import BRepTools_ReShape
from OCP.ElCLib import ElCLib
from OCP.GC import GC_MakeArcOfCircle
from OCP.Geom import Geom_Circle, Geom_Plane
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.gp import (
    gp_Ax2,
    gp_Circ,
    gp_Dir,
    gp_Pln,
    gp_Pnt,
    gp_Vec,
)
from OCP.GProp import GProp_GProps
from OCP.Precision import Precision
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.Standard import Standard_Failure
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_REVERSED,
    TopAbs_SHELL,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import (
    TopoDS,
    TopoDS_Compound,
    TopoDS_Face,
    TopoDS_Shape,
    TopoDS_Vertex,
)
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

from .prism import PrismLevels, PrismTols, detect_prismatic
from .profile import (
    K_TWO_PI,
    Profile,
    ProfLoop,
    ProfSeg,
    _cross3,
    _dir_xyz,
    _dist2,
    _dot3,
    _norm3,
    _p2,
    _pnt_xyz,
    fit_profile,
    slice_profiles,
)
from .segment import RegionSet, SurfType

_CONFUSION = Precision.Confusion_s()


# --- diagnostic / state records (ports of the thread_local globals) ---------------


@dataclass
class PrismDiag:
    """Every ``DIAG_PRISMBUILD`` field, captured instead of printed (refit_prism_build.cpp:52)."""

    slabs: list = field(default_factory=list)  # (faces:int, vol:float, valid:int)
    fuses: list = field(default_factory=list)  # (k:int, faces:int)
    usd_try: tuple | None = None  # (P0,P1,C0,C1,V0,V1)
    plane_adj: tuple | None = None  # (nAdj, nExact, nPlanes)
    unify: tuple | None = None  # (faces, G1, G2, G4, V_before, V_after, P0, P1, C0, C1)
    # (D_signed, D_abs, V_ref, budget, envelope, |s-Vref|, |s-mesh|, cond1, cond2)
    vol_gate: tuple | None = None
    g_line: tuple | None = None  # (G1, G2, G3_planes, G4, C0, C1, V_before, V_after)
    census: tuple | None = None  # (comp, slabs, faces, planes, cyls, vol, wt, valid, reverted)


@dataclass
class PrismBuild:
    """Port of the ``thread_local`` unify state (refit_prism_build.cpp:79-81)."""

    diag: PrismDiag = field(default_factory=PrismDiag)
    unify_v0: float = 0.0
    unify_v1: float = 0.0
    unify_p0: int = 0
    unify_c0: int = 0
    unify_p1: int = 0
    unify_c1: int = 0
    unify_g2: int = 1
    unify_g4: int = 1


@dataclass
class PrismResult:
    """Port of ``tryStageP``'s return: ok + the extracted faces + diagnostics."""

    ok: bool = False
    faces: list = field(default_factory=list)
    pb: PrismBuild = field(default_factory=PrismBuild)


# --- frame (makeFrame / to3, refit_prism_build.cpp:122-155) -----------------------


@dataclass
class _Frame:
    origin: np.ndarray = field(default_factory=lambda: np.zeros(3))
    axis: np.ndarray = field(default_factory=lambda: np.zeros(3))
    u: np.ndarray = field(default_factory=lambda: np.zeros(3))
    v: np.ndarray = field(default_factory=lambda: np.zeros(3))
    y_ref: float = 0.0


def _make_frame(lv: PrismLevels, origin3: np.ndarray) -> _Frame | None:  # :130
    fr = _Frame()
    fr.axis = np.asarray(lv.axis, dtype=float).copy()
    am = _norm3(fr.axis)
    if not (am > 0.0) or not math.isfinite(am):
        return None
    fr.axis = fr.axis / am
    hint = np.array([1.0, 0.0, 0.0])
    if abs(_dot3(fr.axis, hint)) > 0.9:
        hint = np.array([0.0, 1.0, 0.0])
    fr.u = _cross3(fr.axis, hint)
    um = _norm3(fr.u)
    if um < 1e-18:
        return None
    fr.u = fr.u / um
    fr.v = _cross3(fr.axis, fr.u)
    vm = _norm3(fr.v)
    if vm < 1e-18:
        return None
    fr.v = fr.v / vm
    fr.origin = np.asarray(origin3, dtype=float).copy()
    fr.y_ref = _dot3(fr.axis, fr.origin)
    return fr


def _to3(fr: _Frame, p: np.ndarray, y_level: float) -> gp_Pnt:  # :152
    q = fr.origin + fr.u * p[0] + fr.v * p[1] + fr.axis * (y_level - fr.y_ref)
    return gp_Pnt(float(q[0]), float(q[1]), float(q[2]))


def _loop_signed_area(lp: ProfLoop) -> float:  # :161
    a = 0.0
    for s in lp.segs:
        a += s.a[0] * s.b[1] - s.b[0] * s.a[1]
    return 0.5 * a


def _is_full_circle(s: ProfSeg) -> bool:  # :168
    if not s.is_arc or not (s.r > 0.0):
        return False
    if s.phi >= K_TWO_PI * 0.5 and _dist2(s.a, s.b) <= max(1e-9 * s.r, _CONFUSION):
        return True
    return s.phi >= K_TWO_PI - 1e-9


# --- edge construction ------------------------------------------------------------

def _make_line_edge(a: gp_Pnt, b: gp_Pnt):  # :175
    if a.Distance(b) <= _CONFUSION:
        return None
    try:
        me = BRepBuilderAPI_MakeEdge(a, b)
        if not me.IsDone():
            return None
        e = me.Edge()
        return e if not e.IsNull() else None
    except Standard_Failure:
        return None


def _on_circ2(s: ProfSeg, p: np.ndarray) -> np.ndarray:  # :187
    if not s.is_arc or not (s.r > 0.0):
        return p
    ang = math.atan2(p[1] - s.center[1], p[0] - s.center[0])
    return _p2(s.center[0] + s.r * math.cos(ang), s.center[1] + s.r * math.sin(ang))


def _make_arc_edge(fr: _Frame, s: ProfSeg, a2: np.ndarray, b2: np.ndarray, y_level: float):  # :193
    if not (s.r > 0.0):
        return None
    try:
        c = _to3(fr, s.center, y_level)
        ax = gp_Ax2(
            c,
            gp_Dir(float(fr.axis[0]), float(fr.axis[1]), float(fr.axis[2])),
            gp_Dir(float(fr.u[0]), float(fr.u[1]), float(fr.u[2])),
        )
        circ = gp_Circ(ax, s.r)
        gc = Geom_Circle(circ)
        if _is_full_circle(s) or _dist2(a2, b2) <= _CONFUSION:
            me = BRepBuilderAPI_MakeEdge(gc)
            if not me.IsDone():
                return None
            e = me.Edge()
            return e if not e.IsNull() else None
        u0 = math.atan2(a2[1] - s.center[1], a2[0] - s.center[0])
        sweep = s.phi
        if not (sweep > 0.0):
            u1guess = math.atan2(b2[1] - s.center[1], b2[0] - s.center[0])
            sweep = u1guess - u0
            if s.ccw:
                while sweep <= 0.0:
                    sweep += K_TWO_PI
            else:
                while sweep >= 0.0:
                    sweep -= K_TWO_PI
                sweep = -sweep
        if not (sweep > 0.0):
            return None
        u1 = (u0 + sweep) if s.ccw else (u0 - sweep)
        pA = ElCLib.Value_s(u0, circ)
        pM = ElCLib.Value_s(0.5 * (u0 + u1), circ)
        pB = ElCLib.Value_s(u1, circ)
        mk = GC_MakeArcOfCircle(pA, pM, pB)
        if not mk.IsDone():
            me = BRepBuilderAPI_MakeEdge(gc, min(u0, u1), max(u0, u1))
            if not me.IsDone():
                return None
            e = me.Edge()
            return e if not e.IsNull() else None
        me = BRepBuilderAPI_MakeEdge(mk.Value())
        if not me.IsDone():
            return None
        e = me.Edge()
        return e if not e.IsNull() else None
    except Standard_Failure:
        return None


def _merge_same_circle_arcs(lp: ProfLoop) -> None:  # :240
    if len(lp.segs) < 2:
        return
    out = []
    acc = copy(lp.segs[0])

    def same_circ(a: ProfSeg, b: ProfSeg) -> bool:
        if not a.is_arc or not b.is_arc or not (a.r > 0.0) or not (b.r > 0.0):
            return False
        if abs(a.r - b.r) > max(1e-6 * a.r, _CONFUSION):
            return False
        return _dist2(a.center, b.center) <= max(1e-6 * a.r, _CONFUSION)

    for i in range(1, len(lp.segs)):
        s = lp.segs[i]
        if same_circ(acc, s) and acc.ccw == s.ccw:
            acc.b = s.b
            acc.phi += s.phi
            continue
        out.append(acc)
        acc = copy(s)
    if out and same_circ(acc, out[0]) and acc.ccw == out[0].ccw:
        out[0].a = acc.a
        out[0].phi += acc.phi
    else:
        out.append(acc)
    lp.segs = out


def _snap_line_ends_to_arcs(lp: ProfLoop) -> None:  # :270
    n = len(lp.segs)
    if n < 2:
        return
    for i in range(n):
        s = lp.segs[i]
        if s.is_arc and s.r > 0.0:
            s.a = _on_circ2(s, s.a)
            s.b = _on_circ2(s, s.b)
    for i in range(n):
        s = lp.segs[i]
        if s.is_arc:
            continue
        nxt = lp.segs[(i + 1) % n]
        prev = lp.segs[(i + n - 1) % n]
        if prev.is_arc and prev.r > 0.0:
            s.a = _on_circ2(prev, s.a)
            prev.b = s.a
        if nxt.is_arc and nxt.r > 0.0:
            s.b = _on_circ2(nxt, s.b)
            nxt.a = s.b


def _build_loop_wire(fr: _Frame, lp_in: ProfLoop, y_level: float, want_ccw: bool):  # :298
    lp = deepcopy(lp_in)
    _merge_same_circle_arcs(lp)
    _snap_line_ends_to_arcs(lp)
    if not lp.segs:
        return None
    try:
        if len(lp.segs) == 1 and _is_full_circle(lp.segs[0]):
            circ = copy(lp.segs[0])
            circ.a = _p2(circ.center[0] + circ.r, circ.center[1])
            circ.b = circ.a
            circ.phi = K_TWO_PI
            e = _make_arc_edge(fr, circ, circ.a, circ.b, y_level)
            if e is None:
                return None
            mw = BRepBuilderAPI_MakeWire(e)
            if not mw.IsDone():
                return None
            w = mw.Wire()
            if not want_ccw:
                w.Reverse()
            w.Closed(True)
            return w
        if len(lp.segs) == 1 and lp.segs[0].is_arc and not _is_full_circle(lp.segs[0]):
            return None
        n = len(lp.segs)
        mw = BRepBuilderAPI_MakeWire()
        last_end = None
        have_last = False
        first_start = None
        for i in range(n):
            s = lp.segs[i]
            a2 = s.a
            b2 = s.b
            if s.is_arc and s.r > 0.0:
                a2 = _on_circ2(s, s.a)
                b2 = _on_circ2(s, s.b)
            e = None
            ok = False
            if s.is_arc and s.r > 0.0 and not s.declined_ambiguous:
                e = _make_arc_edge(fr, s, a2, b2, y_level)
                ok = e is not None
            if not ok:
                pA = _to3(fr, a2, y_level)
                pB = _to3(fr, b2, y_level)
                if have_last:
                    pA = last_end
                e = _make_line_edge(pA, pB)
                ok = e is not None
            if not ok:
                return None
            va = TopoDS_Vertex()
            vb = TopoDS_Vertex()
            TopExp.Vertices_s(e, va, vb, True)
            e0 = BRep_Tool.Pnt_s(va)
            e1 = BRep_Tool.Pnt_s(vb)
            if have_last and last_end.Distance(e0) > _CONFUSION:
                bridge = _make_line_edge(last_end, e0)
                if bridge is None:
                    return None
                mw.Add(bridge)
                if not mw.IsDone():
                    return None
            mw.Add(e)
            if not mw.IsDone():
                return None
            if not have_last:
                first_start = e0
            last_end = e1
            have_last = True
        if have_last and last_end.Distance(first_start) > _CONFUSION:
            bridge = _make_line_edge(last_end, first_start)
            if bridge is None:
                return None
            mw.Add(bridge)
            if not mw.IsDone():
                return None
        if not mw.IsDone():
            return None
        w = mw.Wire()
        sa = _loop_signed_area(lp)
        ccw = sa > 0.0
        if ccw != want_ccw:
            w.Reverse()
        w.Closed(True)
        return w if not w.IsNull() else None
    except Standard_Failure:
        return None


def _build_slab_face(fr: _Frame, p: Profile, y_level: float) -> TopoDS_Face | None:  # :391
    if not p.loops or not p.loops[0].outer:
        return None
    try:
        o = _to3(fr, _p2(0.0, 0.0), y_level)
        pln = gp_Pln(o, gp_Dir(float(fr.axis[0]), float(fr.axis[1]), float(fr.axis[2])))
        outer = _build_loop_wire(fr, p.loops[0], y_level, True)
        if outer is None:
            return None
        surf = Geom_Plane(pln)
        B = BRep_Builder()
        f = TopoDS_Face()
        B.MakeFace(f, surf, _CONFUSION)
        B.Add(f, outer)
        for i in range(1, len(p.loops)):
            lp = p.loops[i]
            if lp.outer:
                return None
            on_outer = False
            for hs in lp.segs:
                if not hs.is_arc or not (hs.r > 0.0):
                    continue
                for os_ in p.loops[0].segs:
                    if (
                        os_.is_arc
                        and os_.r > 0.0
                        and abs(os_.r - hs.r) <= max(1e-6 * hs.r, _CONFUSION)
                        and _dist2(os_.center, hs.center) <= max(1e-6 * hs.r, _CONFUSION)
                    ):
                        on_outer = True
                        break
                if on_outer:
                    break
            if on_outer:
                continue
            inner = _build_loop_wire(fr, lp, y_level, False)
            if inner is None:
                continue
            B.Add(f, inner)
        try:
            BRepLib.BuildCurves3d_s(f)
        except Standard_Failure:
            pass
        return f if not f.IsNull() else None
    except Standard_Failure:
        return None


def _build_one_prism(fr: _Frame, p: Profile, lv: PrismLevels):  # :450
    if p.slab < 0 or p.slab + 1 >= len(lv.y):
        return None
    y0 = lv.y[p.slab]
    y1 = lv.y[p.slab + 1]
    h = y1 - y0
    if not (h > 0.0) or not math.isfinite(h):
        return None
    face = _build_slab_face(fr, p, y0)
    if face is None:
        return None
    try:
        vec = gp_Vec(gp_Dir(float(fr.axis[0]), float(fr.axis[1]), float(fr.axis[2]))) * h
        mk = BRepPrimAPI_MakePrism(face, vec, False)
        if not mk.IsDone():
            return None
        solid = mk.Shape()
        return solid if not solid.IsNull() else None
    except Standard_Failure:
        return None


# --- shape predicates / measures --------------------------------------------------

def _shape_vol(s) -> float:  # :470
    if s is None or s.IsNull():
        return 0.0
    try:
        gp = GProp_GProps()
        BRepGProp.VolumeProperties_s(s, gp)
        return gp.Mass()
    except Standard_Failure:
        return 0.0


def _count_surf(s) -> tuple[int, int]:  # :481
    n_p = 0
    n_c = 0
    if s is None or s.IsNull():
        return 0, 0
    fx = TopExp_Explorer(s, TopAbs_FACE)
    while fx.More():
        try:
            sa = BRepAdaptor_Surface(TopoDS.Face_s(fx.Current()), False)
            if sa.GetType() == GeomAbs_Plane:
                n_p += 1
            elif sa.GetType() == GeomAbs_Cylinder:
                n_c += 1
        except Standard_Failure:
            pass
        fx.Next()
    return n_p, n_c


def _shape_closed(s) -> bool:  # :495
    if s is None or s.IsNull():
        return False
    try:
        if BRep_Tool.IsClosed_s(s):
            return True
        sx = TopExp_Explorer(s, TopAbs_SHELL)
        while sx.More():
            if BRep_Tool.IsClosed_s(TopoDS.Shell_s(sx.Current())):
                return True
            sx.Next()
    except Standard_Failure:
        pass
    return False


def _shape_valid(s) -> bool:  # :507
    if s is None or s.IsNull():
        return False
    try:
        an = BRepCheck_Analyzer(s, True)
        if an.IsValid():
            return True
        sx = TopExp_Explorer(s, TopAbs_SHELL)
        while sx.More():
            a2 = BRepCheck_Analyzer(sx.Current(), True)
            if a2.IsValid():
                return True
            sx.Next()
    except Standard_Failure:
        pass
    return False


def _mesh_vol(mv) -> float:  # :521
    v = 0.0
    if mv.pts is None or mv.tris is None or mv.comp_tris is None:
        return 0.0
    for k in range(mv.n_tri):
        gt = int(mv.comp_tris[k])
        if gt < 0:
            continue
        a = mv.pts[int(mv.tris[gt][0])]
        b = mv.pts[int(mv.tris[gt][1])]
        c = mv.pts[int(mv.tris[gt][2])]
        v += _dot3(a, _cross3(b, c)) / 6.0
    return v


def _count_faces(s) -> int:
    n = 0
    fx = TopExp_Explorer(s, TopAbs_FACE)
    while fx.More():
        n += 1
        fx.Next()
    return n


# --- D9 defect arithmetic (refit_prism_build.cpp:535-602) ------------------------

def _n_sides_for_r(r_value: float, rs: RegionSet) -> int:  # :535
    best = 0
    best_d = 1e300
    for r in rs.regions:
        if r.type != SurfType.CYLINDER or not (r.radius > 0.0) or r.n_sides < 3:
            continue
        assoc = max(_CONFUSION, 4.0 * r.max_vertex_dev, 4.0 * r.chord_sagitta)
        d = abs(r.radius - r_value)
        if d <= assoc and d < best_d:
            best_d = d
            best = r.n_sides
    return best


def _seg_sweep(s: ProfSeg) -> float:  # :552
    if not s.is_arc or not (s.r > 0.0):
        return 0.0
    if s.phi > 0.0:
        return s.phi
    u0 = math.atan2(s.a[1] - s.center[1], s.a[0] - s.center[0])
    u1 = math.atan2(s.b[1] - s.center[1], s.b[0] - s.center[0])
    sw = u1 - u0
    if s.ccw:
        while sw <= 0.0:
            sw += K_TWO_PI
    else:
        while sw >= 0.0:
            sw -= K_TWO_PI
        sw = -sw
    return sw


def _loop_arc_defect(lp: ProfLoop, h: float, rs: RegionSet) -> float:  # :568
    if not (h > 0.0) or not math.isfinite(h):
        return 0.0
    d = 0.0
    for s in lp.segs:
        if not s.is_arc or not (s.r > 0.0) or s.declined_ambiguous:
            continue
        theta = _seg_sweep(s)
        if not (theta > 0.0) or not math.isfinite(theta):
            continue
        n = _n_sides_for_r(s.r, rs)
        if n >= 3:
            g = K_TWO_PI / float(n)
            n_strips = max(1.0, theta / g)
            d += n_strips * 0.5 * s.r * s.r * (g - math.sin(g)) * h
        elif theta < K_TWO_PI - 1e-9:
            d += 0.5 * s.r * s.r * (theta - math.sin(theta)) * h
    return d


def _profile_arc_defects(profs, lv: PrismLevels, rs: RegionSet) -> tuple[float, float]:  # :587
    d_signed = 0.0
    d_abs = 0.0
    for p in profs:
        if p.slab < 0 or p.slab + 1 >= len(lv.y):
            continue
        h = lv.y[p.slab + 1] - lv.y[p.slab]
        for lp in p.loops:
            defect = _loop_arc_defect(lp, h, rs)
            sig = -1.0 if lp.outer else 1.0
            d_signed += sig * defect
            d_abs += abs(defect)
    return d_signed, d_abs


# --- plane merge / unify (refit_prism_build.cpp:605-804) --------------------------

def _exact_coplanar_same_ori(n1, d1: float, n2, d2: float) -> bool:  # :605
    dn = _dot3(n1, n2)
    if not (dn > 0.0):
        return False
    ang = 0.0 if dn >= 1.0 else math.acos(min(1.0, dn))
    if ang > _CONFUSION:
        return False
    return abs(d1 - d2) <= _CONFUSION


def _plane_params(f):
    try:
        sa = BRepAdaptor_Surface(f, False)
        if sa.GetType() != GeomAbs_Plane:
            return None
        pl = sa.Plane()
        n = _dir_xyz(pl.Axis().Direction())
        if f.Orientation() == TopAbs_REVERSED:
            n = -n
        d = _dot3(n, _pnt_xyz(pl.Location()))
    except Standard_Failure:
        return None
    return n, d


def _merge_exact_coplanar_planes(
    s: TopoDS_Shape, pb: PrismBuild
) -> tuple[TopoDS_Shape, int]:  # :629
    if s is None or s.IsNull():
        return s, 0
    planes = []
    fx = TopExp_Explorer(s, TopAbs_FACE)
    while fx.More():
        f = TopoDS.Face_s(fx.Current())
        pp = _plane_params(f)
        if pp is not None:
            planes.append((f, pp[0], pp[1]))
        fx.Next()
    n = len(planes)
    if n < 2:
        return s, 0
    parent = list(range(n))

    def find(i: int) -> int:
        r = i
        while parent[r] != r:
            r = parent[r]
        k = i
        while k != r:
            nxt = parent[k]
            parent[k] = r
            k = nxt
        return r

    def unite(a: int, b: int) -> None:
        a = find(a)
        b = find(b)
        if a != b:
            parent[b] = a

    ef = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(s, TopAbs_EDGE, TopAbs_FACE, ef)
    n_adj = 0
    n_exact = 0
    for ei in range(1, ef.Extent() + 1):
        lf = ef.FindFromIndex(ei)
        if lf.Extent() != 2:
            continue
        f1 = TopoDS.Face_s(lf.First())
        f2 = TopoDS.Face_s(lf.Last())
        i1 = -1
        i2 = -1
        for i in range(n):
            if planes[i][0].IsSame(f1):
                i1 = i
            if planes[i][0].IsSame(f2):
                i2 = i
        if i1 < 0 or i2 < 0 or i1 == i2:
            continue
        pp1 = _plane_params(f1)
        pp2 = _plane_params(f2)
        if pp1 is None or pp2 is None:
            continue
        n_adj += 1
        if _exact_coplanar_same_ori(pp1[0], pp1[1], pp2[0], pp2[1]):
            n_exact += 1
            unite(i1, i2)
    pb.diag.plane_adj = (n_adj, n_exact, n)
    if n_exact < 1:
        return s, 0

    groups = [[] for _ in range(n)]
    for i in range(n):
        groups[find(i)].append(i)

    v0 = _shape_vol(s)
    _n_p0, n_c0 = _count_surf(s)
    merged = 0
    try:
        reshape = BRepTools_ReShape()
        for g in range(n):
            mem = groups[g]
            if len(mem) < 2:
                continue
            c = TopoDS_Compound()
            B = BRep_Builder()
            B.MakeCompound(c)
            for i in mem:
                B.Add(c, planes[i][0])
            usd = ShapeUpgrade_UnifySameDomain(c, True, True, False)
            usd.SetLinearTolerance(_CONFUSION)
            usd.SetAngularTolerance(_CONFUSION)
            usd.SetSafeInputMode(True)
            usd.Build()
            u = usd.Shape()
            if u.IsNull():
                continue
            n_f = 0
            kept = None
            fx2 = TopExp_Explorer(u, TopAbs_FACE)
            while fx2.More():
                n_f += 1
                kept = TopoDS.Face_s(fx2.Current())
                fx2.Next()
            if n_f != 1 or kept is None or kept.IsNull():
                continue
            reshape.Replace(planes[mem[0]][0], kept)
            for k in range(1, len(mem)):
                reshape.Remove(planes[mem[k]][0])
            merged += len(mem) - 1
        if merged < 1:
            return s, 0
        out = reshape.Apply(s)
        if out.IsNull():
            return s, 0
        v1 = _shape_vol(out)
        _n_p, n_c = _count_surf(out)
        v_floor = 1e-6 * abs(v0)
        if abs(v1 - v0) > v_floor:
            pb.unify_g2 = 0
            return s, 0
        if n_c != n_c0:
            pb.unify_g4 = 0
            return s, 0
        return out, merged  # noqa: TRY300 - port of the reference's try/catch guard
    except Standard_Failure:
        return s, 0


def _unify_same_once(s: TopoDS_Shape, pb: PrismBuild) -> TopoDS_Shape:  # :750
    pb.unify_v0 = 0.0
    pb.unify_v1 = 0.0
    pb.unify_p0 = 0
    pb.unify_c0 = 0
    pb.unify_p1 = 0
    pb.unify_c1 = 0
    pb.unify_g2 = 1
    pb.unify_g4 = 1
    if s is None or s.IsNull():
        return s
    pb.unify_v0 = _shape_vol(s)
    pb.unify_p0, pb.unify_c0 = _count_surf(s)
    pb.unify_v1 = pb.unify_v0
    pb.unify_p1 = pb.unify_p0
    pb.unify_c1 = pb.unify_c0
    try:
        usd = ShapeUpgrade_UnifySameDomain(s, True, True, False)
        usd.SetLinearTolerance(_CONFUSION)
        usd.SetAngularTolerance(_CONFUSION)
        usd.SetSafeInputMode(True)
        usd.Build()
        u = usd.Shape()
        if not u.IsNull():
            v1 = _shape_vol(u)
            n_p, n_c = _count_surf(u)
            pb.diag.usd_try = (pb.unify_p0, n_p, pb.unify_c0, n_c, pb.unify_v0, v1)
            v_floor = 1e-6 * abs(pb.unify_v0)
            if abs(v1 - pb.unify_v0) > v_floor:
                pb.unify_g2 = 0
            elif n_c != pb.unify_c0:
                pb.unify_g4 = 0
            else:
                s = u
                pb.unify_v1 = v1
                pb.unify_p1 = n_p
                pb.unify_c1 = n_c
    except Standard_Failure:
        pass
    s, _merged = _merge_exact_coplanar_planes(s, pb)
    if _merged > 0:
        pb.unify_v1 = _shape_vol(s)
        pb.unify_p1, pb.unify_c1 = _count_surf(s)
    return s


# --- buildPrismSolid (refit_prism_build.cpp:835-979) -----------------------------

def build_prism_solid(
    profs, lv: PrismLevels, origin3: np.ndarray, pb: PrismBuild | None = None
) -> TopoDS_Shape | None:
    """Port of ``buildPrismSolid`` (refit_prism_build.cpp:835). Returns the fused
    solid or ``None`` on failure; never throws.

    ``origin3`` is the sketch origin bound by ``prismBindSketchOrigin``
    (refit_prism_build.cpp:808); the reference stores it thread-locally, this port
    passes it explicitly (computed by ``try_stage_p``)."""
    if pb is None:
        pb = PrismBuild()
    try:
        if not lv.ok or len(lv.y) < 2:
            return None
        n_slab = len(lv.y) - 1
        if n_slab < 1:
            return None

        by_slab: list = [None] * n_slab
        for p in profs:
            if p.slab < 0 or p.slab >= n_slab:
                return None
            if by_slab[p.slab] is not None:
                return None
            if not p.loops or not p.loops[0].outer:
                return None
            by_slab[p.slab] = p
        for p in by_slab:
            if p is None:
                return None

        fr = _make_frame(lv, origin3)
        if fr is None:
            return None

        slabs = [None] * n_slab
        for k in range(n_slab):
            try:
                slabs[k] = _build_one_prism(fr, by_slab[k], lv)
                if slabs[k] is None:
                    return None
                nf = _count_faces(slabs[k])
                sv = _shape_vol(slabs[k])
                okv = 1 if _shape_valid(slabs[k]) else 0
                pb.diag.slabs.append((nf, sv, okv))
            except Standard_Failure:
                return None

        h_min = 0.0
        for k in range(n_slab):
            h = lv.y[k + 1] - lv.y[k]
            if h > 0.0 and (h_min <= 0.0 or h < h_min):
                h_min = h
        lin_tol = max(_CONFUSION, (1e-6 * h_min if h_min > 0.0 else 0.0))

        acc = slabs[0]
        for k in range(1, n_slab):
            fuse = BRepAlgoAPI_Fuse(acc, slabs[k])
            fuse.SetRunParallel(False)
            fuse.SetFuzzyValue(max(lin_tol, _CONFUSION))
            fuse.SetGlue(BOPAlgo_GlueEnum.BOPAlgo_GlueShift)
            fuse.Build()
            # OCP does not expose BRepAlgoAPI_Fuse::HasErrors (OCCT 7.9); the
            # reference retries a plain fuse when it reports errors, but the
            # handle-lock fuse is clean, so IsDone() selects the same branch.
            if not fuse.IsDone():
                fuse2 = BRepAlgoAPI_Fuse(acc, slabs[k])
                fuse2.SetRunParallel(False)
                fuse2.SetFuzzyValue(max(lin_tol, _CONFUSION))
                fuse2.Build()
                if not fuse2.IsDone():
                    return None
                acc = fuse2.Shape()
            else:
                acc = fuse.Shape()
            if acc.IsNull() or _count_faces(acc) < 1:
                return None
            pb.diag.fuses.append((k, _count_faces(acc)))

        acc = _unify_same_once(acc, pb)
        pb.diag.unify = (
            _count_faces(acc),
            1,
            pb.unify_g2,
            pb.unify_g4,
            pb.unify_v0,
            pb.unify_v1,
            pb.unify_p0,
            pb.unify_p1,
            pb.unify_c0,
            pb.unify_c1,
        )
        n_f = _count_faces(acc)
        if n_f < 1:
            return None
        return acc if not acc.IsNull() else None
    except Exception:  # noqa: BLE001 - port of the reference's catch-all guard
        return None


# --- tryStageP (refit_prism_build.cpp:981-1185) ----------------------------------

def try_stage_p(mv, rs: RegionSet) -> PrismResult:
    """Port of ``tryStageP`` (refit_prism_build.cpp:981). Never throws."""
    result = PrismResult()
    pb = result.pb
    n_faces = 0
    n_planes = 0
    n_cyls = 0
    n_slabs = 0
    vol = 0.0
    wt = 0
    valid = 0
    reverted = 1
    try:
        pt = PrismTols()
        lv = detect_prismatic(mv, rs, pt)
        if not lv.ok or len(lv.y) < 2:
            return result
        n_slabs = len(lv.y) - 1

        origin3 = np.zeros(3)
        if lv.cap_region:
            for r in rs.regions:
                if r.id == lv.cap_region[0]:
                    origin3 = _pnt_xyz(r.ax.Location())
                    break
        else:
            for r in rs.regions:
                if r.type == SurfType.CYLINDER:
                    origin3 = _pnt_xyz(r.ax.Location())
                    break

        profs = slice_profiles(mv, rs, lv, pt)
        ready = len(profs) > 0
        if ready:
            for p in profs:
                fit_profile(mv, pt, p)

        # D8 §3.2: guarded cylinder-span validation (refit_prism_build.cpp:1074).
        def snap_lvl(yv: float) -> int:
            best = -1
            best_d = 0.0
            for k in range(len(lv.y)):
                d = abs(yv - lv.y[k])
                if d <= pt.tau_lvl and (best < 0 or d < best_d):
                    best = k
                    best_d = d
            return best

        if ready:
            for r in rs.regions:
                if r.type != SurfType.CYLINDER or not (r.radius > 0.0):
                    continue
                a = _dir_xyz(r.ax.Direction())
                loc = _pnt_xyz(r.ax.Location())
                p0 = loc + a * r.v_min
                p1 = loc + a * r.v_max
                ah = np.asarray(lv.axis, dtype=float)
                y0 = _dot3(ah, p0)
                y1 = _dot3(ah, p1)
                lo = min(y0, y1)
                hi = max(y0, y1)
                i0 = snap_lvl(lo)
                i1 = snap_lvl(hi)
                if i0 < 0 or i1 < 0 or (i1 - i0) < 2:
                    continue
                for k in range(i0, i1):
                    found = False
                    if k < 0 or k >= len(profs):
                        ready = False
                        break
                    p = profs[k]
                    assoc = max(pt.tau_fit, 4.0 * r.max_vertex_dev, 4.0 * r.chord_sagitta)
                    for lp in p.loops:
                        if lp.outer:
                            continue
                        for s in lp.segs:
                            if s.is_arc and s.r > 0.0 and abs(s.r - r.radius) <= assoc:
                                found = True
                                break
                        if found:
                            break
                        if len(lp.segs) >= 3:
                            cx = 0.0
                            cy = 0.0
                            for s in lp.segs:
                                cx += s.a[0]
                                cy += s.a[1]
                            cx /= len(lp.segs)
                            cy /= len(lp.segs)
                            rmin = 1e300
                            rmax = 0.0
                            for s in lp.segs:
                                d = math.hypot(s.a[0] - cx, s.a[1] - cy)
                                rmin = min(rmin, d)
                                rmax = max(rmax, d)
                            if rmax - rmin <= 8.0 * assoc and abs(
                                0.5 * (rmin + rmax) - r.radius
                            ) <= assoc:
                                found = True
                    if not found:
                        ready = False
                        break
                if not ready:
                    break

        solid = None
        if ready:
            solid = build_prism_solid(profs, lv, origin3, pb)
            if solid is None or solid.IsNull():
                solid = None
        if solid is not None:
            faces = []
            fx = TopExp_Explorer(solid, TopAbs_FACE)
            while fx.More():
                faces.append(TopoDS.Face_s(fx.Current()))
                fx.Next()
            wt = 1 if _shape_closed(solid) else 0
            valid = 1 if _shape_valid(solid) else 0
            vol = _shape_vol(solid)
            n_faces = len(faces)
            n_planes, n_cyls = _count_surf(solid)
            d_vol_abs = 0.0
            for r in rs.regions:
                d_vol_abs += abs(r.dvol_predicted)
            mesh_vol = abs(_mesh_vol(mv))
            budget = max(1e-4 * mesh_vol, 3.0 * d_vol_abs)
            d_signed, d_abs = _profile_arc_defects(profs, lv, rs)
            v_ref = mesh_vol - d_signed
            k_prism = 1.0 + 5.0 / 100.0
            envelope = k_prism * d_abs
            cond1 = abs(vol - v_ref) <= budget
            cond2 = abs(vol - mesh_vol) <= envelope
            vol_ok = cond1 and cond2
            pb.diag.vol_gate = (
                d_signed,
                d_abs,
                v_ref,
                budget,
                envelope,
                abs(vol - v_ref),
                abs(vol - mesh_vol),
                1 if cond1 else 0,
                1 if cond2 else 0,
            )
            pb.diag.g_line = (
                1,
                pb.unify_g2,
                n_planes,
                pb.unify_g4,
                pb.unify_c0,
                pb.unify_c1,
                pb.unify_v0,
                pb.unify_v1,
            )
            if wt and valid and vol_ok and faces:
                reverted = 0
                rs.stats.planes = n_planes
                rs.stats.cylinders = n_cyls
                rs.stats.facet_islands = 0
                rs.stats.facet_triangles = 0
                pb.diag.census = (
                    rs.comp_root if rs.comp_root >= 0 else 0,
                    n_slabs,
                    n_faces,
                    n_planes,
                    n_cyls,
                    vol,
                    wt,
                    valid,
                    reverted,
                )
                result.ok = True
                result.faces = faces
                return result

        pb.diag.census = (
            rs.comp_root if rs.comp_root >= 0 else 0,
            n_slabs,
            n_faces,
            n_planes,
            n_cyls,
            vol,
            wt,
            valid,
            reverted,
        )
        return result  # noqa: TRY300 - port of the reference's try/catch guard
    except Exception:  # noqa: BLE001 - port of the reference's catch-all guard
        pb.diag.census = (
            rs.comp_root if rs.comp_root >= 0 else 0,
            n_slabs,
            n_faces,
            n_planes,
            n_cyls,
            vol,
            wt,
            valid,
            reverted,
        )
        return result
