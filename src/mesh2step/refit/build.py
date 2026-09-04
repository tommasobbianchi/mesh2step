"""Analytic planar face building — port of refs/stl2step/src/refit_build.cpp
(P2 buildFaces), planar subset.

Each accepted plane region becomes ONE Geom_Plane face carrying its outer loop
(and inner loops where the region has holes). Boundary chains between two
analytic regions are collapsed to the intersection line of the fitted planes
(IntAna plane|plane); chains touching faceted islands stay mesh polylines so
the shell keeps shared vertex/edge TShapes. A region whose face cannot be
built is exploded to its own triangles (BuiltAs.ExplodedToFacets) — it still
counts as a plane in the segmentation stats. Cylinders, fillets and the
prismatic rebuild are M3-M5 stubs that build nothing.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepLib import BRepLib
from OCP.BRepTools import BRepTools_WireExplorer
from OCP.ElCLib import ElCLib
from OCP.GC import GC_MakeArcOfCircle
from OCP.Geom import (
    Geom_Circle,
    Geom_CylindricalSurface,
    Geom_Ellipse,
    Geom_Line,
    Geom_Plane,
    Geom_TrimmedCurve,
)
from OCP.Geom2d import Geom2d_Line
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.gp import (
    gp_Ax1,
    gp_Ax2,
    gp_Ax3,
    gp_Circ,
    gp_Cylinder,
    gp_Dir,
    gp_Dir2d,
    gp_Elips,
    gp_Lin,
    gp_Pln,
    gp_Pnt,
    gp_Pnt2d,
    gp_Vec,
    gp_Vec2d,
)
from OCP.IntAna import IntAna_QuadQuadGeo, IntAna_ResultType
from OCP.Precision import Precision
from OCP.ShapeFix import ShapeFix_Edge, ShapeFix_Face
from OCP.Standard import Standard_Failure
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_VERTEX
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import (
    TopoDS,
    TopoDS_Edge,
    TopoDS_Face,
    TopoDS_Shell,
    TopoDS_Vertex,
    TopoDS_Wire,
)
from OCP.TopTools import TopTools_IndexedMapOfShape

from .mesh_view import MeshView
from .segment import (
    BoundaryChain,
    BuiltAs,
    Loop,
    LoopRole,
    Region,
    RegionSet,
    Reject,
    SurfType,
    derived_eps_plane,
)

K_PI = math.pi


def _confusion() -> float:
    return Precision.Confusion_s()


# --- small geometry helpers ----------------------------------------------------

def _ax_dir(ax) -> np.ndarray:
    d = ax.Direction()
    return np.array([d.X(), d.Y(), d.Z()])


def _ax_loc(ax) -> np.ndarray:
    p = ax.Location()
    return np.array([p.X(), p.Y(), p.Z()])


def _ax3_of(region: Region) -> gp_Pln:
    return gp_Pln(region.ax)


def _region_by_id(rs: RegionSet, rid: int) -> Region | None:
    if rid < 0 or rid >= len(rs.regions):
        return None
    return rs.regions[rid]


def _is_analytic(r: Region | None) -> bool:
    return r is not None and r.type in (SurfType.PLANE, SurfType.CYLINDER)


def _pnt_of(vert: TopoDS_Vertex) -> gp_Pnt:
    return BRep_Tool.Pnt_s(vert)


def _face_is_valid(face: TopoDS_Face) -> bool:
    if face is None or face.IsNull():
        return False
    try:
        return bool(BRepCheck_Analyzer(face, False).IsValid())
    except Standard_Failure:
        return False


def _shell_is_valid(shape) -> bool:
    if shape is None or shape.IsNull():
        return False
    try:
        return bool(BRepCheck_Analyzer(shape, True).IsValid())
    except Standard_Failure:
        return False


def _set_face_outward(face: TopoDS_Face, outward: bool) -> TopoDS_Face:
    if face is None or face.IsNull():
        return face
    if not outward and face.Orientation() == TopAbs_FORWARD:
        return TopoDS.Face_s(face.Reversed())
    if outward and face.Orientation() == TopAbs_REVERSED:
        return TopoDS.Face_s(face.Reversed())
    return face


def _mesh_tol_cap(mv: MeshView, region: Region | None) -> float:
    c = max(mv.sew_tol, _confusion())
    if region is not None:
        c = max(c, region.chord_sagitta)
        if region.radius > 0.0:
            c = max(c, region.radius * (1.0 - math.cos(K_PI / 4.0)))
    return c * 1.001 + _confusion()


def _analytic_snap_cap(mv: MeshView, a: Region | None, b: Region | None) -> float:
    c = max(_mesh_tol_cap(mv, a), _mesh_tol_cap(mv, b))
    if a is not None:
        c = max(c, a.max_vertex_dev)
    if b is not None:
        c = max(c, b.max_vertex_dev)
    return max(c, derived_eps_plane(mv))


def _ensure_face_valid(face: TopoDS_Face, cap: float) -> bool:
    """F4: absorb deviation in edge/vertex tolerance, never past the cap."""
    if face is None or face.IsNull():
        return False
    if _face_is_valid(face):
        return True
    if not cap > 0.0:
        cap = _confusion()
    try:
        builder = BRep_Builder()
        surf = BRepAdaptor_Surface(face, False)

        def dev_pnt(p: gp_Pnt) -> float:
            if surf.GetType() == GeomAbs_Plane:
                return surf.Plane().Distance(p)
            if surf.GetType() == GeomAbs_Cylinder:
                # |rho(p) - R|. Without this branch a cylindrical face measures zero
                # deviation everywhere, so nothing is ever absorbed and the repair
                # cannot succeed -- which is how every partial arc band was failing.
                cyl = surf.Cylinder()
                v = gp_Vec(cyl.Location(), p)
                axis = gp_Vec(cyl.Axis().Direction())
                return abs(axis.Crossed(v).Magnitude() - cyl.Radius())
            return 0.0

        vx = TopExp_Explorer(face, TopAbs_VERTEX)
        while vx.More():
            vv = TopoDS.Vertex_s(vx.Current())
            d = dev_pnt(_pnt_of(vv))
            if d > 0.0:
                if d > cap:
                    return False
                if d > BRep_Tool.Tolerance_s(vv):
                    builder.UpdateVertex(vv, min(d * 1.001 + _confusion(), cap))
            vx.Next()
        ex = TopExp_Explorer(face, TopAbs_EDGE)
        while ex.More():
            edge = TopoDS.Edge_s(ex.Current())
            d = 0.0
            evx = TopExp_Explorer(edge, TopAbs_VERTEX)
            while evx.More():
                d = max(d, dev_pnt(_pnt_of(TopoDS.Vertex_s(evx.Current()))))
                evx.Next()
            first, last = 0.0, 0.0
            curve = BRep_Tool.Curve_s(edge, first, last)
            if curve is not None:
                d = max(d, dev_pnt(curve.Value(0.5 * (first + last))))
            if d > cap:
                return False
            if d > BRep_Tool.Tolerance_s(edge):
                builder.UpdateEdge(edge, min(d * 1.001 + _confusion(), cap))
            ex.Next()
    except Standard_Failure:
        return False
    return _face_is_valid(face)


def _mesh_component_closed(mv: MeshView) -> bool:
    use = [0] * mv.n_edge
    for t in range(mv.n_tri):
        for s in range(3):
            e = int(mv.tri_edges[t, s])
            if 0 <= e < mv.n_edge:
                use[e] += 1
    for u in use:
        if u == 1:
            return False
    return mv.n_tri > 0


# --- analytic curves (plane|plane only in M2) ----------------------------------

class _Curve:
    __slots__ = ("circ", "elips", "kind", "lin")

    NONE, LIN, CIRC, ELIPS = 0, 1, 2, 3

    def __init__(self):
        self.kind = _Curve.NONE
        self.lin: gp_Lin | None = None
        self.circ: gp_Circ | None = None
        self.elips: gp_Elips | None = None


def _curve_residual(curve: _Curve, p: gp_Pnt) -> float:
    try:
        if curve.kind == _Curve.LIN and curve.lin is not None:
            return curve.lin.Distance(p)
        if curve.kind == _Curve.CIRC and curve.circ is not None:
            t = ElCLib.Parameter_s(curve.circ, p)
            return ElCLib.Value_s(t, curve.circ).Distance(p)
        if curve.kind == _Curve.ELIPS and curve.elips is not None:
            t = ElCLib.Parameter_s(curve.elips, p)
            return ElCLib.Value_s(t, curve.elips).Distance(p)
    except Standard_Failure:
        return 1e300
    return 1e300


def _cylinder_iso_circle(cyl: Region, v: float) -> gp_Circ:
    """refit_build.cpp:517 — the iso-parameter circle at height v on a cylinder."""
    loc = cyl.ax.Location().Translated(gp_Vec(cyl.ax.Direction()).Multiplied(v))
    return gp_Circ(gp_Ax2(loc, cyl.ax.Direction(), cyl.ax.XDirection()), cyl.radius)


def _plane_perp_cylinder(pln: Region, cyl: Region) -> bool:
    """refit_build.cpp:522 — plane normal within 3 deg of the cylinder axis."""
    c = abs(pln.ax.Direction().Dot(cyl.ax.Direction()))
    return c >= math.cos(3.0 * K_PI / 180.0)


def _plane_v_on_cylinder(pln: Region, cyl: Region) -> float:
    """refit_build.cpp:527 — the cylinder v at which a plane cuts the axis."""
    n = pln.ax.Direction()
    a = cyl.ax.Direction()
    na = n.Dot(a)
    if abs(na) < 1e-12:
        return 0.0
    return gp_Vec(cyl.ax.Location(), pln.ax.Location()).Dot(gp_Vec(n)) / na


def _constructed_plane_cyl_cap(pln: Region, cyl: Region) -> _Curve:
    """refit_build.cpp:759 — plane perpendicular to a cylinder -> its cap circle."""
    out = _Curve()
    if not _plane_perp_cylinder(pln, cyl):
        return out
    out.kind = _Curve.CIRC
    out.circ = _cylinder_iso_circle(cyl, _plane_v_on_cylinder(pln, cyl))
    return out


def _constructed_generator(cyl: Region, pln: Region) -> _Curve:
    """refit_build.cpp:767 — plane containing the axis direction -> a generator line.

    The reference leaves the parallel-to-axis precondition to its caller
    (planeCylSideContact); here the constructor itself declines for a plane that
    does not contain the axis, otherwise it would return a line at distance < R
    from the axis (a plausible wrong answer).
    """
    out = _Curve()
    n = pln.ax.Direction()
    a = cyl.ax.Direction()
    if abs(n.Dot(a)) > math.sin(3.0 * K_PI / 180.0) + 1e-15:
        return out
    axp = cyl.ax.Location()
    sd = gp_Vec(pln.ax.Location(), axp).Dot(gp_Vec(n))
    toward = gp_Vec(n).Reversed() if sd >= 0.0 else gp_Vec(n)
    mag = toward.Magnitude()
    if mag < _confusion():
        return out
    origin = axp.Translated(toward.Multiplied(cyl.radius))
    out.kind = _Curve.LIN
    out.lin = gp_Lin(origin, a)
    return out


def _chain_residual(curve: _Curve, mv: MeshView, chain: BoundaryChain) -> float:
    if not chain.mesh_verts:
        return 1e300
    total = 0.0
    for lv in chain.mesh_verts:
        p = mv.pts[int(mv.comp_vtx[lv])]
        total += _curve_residual(curve, gp_Pnt(float(p[0]), float(p[1]), float(p[2])))
    return total / len(chain.mesh_verts)


def _int_ana_accept_residual(
    mv: MeshView, chain: BoundaryChain, sew_tol: float, a: Region | None, b: Region | None
) -> float:
    accept_r = max(sew_tol * 50.0, 1.0)
    if a is not None and b is not None:
        fit = max(a.max_vertex_dev, b.max_vertex_dev)
        if len(chain.mesh_verts) <= 3:
            accept_r = max(accept_r, fit * 3.0 + derived_eps_plane(mv))
        elif len(chain.mesh_verts) <= 20:
            accept_r = max(accept_r, fit * 2.0 + derived_eps_plane(mv))
        # Skew/near-tangent cyl|cyl and plane|cyl cap circles (refit_build.cpp:570-579):
        # conics land off the mesh band on coarse exports — widen vs the fitted residual.
        if a.type == SurfType.CYLINDER and b.type == SurfType.CYLINDER:
            accept_r = max(accept_r, fit * 4.0 + derived_eps_plane(mv))
            if len(chain.mesh_verts) <= 3:
                accept_r = max(accept_r, fit * 5.0 + derived_eps_plane(mv) * 2.0)
        if (a.type == SurfType.PLANE and b.type == SurfType.CYLINDER) or (
            a.type == SurfType.CYLINDER and b.type == SurfType.PLANE
        ):
            if len(chain.mesh_verts) <= 3:
                accept_r = max(accept_r, fit * 5.0 + derived_eps_plane(mv) * 2.0)
    return accept_r


def _pick_int_ana(
    iq, mv: MeshView, chain: BoundaryChain, sew_tol: float, accept_residual: float = -1.0
) -> _Curve:
    best = _Curve()
    if not iq.IsDone():
        return best
    ty = iq.TypeInter()
    if ty in (
        IntAna_ResultType.IntAna_Empty,
        IntAna_ResultType.IntAna_Same,
        IntAna_ResultType.IntAna_NoGeometricSolution,
    ):
        return best
    best_r = 1e300

    def consider(cand: _Curve) -> None:
        nonlocal best_r, best
        r = _chain_residual(cand, mv, chain)
        if r < best_r:
            best_r = r
            best = cand

    n = iq.NbSolutions()
    if ty in (IntAna_ResultType.IntAna_Line, IntAna_ResultType.IntAna_PointAndCircle):
        for i in range(1, n + 1):
            cand = _Curve()
            try:
                cand.kind = _Curve.LIN
                cand.lin = iq.Line(i)
                consider(cand)
            except Standard_Failure:
                continue
    if ty in (IntAna_ResultType.IntAna_Circle, IntAna_ResultType.IntAna_PointAndCircle):
        for i in range(1, n + 1):
            cand = _Curve()
            try:
                cand.kind = _Curve.CIRC
                cand.circ = iq.Circle(i)
                consider(cand)
            except Standard_Failure:
                continue
    if ty == IntAna_ResultType.IntAna_Ellipse:
        for i in range(1, n + 1):
            cand = _Curve()
            try:
                cand.kind = _Curve.ELIPS
                cand.elips = iq.Ellipse(i)
                consider(cand)
            except Standard_Failure:
                continue
    if best.kind != _Curve.NONE:
        accept_r = accept_residual if accept_residual > 0.0 else max(sew_tol * 50.0, 1.0)
        if best_r > accept_r:
            best = _Curve()
    return best


def _intersect_surfaces(
    a: Region, b: Region, mv: MeshView, chain: BoundaryChain, sew_tol: float
) -> _Curve:
    """plane|plane, plane|cylinder and cylinder|cylinder intersection
    (refit_build.cpp:950 intersectSurfaces)."""
    tol_ang = Precision.Angular_s()
    tol = max(sew_tol, _confusion())
    try:
        if a.type == SurfType.PLANE and b.type == SurfType.PLANE:
            iq = IntAna_QuadQuadGeo(_ax3_of(a), _ax3_of(b), tol_ang, tol)
            accept_r = _int_ana_accept_residual(mv, chain, sew_tol, a, b)
            return _pick_int_ana(iq, mv, chain, sew_tol, accept_r)
        if a.type == SurfType.PLANE and b.type == SurfType.CYLINDER:
            h = abs(b.v_max - b.v_min)
            iq = IntAna_QuadQuadGeo(_ax3_of(a), _cyl_for_intersect(b), tol_ang, tol, h)
            accept_r = _int_ana_accept_residual(mv, chain, sew_tol, a, b)
            c = _pick_int_ana(iq, mv, chain, sew_tol, accept_r)
            # Oblique plane|cyl: IntAna ellipse on 2-vertex coarse chains often
            # exceeds the first-pass residual gate (refit_build.cpp:972-977).
            if (
                c.kind == _Curve.NONE
                and iq.IsDone()
                and iq.TypeInter() == IntAna_ResultType.IntAna_Ellipse
                and len(chain.mesh_verts) <= 3
            ):
                fit = max(a.max_vertex_dev, b.max_vertex_dev)
                loose = max(accept_r, fit * 8.0 + derived_eps_plane(mv) * 3.0)
                c = _pick_int_ana(iq, mv, chain, sew_tol, loose)
            # Cap circle from the fitted cylinder when IntAna misses or picks the
            # wrong branch (refit_build.cpp:986).
            if c.kind == _Curve.NONE and _plane_perp_cylinder(a, b):
                c = _constructed_plane_cyl_cap(a, b)
            # Ellipse branch on a cap plane is often a noisy IntAna circle
            # (refit_build.cpp:990).
            if c.kind == _Curve.ELIPS and _plane_perp_cylinder(a, b) and not b.closed360:
                cap = _constructed_plane_cyl_cap(a, b)
                if cap.kind == _Curve.CIRC:
                    c = cap
            return c
        if a.type == SurfType.CYLINDER and b.type == SurfType.PLANE:
            return _intersect_surfaces(b, a, mv, chain, sew_tol)
        if a.type == SurfType.CYLINDER and b.type == SurfType.CYLINDER:
            iq = IntAna_QuadQuadGeo(_cyl_for_intersect(a), _cyl_for_intersect(b), tol)
            accept_r = _int_ana_accept_residual(mv, chain, sew_tol, a, b)
            return _pick_int_ana(iq, mv, chain, sew_tol, accept_r)
    except Standard_Failure:
        return _Curve()
    return _Curve()


def _bump_vertex_tol(vert: TopoDS_Vertex, d: float) -> None:
    if vert is None or vert.IsNull() or not d > 0.0:
        return
    if d > BRep_Tool.Tolerance_s(vert):
        BRep_Builder().UpdateVertex(vert, d * 1.001 + _confusion())


def _snap_vertex_to_curve(vert: TopoDS_Vertex, curve: _Curve, cap: float) -> None:
    if vert is None or vert.IsNull():
        return
    d = _curve_residual(curve, _pnt_of(vert))
    if not math.isfinite(d) or d > cap:
        return
    _bump_vertex_tol(vert, d)


def _bind_edge_by_param(gc, v1: TopoDS_Vertex, v2: TopoDS_Vertex, p1: float, p2: float):
    if gc is None or v1.IsNull() or v2.IsNull():
        return None
    try:
        me = BRepBuilderAPI_MakeEdge(gc, v1, v2, p1, p2)
        if me.IsDone():
            return me.Edge()
    except Standard_Failure:
        pass
    return None


def _make_edge_from_curve(curve: _Curve, v1: TopoDS_Vertex, v2: TopoDS_Vertex, closed_full: bool):
    try:
        if curve.kind == _Curve.LIN and curve.lin is not None:
            me = BRepBuilderAPI_MakeEdge(curve.lin, v1, v2)
            if me.IsDone():
                return me.Edge()
            p1 = ElCLib.Parameter_s(curve.lin, _pnt_of(v1))
            p2 = ElCLib.Parameter_s(curve.lin, _pnt_of(v2))
            if abs(p1 - p2) <= _confusion():
                return None
            return _bind_edge_by_param(Geom_Line(curve.lin), v1, v2, p1, p2)
        if curve.kind == _Curve.CIRC and curve.circ is not None:
            if closed_full or v1.IsSame(v2):
                me = BRepBuilderAPI_MakeEdge(curve.circ, v1, v1)
                if me.IsDone():
                    return me.Edge()
                me = BRepBuilderAPI_MakeEdge(curve.circ)
                if me.IsDone():
                    return me.Edge()
            else:
                me = BRepBuilderAPI_MakeEdge(curve.circ, v1, v2)
                if me.IsDone():
                    return me.Edge()
        if curve.kind == _Curve.ELIPS and curve.elips is not None:
            # refit_build.cpp:1099-1106 — a tilted plane|cyl cap is a full ellipse.
            if closed_full or v1.IsSame(v2):
                me = BRepBuilderAPI_MakeEdge(curve.elips, v1, v1)
                if me.IsDone():
                    return me.Edge()
            else:
                me = BRepBuilderAPI_MakeEdge(curve.elips, v1, v2)
                if me.IsDone():
                    return me.Edge()
    except Standard_Failure:
        pass
    return None


def _mixed_edge_deviation(v1: TopoDS_Vertex, v2: TopoDS_Vertex, analytic: Region | None) -> float:
    if analytic is None:
        return 0.0
    a, b = _pnt_of(v1), _pnt_of(v2)
    m = gp_Pnt(0.5 * (a.X() + b.X()), 0.5 * (a.Y() + b.Y()), 0.5 * (a.Z() + b.Z()))

    def dev(p: gp_Pnt) -> float:
        if analytic.type == SurfType.PLANE:
            return _ax3_of(analytic).Distance(p)
        return 0.0

    return max(dev(m), max(dev(a), dev(b)))


# --- cylinder seam / azimuth helpers (refit_build.cpp:224-285, 1826-1900) ---------

def _as_cyl(region: Region) -> gp_Cylinder:
    return gp_Cylinder(region.ax, region.radius)


def _cyl_for_intersect(region: Region) -> gp_Cylinder:
    """refit_build.cpp:174 — intersect against the (possibly rotated) partial
    surface frame so a band straddling the seam still presents the right U=0."""
    if region.type != SurfType.CYLINDER:
        return _as_cyl(region)
    return _cyl_surface_for_region(region).Cylinder()


def _azimuth_of(region: Region, p: gp_Pnt) -> float:
    """refit_build.cpp:224 — azimuth in [0, 2π) around the cylinder axis."""
    loc = region.ax.Location()
    d = region.ax.Direction()
    rho = gp_Vec(loc, p)
    rad = rho.Subtracted(gp_Vec(d).Multiplied(rho.Dot(gp_Vec(d))))
    if rad.Magnitude() < _confusion():
        return 0.0
    x = rad.Dot(gp_Vec(region.ax.XDirection()))
    y = rad.Dot(gp_Vec(region.ax.YDirection()))
    u = math.atan2(y, x)
    if u < 0.0:
        u += 2.0 * K_PI
    return u


def _wrap_to_pi(t: float) -> float:
    while t <= -K_PI:
        t += 2.0 * K_PI
    while t > K_PI:
        t -= 2.0 * K_PI
    return t


def _shift_into_u_span(chi: float, u_min: float, u_max: float) -> float:
    """refit_build.cpp:1834 — shift chi into [uMin, uMin+2π)."""
    two_pi = 2.0 * K_PI
    k = math.ceil((u_min - chi) / two_pi)
    t = chi + two_pi * k
    if t < u_min:
        t += two_pi
    if t >= u_min + two_pi:
        t -= two_pi
    if t > u_max:
        t2 = t - two_pi
        d_hi = t - u_max
        d_lo = u_min - t2
        if d_lo <= d_hi:
            t = t2
    return t


def _seam_straddle_u(region: Region) -> bool:
    if region.type != SurfType.CYLINDER or region.closed360:
        return False
    u0 = region.u_min
    u1 = region.u_max
    if u1 < u0:
        u1 += 2.0 * K_PI
    return (u0 < -0.5 * K_PI and u1 > 0.0) or (u0 < 2.0 * K_PI and u1 > 2.0 * K_PI)


def _region_u(region: Region, p: gp_Pnt) -> float:
    chi = _wrap_to_pi(_azimuth_of(region, p))
    if _seam_straddle_u(region):
        return _shift_into_u_span(chi, region.u_min, region.u_max)
    return chi


def _region_v(region: Region, p: gp_Pnt) -> float:
    return gp_Vec(region.ax.Location(), p).Dot(gp_Vec(region.ax.Direction()))


def _azimuth_on_ax(ax: gp_Ax3, p: gp_Pnt) -> float:
    rho = gp_Vec(ax.Location(), p)
    rad = rho.Subtracted(gp_Vec(ax.Direction()).Multiplied(rho.Dot(gp_Vec(ax.Direction()))))
    if rad.Magnitude() < _confusion():
        return 0.0
    u = math.atan2(rad.Dot(gp_Vec(ax.YDirection())), rad.Dot(gp_Vec(ax.XDirection())))
    if u < 0.0:
        u += 2.0 * K_PI
    if u > K_PI:
        u -= 2.0 * K_PI
    return u


def _v_on_ax(ax: gp_Ax3, p: gp_Pnt) -> float:
    return gp_Vec(ax.Location(), p).Dot(gp_Vec(ax.Direction()))


def _project_pnt_on_cylinder(region: Region, p: gp_Pnt) -> gp_Pnt:
    """refit_build.cpp:1913 — project a point onto the fitted cylinder surface."""
    rho = gp_Vec(region.ax.Location(), p)
    ax = gp_Vec(region.ax.Direction())
    v = rho.Dot(ax)
    rad = rho.Subtracted(ax.Multiplied(v))
    mag = rad.Magnitude()
    if mag < _confusion():
        rad = gp_Vec(region.ax.XDirection()).Multiplied(region.radius)
    else:
        rad.Scale(region.radius / mag)
    return region.ax.Location().Translated(ax.Multiplied(v).Added(rad))


def _seam_vertex_of(mv: MeshView, cyl: Region, chain: BoundaryChain) -> int:
    """refit_build.cpp:237 — vertex whose azimuth is closest to 0."""
    best = chain.mesh_verts[0] if chain.mesh_verts else -1
    best_u = 1e300
    for lv in chain.mesh_verts:
        p = mv.pts[int(mv.comp_vtx[lv])]
        u = _azimuth_of(cyl, gp_Pnt(float(p[0]), float(p[1]), float(p[2])))
        d = min(u, 2.0 * K_PI - u)
        if d < best_u:
            best_u = d
            best = lv
    return best


def _vertex_closest_to_u(mv: MeshView, cyl: Region, chain: BoundaryChain, target: float) -> int:
    """refit_build.cpp:252."""
    best = chain.mesh_verts[0] if chain.mesh_verts else -1
    best_d = 1e300
    for lv in chain.mesh_verts:
        if lv < 0 or lv >= mv.n_vtx:
            continue
        p = mv.pts[int(mv.comp_vtx[lv])]
        u = _azimuth_of(cyl, gp_Pnt(float(p[0]), float(p[1]), float(p[2])))
        d = abs(u - target)
        d = min(d, 2.0 * K_PI - d)
        if d < best_d:
            best_d = d
            best = lv
    return best


def _vertex_closest_to_u_on_loop(
    mv: MeshView, cyl: Region, loop: Loop, rs: RegionSet, target: float
) -> int:
    """refit_build.cpp:268."""
    best = -1
    best_d = 1e300
    for ci in loop.chain_idx:
        if ci < 0 or ci >= len(rs.chains):
            continue
        v = _vertex_closest_to_u(mv, cyl, rs.chains[ci], target)
        if v < 0:
            continue
        p = mv.pts[int(mv.comp_vtx[v])]
        u = _azimuth_of(cyl, gp_Pnt(float(p[0]), float(p[1]), float(p[2])))
        d = abs(u - target)
        d = min(d, 2.0 * K_PI - d)
        if d < best_d:
            best_d = d
            best = v
    return best


def _edge_spans_full_circle(edge: TopoDS_Edge) -> bool:
    """refit_build.cpp:161."""
    if edge is None or edge.IsNull():
        return False
    f, last = BRep_Tool.Range_s(edge)
    c = BRep_Tool.Curve_s(edge, 0.0, 0.0)
    if c is None:
        return False
    return abs(abs(last - f) - 2.0 * K_PI) <= 0.05


def _cylinder_post_fit_ok(region: Region, mv: MeshView, rs: RegionSet) -> bool:
    """refit_build.cpp:302 — F3 post-fit chord sagitta gate. Rejects the 3-sided
    closed360 fixtures (sagitta/R = 0.5) while keeping live nSides=4."""
    if region.type != SurfType.CYLINDER or region.radius <= 0.0:
        return True
    lim = region.radius * (1.0 - math.cos(K_PI / 4.0)) * 1.001 + _confusion()
    cyl = _as_cyl(region)

    def rad_dev(p: gp_Pnt) -> float:
        v = gp_Vec(cyl.Location(), p)
        return abs(gp_Vec(cyl.Axis().Direction()).Crossed(v).Magnitude() - cyl.Radius())

    d = 0.0
    for lt in region.tris:
        if lt < 0 or lt >= mv.n_tri:
            continue
        gt = int(mv.comp_tris[lt])
        for i in range(3):
            p = mv.pts[int(mv.tris[gt, i])]
            d = max(d, rad_dev(gp_Pnt(float(p[0]), float(p[1]), float(p[2]))))
            if d > lim:
                return False
    for ch in rs.chains:
        if ch.reg_a != region.id and ch.reg_b != region.id:
            continue
        for eid in ch.mesh_edges:
            if eid < 0 or eid >= mv.n_edge:
                continue
            a, b = mv.comp_edges[eid]
            pa = mv.pts[int(a)]
            pb = mv.pts[int(b)]
            mid = gp_Pnt(
                0.5 * (pa[0] + pb[0]), 0.5 * (pa[1] + pb[1]), 0.5 * (pa[2] + pb[2])
            )
            d = max(d, rad_dev(mid))
            if d > lim:
                return False
    return True


# --- edge construction from fitted circles (refit_build.cpp:1113, 2529) ----------

def _make_full_circle(circ: gp_Circ, v: TopoDS_Vertex) -> TopoDS_Edge:
    """refit_build.cpp:2529."""
    try:
        me = BRepBuilderAPI_MakeEdge(circ, v, v)
        if me.IsDone():
            e = me.Edge()
            e.Closed(True)
            return e
    except Standard_Failure:
        pass
    try:
        me2 = BRepBuilderAPI_MakeEdge(circ)
        if me2.IsDone():
            e = me2.Edge()
            e.Closed(True)
            return e
    except Standard_Failure:
        pass
    try:
        gc = Geom_Circle(circ)
        b = BRep_Builder()
        e = TopoDS_Edge()
        b.MakeEdge(e, gc, _confusion())
        b.Add(e, v.Oriented(TopAbs_FORWARD))
        b.Add(e, v.Oriented(TopAbs_REVERSED))
        b.Range(e, 0.0, 2.0 * K_PI)
        e.Closed(True)
    except Standard_Failure:
        return TopoDS_Edge()
    return e


def _make_arc(circ: gp_Circ, va: TopoDS_Vertex, vb: TopoDS_Vertex, mid_hint: gp_Pnt) -> TopoDS_Edge:
    """refit_build.cpp:1113 — bound the circle with the shared verts; the mesh
    mid-vertex picks which of the two arcs (critical at 180°)."""
    two_pi = 2.0 * K_PI

    def wrap(t: float) -> float:
        while t < 0.0:
            t += two_pi
        while t >= two_pi:
            t -= two_pi
        return t

    try:
        p1 = wrap(ElCLib.Parameter_s(circ, _pnt_of(va)))
        p2 = wrap(ElCLib.Parameter_s(circ, _pnt_of(vb)))
        pm = wrap(ElCLib.Parameter_s(circ, mid_hint))
        df = p2 - p1
        while df <= 0.0:
            df += two_pi
        dm = pm - p1
        while dm < 0.0:
            dm += two_pi
        gc = Geom_Circle(circ)
        b = BRep_Builder()
        e = TopoDS_Edge()
        b.MakeEdge(e, gc, _confusion())
        if dm <= df + 1e-9:
            b.Add(e, va.Oriented(TopAbs_FORWARD))
            b.Add(e, vb.Oriented(TopAbs_REVERSED))
            b.Range(e, p1, p1 + df)
        else:
            db = two_pi - df
            t0 = wrap(p1 - db)
            b.Add(e, vb.Oriented(TopAbs_FORWARD))
            b.Add(e, va.Oriented(TopAbs_REVERSED))
            b.Range(e, t0, t0 + db)
            e.Reverse()
    except Standard_Failure:
        return TopoDS_Edge()
    return e
    try:
        me = BRepBuilderAPI_MakeEdge(circ, va, vb)
        if me.IsDone():
            return me.Edge()
    except Standard_Failure:
        pass
    try:
        mk = GC_MakeArcOfCircle(_pnt_of(va), mid_hint, _pnt_of(vb))
        if mk.IsDone():
            me = BRepBuilderAPI_MakeEdge(mk.Value(), va, vb)
            if me.IsDone():
                return me.Edge()
    except Standard_Failure:
        pass
    return TopoDS_Edge()


def _orient_edge_from_to(edge: TopoDS_Edge, from_vert: TopoDS_Vertex) -> TopoDS_Edge:
    """refit_build.cpp:441."""
    v1 = TopExp.FirstVertex_s(edge, True)
    if v1.IsNull():
        return edge
    if v1.IsSame(from_vert):
        return edge
    return TopoDS.Edge_s(edge.Reversed())


def _edge_uses_linear_cyl_pcurve(edge: TopoDS_Edge) -> bool:
    """refit_build.cpp:1926 — a conic (ellipse) pcurve must not be replaced by a
    linear one."""
    c = BRep_Tool.Curve_s(edge, 0.0, 0.0)
    if c is None:
        return True
    if isinstance(c, Geom_Ellipse):
        return False
    if isinstance(c, Geom_TrimmedCurve):
        basis = c.BasisCurve()
        if isinstance(basis, Geom_Ellipse):
            return False
    return True


def _add_pcurves_on_surface(surf, edge: TopoDS_Edge, is_seam: bool, sew_tol: float) -> None:
    """refit_build.cpp:435."""
    sfe = ShapeFix_Edge()
    sfe.FixAddPCurve(edge, surf, TopLoc_Location(), is_seam, sew_tol)


def _add_pcurves_on_face(face: TopoDS_Face, sew_tol: float, closed360: bool) -> None:
    """refit_build.cpp:417 — project a pcurve for every edge of the face; an edge
    that appears twice is a seam."""
    sfe = ShapeFix_Edge()
    emap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(face, TopAbs_EDGE, emap)
    count = [0] * (emap.Extent() + 1)
    ex = TopExp_Explorer(face, TopAbs_EDGE)
    while ex.More():
        i = emap.FindIndex(ex.Current())
        if i > 0:
            count[i] += 1
        ex.Next()
    for i in range(1, emap.Extent() + 1):
        e = TopoDS.Edge_s(emap.FindKey(i))
        is_seam = count[i] >= 2
        sfe.FixAddPCurve(e, face, is_seam, sew_tol)


def _bind_cyl_pcurves(wire: TopoDS_Wire, surf, region: Region, sew_tol: float) -> None:
    """refit_build.cpp:1949 — linear pcurves on a cylindrical surface, in the
    fitted (or rotated) parametric frame."""
    rotated = (
        isinstance(surf, Geom_CylindricalSurface)
        and surf.Position().XDirection().Angle(region.ax.XDirection()) > 1e-9
    )

    def to_uv(p: gp_Pnt) -> tuple[float, float]:
        if rotated:
            ax = surf.Position()
            return _azimuth_on_ax(ax, p), _v_on_ax(ax, p)
        return _region_u(region, p), _region_v(region, p)

    def unwrap_u(u1: float, u2: float) -> float:
        if not _seam_straddle_u(region) or rotated:
            while u2 - u1 > K_PI:
                u2 -= 2.0 * K_PI
            while u1 - u2 > K_PI:
                u2 += 2.0 * K_PI
        return u2

    b = BRep_Builder()
    for e_w in _wire_edges_in_order(wire):
        if not _edge_uses_linear_cyl_pcurve(e_w):
            _add_pcurves_on_surface(surf, e_w, False, sew_tol)
            continue
        pa = pb = None
        got_ends = False
        try:
            ad = BRepAdaptor_Curve(e_w)
            t0 = ad.FirstParameter()
            t1 = ad.LastParameter()
            if t1 - t0 > Precision.PConfusion_s():
                pa = _project_pnt_on_cylinder(region, ad.Value(t0))
                pb = _project_pnt_on_cylinder(region, ad.Value(t1))
                got_ends = pa.Distance(pb) > _confusion()
        except Standard_Failure:
            pass
        if not got_ends:
            f, last = BRep_Tool.Range_s(e_w)
            c3 = BRep_Tool.Curve_s(e_w, 0.0, 0.0)
            if c3 is not None and last - f > Precision.PConfusion_s():
                pa = _project_pnt_on_cylinder(region, c3.Value(f))
                pb = _project_pnt_on_cylinder(region, c3.Value(last))
                got_ends = pa.Distance(pb) > _confusion()
        if not got_ends:
            v1 = TopExp.FirstVertex_s(e_w, True)
            v2 = TopExp.LastVertex_s(e_w, True)
            if v1.IsNull() or v2.IsNull() or v1.IsSame(v2):
                continue
            pa = _project_pnt_on_cylinder(region, _pnt_of(v1))
            pb = _project_pnt_on_cylinder(region, _pnt_of(v2))
        u1, v1v = to_uv(pa)
        u2, v2v = to_uv(pb)
        u2 = unwrap_u(u1, u2)
        duv = gp_Vec2d(u2 - u1, v2v - v1v)
        mag = duv.Magnitude()
        if mag < Precision.PConfusion_s():
            continue
        ln = Geom2d_Line(gp_Pnt2d(u1, v1v), gp_Dir2d(duv))
        b.UpdateEdge(e_w, ln, surf, TopLoc_Location(), sew_tol)
        b.Range(e_w, surf, TopLoc_Location(), 0.0, mag)


def _rotate_edges_to_vertex(edges: list, v: TopoDS_Vertex) -> bool:
    """refit_build.cpp:1347 — rotate so the edge whose start is V comes first."""
    if not edges or v.IsNull():
        return False
    for i in range(len(edges)):
        if TopExp.FirstVertex_s(edges[i], True).IsSame(v):
            return _rotate_list(edges, i)
    for i in range(len(edges)):
        v1 = TopExp.FirstVertex_s(edges[i], False)
        v2 = TopExp.LastVertex_s(edges[i], False)
        if v1.IsSame(v) or v2.IsSame(v):
            if not TopExp.FirstVertex_s(edges[i], True).IsSame(v):
                edges[i] = TopoDS.Edge_s(edges[i].Reversed())
            return _rotate_list(edges, i)
    return False


def _rotate_list(items: list, i: int) -> bool:
    if i < 0 or i >= len(items):
        return False
    items[:] = items[i:] + items[:i]
    return True


# --- wire / face construction ----------------------------------------------------

def _walk_verts(chain: BoundaryChain, reversed_: bool) -> list:
    v = list(chain.mesh_verts)
    if reversed_:
        v.reverse()
    return v


def _edge_connecting(mv: MeshView, chain: BoundaryChain, va: int, vb: int) -> int:
    for eid in chain.mesh_edges:
        if eid < 0 or eid >= mv.n_edge:
            continue
        a, b = mv.comp_edges[eid]
        if (a == va and b == vb) or (a == vb and b == va):
            return eid
    return -1


def _append_polyline(
    builder, wire, mv: MeshView, chain: BoundaryChain, reversed_, mesh_e, edge_ok
) -> bool:
    vs = _walk_verts(chain, reversed_)
    n_seg = len(chain.mesh_edges)
    if not vs or n_seg == 0:
        return False
    for i in range(n_seg):
        va = vs[i % len(vs)]
        vb = vs[(i + 1) % len(vs)]
        if not chain.closed_loop and i + 1 >= len(vs):
            return False
        eid = _edge_connecting(mv, chain, va, vb)
        if eid < 0:
            idx = n_seg - 1 - i if reversed_ else i
            if idx >= len(chain.mesh_edges):
                return False
            eid = chain.mesh_edges[idx]
        if eid < 0 or eid >= len(mesh_e) or not edge_ok[eid]:
            return False
        a, _ = mv.comp_edges[eid]
        fwd = a == va
        e = mesh_e[eid]
        builder.Add(wire, e if fwd else TopoDS.Edge_s(e.Reversed()))
    return True


def _append_collapsed(builder, wire, edges: list, reversed_: bool) -> bool:
    if not edges:
        return False
    if not reversed_:
        for e in edges:
            builder.Add(wire, e)
    else:
        for i in range(len(edges) - 1, -1, -1):
            builder.Add(wire, TopoDS.Edge_s(edges[i].Reversed()))
    return True


def _build_loop_wire(loop: Loop, rs: RegionSet, mv: MeshView, geom, collapsed, mesh_e, edge_ok):
    builder = BRep_Builder()
    wire = TopoDS_Wire()
    builder.MakeWire(wire)
    if len(loop.chain_idx) != len(loop.reversed):
        return None
    for i, ci in enumerate(loop.chain_idx):
        if ci < 0 or ci >= len(rs.chains):
            return None
        rev = loop.reversed[i]
        if ci < len(collapsed) and collapsed[ci] and geom[ci]:
            ok = _append_collapsed(builder, wire, geom[ci], rev)
        else:
            ok = _append_polyline(builder, wire, mv, rs.chains[ci], rev, mesh_e, edge_ok)
        if not ok:
            return None
    wire.Closed(True)
    return wire


def _make_face_keep(surf: Geom_Plane, outer: TopoDS_Wire, inners: list, outward: bool):
    """BRep_Builder::MakeFace + Add keeps the wires' shared TShapes (J2)."""
    if surf is None or outer is None or outer.IsNull():
        return None
    try:
        builder = BRep_Builder()
        face = TopoDS_Face()
        builder.MakeFace(face, surf, _confusion())
        builder.Add(face, outer)
        for iw in inners:
            if iw is None or iw.IsNull():
                return None
            builder.Add(face, iw)
        return _set_face_outward(face, outward)
    except Standard_Failure:
        return None


def _wire_edges_in_order(wire: TopoDS_Wire) -> list:
    """BRepTools_WireExplorer order, falling back to raw iteration."""
    edges = []
    try:
        ex = BRepTools_WireExplorer(wire)
        while ex.More():
            edges.append(TopoDS.Edge_s(ex.Current()))
            ex.Next()
    except Standard_Failure:
        return []
    if not edges:
        from OCP.TopoDS import TopoDS_Iterator

        it = TopoDS_Iterator(wire)
        while it.More():
            if it.Value().ShapeType() == TopAbs_EDGE:
                edges.append(TopoDS.Edge_s(it.Value()))
            it.Next()
    return edges


def _make_wire_closed_from_edges(edges: list):
    """Reference addInners >6-chain retry: MakeWire + Closed(True)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire

    if not edges:
        return None
    try:
        mw = BRepBuilderAPI_MakeWire()
        for e in edges:
            mw.Add(e)
        if not mw.IsDone():
            return None
        w = mw.Wire()
        w.Closed(True)
    except Standard_Failure:
        return None
    return w


def _cyl_surface_for_region(region: Region) -> Geom_CylindricalSurface:
    """refit_build.cpp:1779. For a partial band the surface frame is rotated so the
    region's own u_min becomes u = 0, which keeps the face's parametric window away
    from the seam at +/-pi instead of straddling it."""
    ax = gp_Ax3(region.ax.Location(), region.ax.Direction(), region.ax.XDirection())
    if not region.closed360:
        u0 = region.u_min
        while u0 > math.pi:
            u0 -= 2.0 * math.pi
        while u0 <= -math.pi:
            u0 += 2.0 * math.pi
        if abs(u0) > 1e-14:
            ax.Rotate(gp_Ax1(ax.Location(), ax.Direction()), u0)
    return Geom_CylindricalSurface(gp_Cylinder(ax, region.radius))


def _build_cylindrical_face(
    region: Region, rs: RegionSet, mv: MeshView, geom, collapsed, mesh_e, edge_ok
):
    """A Geom_CylindricalSurface face bounded by the region's own boundary loops.

    Same loop machinery as the planar builder; the difference is that a cylinder is
    periodic in u, so the edges need parametric curves and OCCT will not infer them
    from 3D geometry alone. ShapeFix_Face builds the missing pcurves by projection,
    which is sound here precisely because every boundary vertex is already known to
    lie on the surface to within the mesh budget.
    """
    if region.max_vertex_dev > _mesh_tol_cap(mv, region):
        return None
    if not region.radius > 0.0 or region.ax is None:
        return None

    outer = None
    inners = []
    for lp in region.loops:
        if lp.role == LoopRole.OUTER:
            outer = lp
        elif lp.role == LoopRole.INNER:
            inners.append(lp)
    if outer is None:
        return None

    ow = _build_loop_wire(outer, rs, mv, geom, collapsed, mesh_e, edge_ok)
    if ow is None:
        return None

    cap = _mesh_tol_cap(mv, region)

    def attempt(outer_wire: TopoDS_Wire, force_fix_orientation: bool):
        surf = _cyl_surface_for_region(region)
        mf = BRepBuilderAPI_MakeFace(surf, outer_wire, True)
        if not mf.IsDone():
            return None
        for ip in inners:
            iw = _build_loop_wire(ip, rs, mv, geom, collapsed, mesh_e, edge_ok)
            if iw is None:
                return None
            mf.Add(iw)
        if not mf.IsDone():
            return None
        face = mf.Face()
        # Give every edge its pcurve on this surface first: without them BRepCheck
        # complains the wire is not on the surface, which is a missing-representation
        # problem rather than a geometric one.
        fix = ShapeFix_Face(face)
        if force_fix_orientation:
            fix.FixOrientationMode = 1
        fix.Perform()
        face = fix.Face()
        BRepLib.SameParameter_s(face, cap, True)
        out = _set_face_outward(face, region.outward_normal)
        if out.IsNull():
            return None
        if not _face_is_valid(out) and not _ensure_face_valid(out, cap):
            return None
        return out

    # A cylinder is periodic in u, so which way round the outer wire runs in (u, v)
    # is not fixed by the 3D mesh walk that produced it. The reference resolves this
    # the same way (refit_build.cpp:2166, 2206): force FixOrientation, and failing
    # that rebuild on the reversed wire, keeping whichever face checks out.
    try:
        for wire, forced in (
            (ow, False),
            (ow, True),
            (TopoDS.Wire_s(ow.Reversed()), False),
            (TopoDS.Wire_s(ow.Reversed()), True),
        ):
            face = attempt(wire, forced)
            if face is not None:
                return face
    except Standard_Failure:
        return None
    return None


def _try_seamed_360(region, rs, mv, verts, geom, collapsed, mesh_e, edge_ok, sew_tol):
    """refit_build.cpp:2599 trySeamed360 — one seamed full-2π cylindrical face
    bounded by the two cap circles and a seam generator. Returns the face or None."""
    cap_l = cap_h = None
    inners = []
    for lp in region.loops:
        if lp.role == LoopRole.CAP_LOW:
            cap_l = lp
        elif lp.role == LoopRole.CAP_HIGH:
            cap_h = lp
        elif lp.role == LoopRole.INNER:
            iw = _build_loop_wire(lp, rs, mv, geom, collapsed, mesh_e, edge_ok)
            if iw is None:
                return None
            inners.append(iw)
    if cap_l is None or cap_h is None or not cap_l.chain_idx or not cap_h.chain_idx:
        return None

    v_l = _vertex_closest_to_u_on_loop(mv, region, cap_l, rs, 0.0)
    v_h = _vertex_closest_to_u_on_loop(mv, region, cap_h, rs, 0.0)
    if v_l < 0 or v_h < 0 or v_l >= len(verts) or v_h >= len(verts):
        return None

    surf = Geom_CylindricalSurface(_as_cyl(region))
    circ_l = _cylinder_iso_circle(region, region.v_min)
    circ_h = _cylinder_iso_circle(region, region.v_max)
    ac_l = _Curve()
    ac_l.kind = _Curve.CIRC
    ac_l.circ = circ_l
    ac_h = _Curve()
    ac_h.kind = _Curve.CIRC
    ac_h.circ = circ_h
    snap_cap = _mesh_tol_cap(mv, region)
    _snap_vertex_to_curve(verts[v_l], ac_l, snap_cap)
    _snap_vertex_to_curve(verts[v_h], ac_h, snap_cap)

    def take_full_cap(ci, circ, v):
        if 0 <= ci < len(geom) and collapsed[ci]:
            if len(geom[ci]) != 1:
                return None
            e = TopoDS.Edge_s(geom[ci][0].Oriented(TopAbs_FORWARD))
            return e if _edge_spans_full_circle(e) else None
        e = _make_full_circle(circ, v)
        return None if e.IsNull() else e

    def bind_iso_pcurves(e_cap, v_iso, u0, e_seam, write_seam):
        b = BRep_Builder()
        c3 = BRep_Tool.Curve_s(e_cap, 0.0, 0.0)
        if c3 is None:
            f = u0
        else:
            f, _ = BRep_Tool.Range_s(e_cap)
        pc = Geom2d_Line(gp_Pnt2d(f, v_iso), gp_Dir2d(1.0, 0.0))
        b.UpdateEdge(e_cap, pc, surf, TopLoc_Location(), sew_tol)
        if not write_seam:
            return
        cs = BRep_Tool.Curve_s(e_seam, 0.0, 0.0)
        pc_s0 = Geom2d_Line(gp_Pnt2d(f, region.v_min), gp_Dir2d(0.0, 1.0))
        pc_s1 = Geom2d_Line(gp_Pnt2d(f + 2.0 * K_PI, region.v_min), gp_Dir2d(0.0, 1.0))
        b.UpdateEdge(e_seam, pc_s0, pc_s1, surf, TopLoc_Location(), sew_tol)
        if cs is not None:
            fs, ls = BRep_Tool.Range_s(e_seam)
            b.Range(e_seam, fs, ls)
        e_seam.Closed(False)

    def finish_face(got, publish_simple, ci_l, ci_h, e_l, e_h):
        if got.IsNull():
            return None
        _set_face_outward(got, region.outward_normal)
        _add_pcurves_on_face(got, sew_tol, True)
        if not _face_is_valid(got):
            try:
                sff = ShapeFix_Face(got)
                sff.FixMissingSeamMode = 1
                sff.FixAddNaturalBoundMode = 0
                sff.FixOrientationMode = 1
                sff.Perform()
                res = sff.Result()
                if res is None or res.IsNull():
                    res = sff.Face()
                n_f = 0
                g2 = None
                fx = TopExp_Explorer(res, TopAbs_FACE)
                while fx.More():
                    n_f += 1
                    g2 = TopoDS.Face_s(fx.Current())
                    fx.Next()
                if n_f == 1:
                    got = g2
            except Standard_Failure:
                pass
            _set_face_outward(got, region.outward_normal)
            _add_pcurves_on_face(got, sew_tol, True)
        if not _face_is_valid(got) and not _ensure_face_valid(got, _mesh_tol_cap(mv, region)):
            return None
        if publish_simple and 0 <= ci_l < len(geom) and 0 <= ci_h < len(geom):
            geom[ci_l] = [e_l]
            collapsed[ci_l] = 1
            geom[ci_h] = [e_h]
            collapsed[ci_h] = 1
        return got

    e_seam = TopoDS_Edge()
    try:
        lin = gp_Lin(
            gp_Pnt(
                float(mv.pts[int(mv.comp_vtx[v_l])][0]),
                float(mv.pts[int(mv.comp_vtx[v_l])][1]),
                float(mv.pts[int(mv.comp_vtx[v_l])][2]),
            ),
            region.ax.Direction(),
        )
        acs = _Curve()
        acs.kind = _Curve.LIN
        acs.lin = lin
        _snap_vertex_to_curve(verts[v_l], acs, snap_cap)
        _snap_vertex_to_curve(verts[v_h], acs, snap_cap)
        ms = BRepBuilderAPI_MakeEdge(lin, verts[v_l], verts[v_h])
        if not ms.IsDone():
            return None
        e_seam = ms.Edge()
    except Standard_Failure:
        return None

    ci_l0 = cap_l.chain_idx[0]
    ci_h0 = cap_h.chain_idx[0]
    simple = len(cap_l.chain_idx) == 1 and len(cap_h.chain_idx) == 1
    e_l = e_h = None
    if simple:
        e_l = take_full_cap(ci_l0, circ_l, verts[v_l])
        e_h = take_full_cap(ci_h0, circ_h, verts[v_h])
    simple = simple and e_l is not None and e_h is not None

    try:
        if simple:
            u0 = _azimuth_of(region, _pnt_of(verts[v_l]))
            bind_iso_pcurves(e_l, region.v_min, u0, e_seam, True)
            bind_iso_pcurves(e_h, region.v_max, u0, e_seam, False)
            b = BRep_Builder()
            w = TopoDS_Wire()
            b.MakeWire(w)
            b.Add(w, e_seam)
            b.Add(w, e_h)
            b.Add(w, TopoDS.Edge_s(e_seam.Reversed()))
            b.Add(w, TopoDS.Edge_s(e_l.Reversed()))
            w.Closed(True)
            mf = BRepBuilderAPI_MakeFace(surf, w, True)
            got = mf.Face() if mf.IsDone() else None
            if got is None or got.IsNull():
                box = BRepBuilderAPI_MakeFace(
                    _as_cyl(region), 0.0, 2.0 * K_PI, region.v_min, region.v_max
                )
                if not box.IsDone():
                    return None
                sff = ShapeFix_Face(box.Face())
                sff.FixMissingSeamMode = 1
                sff.FixAddNaturalBoundMode = 0
                sff.Add(w)
                for iw in inners:
                    sff.Add(iw)
                sff.Perform()
                res = sff.Result()
                if res is None or res.IsNull():
                    res = sff.Face()
                n_f = 0
                got = None
                fx = TopExp_Explorer(res, TopAbs_FACE)
                while fx.More():
                    n_f += 1
                    got = TopoDS.Face_s(fx.Current())
                    fx.Next()
                if n_f != 1:
                    return None
            return finish_face(got, True, ci_l0, ci_h0, e_l, e_h)

        w_l = _build_loop_wire(cap_l, rs, mv, geom, collapsed, mesh_e, edge_ok)
        w_h = _build_loop_wire(cap_h, rs, mv, geom, collapsed, mesh_e, edge_ok)
        if w_l is None or w_h is None:
            return None
        path_l = _wire_edges_in_order(w_l)
        path_h = _wire_edges_in_order(w_h)
        if not path_l or not path_h:
            return None
        if not _rotate_edges_to_vertex(path_h, verts[v_h]) or not _rotate_edges_to_vertex(
            path_l, verts[v_l]
        ):
            return None
        bw = BRep_Builder()
        ow = TopoDS_Wire()
        bw.MakeWire(ow)
        bw.Add(ow, e_seam)
        for e in path_h:
            bw.Add(ow, e)
        bw.Add(ow, TopoDS.Edge_s(e_seam.Reversed()))
        for i in range(len(path_l) - 1, -1, -1):
            bw.Add(ow, TopoDS.Edge_s(path_l[i].Reversed()))
        ow.Closed(True)
        _bind_cyl_pcurves(ow, surf, region, sew_tol)
        got = _make_face_keep(surf, ow, inners, region.outward_normal)
        if got is None:
            mf = BRepBuilderAPI_MakeFace(surf, ow, True)
            if not mf.IsDone():
                return None
            for iw in inners:
                mf.Add(iw)
            if not mf.IsDone():
                return None
            got = mf.Face()
        return finish_face(got, False, -1, -1, e_l, e_h)
    except Standard_Failure:
        return None


def _try_two_halves(region, mv, verts, cap_l, cap_h, rs, geom, collapsed, sew_tol, faces):
    """refit_build.cpp:2831 tryTwoHalves — F9 fallback when the seamed face cannot
    take a single 2π cap: build two half-cylinder faces instead."""
    if cap_l is None or cap_h is None:
        return False
    if not cap_l.chain_idx or not cap_h.chain_idx:
        return False
    c_l = cap_l.chain_idx[0]
    c_h = cap_h.chain_idx[0]
    if c_l < 0 or c_h < 0 or c_l >= len(rs.chains) or c_h >= len(rs.chains):
        return False

    v_l0 = _vertex_closest_to_u_on_loop(mv, region, cap_l, rs, 0.0)
    v_lpi = _vertex_closest_to_u_on_loop(mv, region, cap_l, rs, K_PI)
    v_h0 = _vertex_closest_to_u_on_loop(mv, region, cap_h, rs, 0.0)
    v_hpi = _vertex_closest_to_u_on_loop(mv, region, cap_h, rs, K_PI)
    if v_l0 < 0 or v_lpi < 0 or v_h0 < 0 or v_hpi < 0:
        return False
    if v_l0 == v_lpi or v_h0 == v_hpi:
        return False
    if abs(region.v_max - region.v_min) < _confusion():
        return False
    if (
        v_l0 >= len(verts)
        or v_lpi >= len(verts)
        or v_h0 >= len(verts)
        or v_hpi >= len(verts)
    ):
        return False

    circ_l = gp_Circ(
        gp_Ax2(
            region.ax.Location().Translated(gp_Vec(region.ax.Direction()).Multiplied(region.v_min)),
            region.ax.Direction(),
            region.ax.XDirection(),
        ),
        region.radius,
    )
    circ_h = gp_Circ(
        gp_Ax2(
            region.ax.Location().Translated(gp_Vec(region.ax.Direction()).Multiplied(region.v_max)),
            region.ax.Direction(),
            region.ax.XDirection(),
        ),
        region.radius,
    )

    mid_l0 = ElCLib.Value_s(K_PI * 0.5, circ_l)
    mid_l1 = ElCLib.Value_s(K_PI * 1.5, circ_l)
    mid_h0 = ElCLib.Value_s(K_PI * 0.5, circ_h)
    mid_h1 = ElCLib.Value_s(K_PI * 1.5, circ_h)

    a_l0 = _make_arc(circ_l, verts[v_l0], verts[v_lpi], mid_l0)
    a_l1 = _make_arc(circ_l, verts[v_lpi], verts[v_l0], mid_l1)
    a_h0 = _make_arc(circ_h, verts[v_h0], verts[v_hpi], mid_h0)
    a_h1 = _make_arc(circ_h, verts[v_hpi], verts[v_h0], mid_h1)
    try:
        m0 = BRepBuilderAPI_MakeEdge(verts[v_l0], verts[v_h0])
        mpi = BRepBuilderAPI_MakeEdge(verts[v_lpi], verts[v_hpi])
        if not m0.IsDone() or not mpi.IsDone():
            return False
        e0 = m0.Edge()
        e_pi = mpi.Edge()
    except Standard_Failure:
        return False
    if a_l0.IsNull() or a_l1.IsNull() or a_h0.IsNull() or a_h1.IsNull():
        return False

    def one_half(gen_a, arc_h, gen_b, arc_l):
        try:
            mw = BRepBuilderAPI_MakeWire()
            mw.Add(gen_a)
            mw.Add(arc_h)
            mw.Add(TopoDS.Edge_s(gen_b.Reversed()))
            mw.Add(TopoDS.Edge_s(arc_l.Reversed()))
            if not mw.IsDone():
                return None
            ow = mw.Wire()
            surf = Geom_CylindricalSurface(_as_cyl(region))
            _bind_cyl_pcurves(ow, surf, region, sew_tol)
            mf = BRepBuilderAPI_MakeFace(surf, ow, True)
            if not mf.IsDone():
                return None
            f = mf.Face()
            _set_face_outward(f, region.outward_normal)
            _add_pcurves_on_face(f, sew_tol, False)
            return None if f.IsNull() else f
        except Standard_Failure:
            return None

    f0 = one_half(e0, a_h0, e_pi, a_l0)
    f1 = one_half(e_pi, a_h1, e0, a_l1)

    def fix_half(f):
        if f is None or f.IsNull():
            return None
        if _face_is_valid(f):
            return f
        try:
            sff = ShapeFix_Face(f)
            sff.FixOrientationMode = 1
            sff.FixAddNaturalBoundMode = 0
            sff.FixMissingSeamMode = 0
            sff.Perform()
            res = sff.Result()
            if res is None or res.IsNull():
                res = sff.Face()
            fx = TopExp_Explorer(res, TopAbs_FACE)
            if fx.More():
                f = TopoDS.Face_s(fx.Current())
        except Standard_Failure:
            pass
        _set_face_outward(f, region.outward_normal)
        _ensure_face_valid(f, _mesh_tol_cap(mv, region))
        return f

    f0 = fix_half(f0)
    f1 = fix_half(f1)
    if f0 is None or f1 is None or not _face_is_valid(f0) or not _face_is_valid(f1):
        return False

    geom[c_l] = [a_l0, a_l1]
    geom[c_h] = [a_h0, a_h1]
    collapsed[c_l] = 1
    collapsed[c_h] = 1
    faces.append(f0)
    faces.append(f1)
    return True


def _build_planar_face(
    region: Region, rs: RegionSet, mv: MeshView, geom, collapsed, mesh_e, edge_ok
):
    # F4 budget pre-check (refit_build.cpp): a region whose own vertices sit further
    # from the fitted plane than the mesh tolerance budget allows is not representable
    # by that plane. Absorbing the residual into shared vertex/edge tolerances would
    # poison every adjacent face, so the region goes back to its triangles instead.
    # This is a fit residual against a mesh-derived threshold -- both measured, neither
    # tuned.
    if region.max_vertex_dev > _mesh_tol_cap(mv, region):
        return None
    outer = None
    inners = []
    for lp in region.loops:
        if lp.role == LoopRole.OUTER:
            outer = lp
        elif lp.role == LoopRole.INNER:
            inners.append(lp)
    if outer is None:
        return None
    ow = _build_loop_wire(outer, rs, mv, geom, collapsed, mesh_e, edge_ok)
    if ow is None:
        return None

    def add_inners(mf) -> bool:
        for ip in inners:
            iw = _build_loop_wire(ip, rs, mv, geom, collapsed, mesh_e, edge_ok)
            if iw is None:
                return False
            # Hole loops must bind shared Seamed360 cap circles with reversed
            # wire orientation (refit_build.cpp:2080).
            if len(ip.chain_idx) == 1:
                ci = ip.chain_idx[0]
                if (
                    0 <= ci < len(collapsed)
                    and collapsed[ci]
                    and 0 <= ci < len(geom)
                    and len(geom[ci]) == 1
                    and _edge_spans_full_circle(geom[ci][0])
                ):
                    iw = TopoDS.Wire_s(iw.Reversed())
            if len(ip.chain_idx) > 6:
                iw2 = _make_wire_closed_from_edges(_wire_edges_in_order(iw))
                if iw2 is not None:
                    iw = iw2
            mf.Add(iw)
        return bool(mf.IsDone())

    pln = _ax3_of(region)
    try:
        gpl = Geom_Plane(pln)
        inner_wires = []
        inners_ok = True
        for ip in inners:
            iw = _build_loop_wire(ip, rs, mv, geom, collapsed, mesh_e, edge_ok)
            if iw is None:
                inners_ok = False
                break
            # Hole loops must bind shared Seamed360 cap circles with reversed
            # wire orientation (refit_build.cpp:2114).
            if len(ip.chain_idx) == 1:
                ci = ip.chain_idx[0]
                if (
                    0 <= ci < len(collapsed)
                    and collapsed[ci]
                    and 0 <= ci < len(geom)
                    and len(geom[ci]) == 1
                    and _edge_spans_full_circle(geom[ci][0])
                ):
                    iw = TopoDS.Wire_s(iw.Reversed())
            inner_wires.append(iw)
        out_f = None
        if inners_ok:
            out_f = _make_face_keep(gpl, ow, inner_wires, region.outward_normal)
            if out_f is not None and (
                _face_is_valid(out_f) or _ensure_face_valid(out_f, _mesh_tol_cap(mv, region))
            ):
                if not out_f.IsNull():
                    return out_f
            out_f = None

        mf = BRepBuilderAPI_MakeFace(pln, ow, True)
        if not mf.IsDone():
            return None
        if not add_inners(mf):
            return None
        out_f = _set_face_outward(mf.Face(), region.outward_normal)
        if not _face_is_valid(out_f):
            # Mixed loops can be two endpoint-sharing paths rather than one
            # circulating walk. Reconnect by vertex identity (MakeWire) without
            # copying TShapes — s09.
            ow2 = _make_wire_closed_from_edges(_wire_edges_in_order(ow))
            if ow2 is not None:
                mf2 = BRepBuilderAPI_MakeFace(pln, ow2, True)
                if mf2.IsDone() and add_inners(mf2):
                    f2 = _set_face_outward(mf2.Face(), region.outward_normal)
                    if _face_is_valid(f2):
                        out_f = f2
                        ow = ow2
        if not _face_is_valid(out_f):
            # Outer-wire winding vs plane normal: retry reversed wire.
            try:
                mfR = BRepBuilderAPI_MakeFace(pln, TopoDS.Wire_s(ow.Reversed()), True)
                if mfR.IsDone():
                    for ip in inners:
                        iw = _build_loop_wire(ip, rs, mv, geom, collapsed, mesh_e, edge_ok)
                        if iw is None:
                            break
                        mfR.Add(iw)
                    if mfR.IsDone():
                        fR = _set_face_outward(mfR.Face(), region.outward_normal)
                        if _face_is_valid(fR):
                            out_f = fR
            except Standard_Failure:
                pass
        if not _face_is_valid(out_f) and inners:
            # Retry with inner wires flipped — imbrication/orientation of holes.
            try:
                mf2 = BRepBuilderAPI_MakeFace(pln, ow, True)
                if mf2.IsDone():
                    for ip in inners:
                        iw = _build_loop_wire(ip, rs, mv, geom, collapsed, mesh_e, edge_ok)
                        if iw is None:
                            break
                        mf2.Add(TopoDS.Wire_s(iw.Reversed()))
                    if mf2.IsDone():
                        f2 = _set_face_outward(mf2.Face(), not region.outward_normal)
                        if _face_is_valid(f2):
                            out_f = f2
            except Standard_Failure:
                pass
        if not _face_is_valid(out_f) and not inners:
            try:
                sff = ShapeFix_Face(out_f)
                sff.FixOrientationMode = True
                sff.FixAddNaturalBoundMode = False
                sff.FixMissingSeamMode = False
                sff.Perform()
                res = sff.Result()
                if res is None or res.IsNull():
                    res = sff.Face()
                fx = TopExp_Explorer(res, TopAbs_FACE)
                if fx.More():
                    out_f = TopoDS.Face_s(fx.Current())
            except Standard_Failure:
                pass
        # Prefer Region.outwardNormal, but keep the BRepCheck-valid orientation
        # if forcing the flag would leave Unorientable/BadOrientation (s09).
        want = _set_face_outward(out_f, region.outward_normal)
        other = _set_face_outward(out_f, not region.outward_normal)
        if _face_is_valid(want):
            out_f = want
        elif _face_is_valid(other):
            out_f = other
        # F4 (refit_build.cpp): tolerance may absorb the fit residual, but NEVER past
        # the mesh budget -- beyond it the plane is simply the wrong surface for these
        # triangles, and keeping it would poison every adjacent face's shared TShape.
        # Such a region is not representable analytically and goes back to its own
        # triangles via the explode ladder below.
        if out_f is None or out_f.IsNull():
            return None
        if not _face_is_valid(out_f) and not _ensure_face_valid(
            out_f, _mesh_tol_cap(mv, region)
        ):
            return None
    except Standard_Failure:
        return None
    return out_f


# --- faceted fallback pieces ------------------------------------------------------

def _make_facet(mv: MeshView, verts, mesh_e, edge_ok, k: int):
    if k >= mv.n_tri:
        return None
    gt = int(mv.comp_tris[k])
    if gt < 0:
        return None
    a, b, c = (mv.pts[int(mv.tris[gt, i])] for i in range(3))
    n = np.cross(b - a, c - a)
    mag = float(np.linalg.norm(n))
    l2 = max(float(np.dot(b - a, b - a)), float(np.dot(c - a, c - a)))
    if mag < 1e-12 or mag * mag < l2 * l2 * 1e-20:
        return None
    builder = BRep_Builder()
    wire = TopoDS_Wire()
    builder.MakeWire(wire)
    for s in range(3):
        eid = int(mv.tri_edges[k, s])
        if eid < 0 or eid >= len(mesh_e) or not edge_ok[eid]:
            return None
        fwd = bool((int(mv.tri_dirs[k, s]) >> 0) & 1)
        e = mesh_e[eid]
        builder.Add(wire, e if fwd else TopoDS.Edge_s(e.Reversed()))
    wire.Closed(True)
    try:
        pln = gp_Pln(
            gp_Pnt(float(a[0]), float(a[1]), float(a[2])),
            gp_Dir(float(n[0] / mag), float(n[1] / mag), float(n[2] / mag)),
        )
        face = TopoDS_Face()
        builder.MakeFace(face, Geom_Plane(pln), _confusion())
        builder.Add(face, wire)
    except Standard_Failure:
        return None
    return face


def _orient_face_walk(faces: list) -> None:
    """Adjacent faces must use opposite orientations of each shared TShape.
    Reverse() only, seeded from face 0 (J5: no shell-fix / sew / boolean)."""
    if len(faces) < 2:
        return
    acc: dict[int, list] = {}
    key_of = {}
    for fi, face in enumerate(faces):
        ex = TopExp_Explorer(face, TopAbs_EDGE)
        while ex.More():
            e = TopoDS.Edge_s(ex.Current())
            k = id(e.TShape()) if hasattr(e, "TShape") else None
            # IsSame equivalence via TShape pointer
            found = None
            for kk, ts in key_of.items():
                if e.IsSame(ts):
                    found = kk
                    break
            if found is None:
                found = len(key_of)
                key_of[found] = e
            acc.setdefault(found, []).append((fi, e.Orientation() == TopAbs_FORWARD))
            ex.Next()
    pairs = []
    for recs in acc.values():
        if len(recs) != 2:
            continue
        if recs[0][0] == recs[1][0]:
            continue  # seam (same face twice)
        pairs.append((recs[0][0], recs[1][0], recs[0][1], recs[1][1]))

    seen = [0] * len(faces)
    queue = [0]
    seen[0] = 1

    def flip_face(fj: int) -> None:
        faces[fj] = TopoDS.Face_s(faces[fj].Reversed())
        for i, p in enumerate(pairs):
            a, b, af, bf = p
            if a == fj:
                pairs[i] = (a, b, not af, bf)
            elif b == fj:
                pairs[i] = (a, b, af, not bf)

    qi = 0
    while qi < len(queue):
        fi = queue[qi]
        for p in pairs:
            a, b, af, bf = p
            fj, agree = -1, False
            if a == fi:
                fj, agree = b, af == bf
            elif b == fi:
                fj, agree = a, af == bf
            if fj < 0 or seen[fj]:
                continue
            seen[fj] = 1
            queue.append(fj)
            if agree:
                flip_face(fj)
        if qi + 1 == len(queue):
            for k in range(len(faces)):
                if not seen[k]:
                    seen[k] = 1
                    queue.append(k)
                    break
        qi += 1


# --- entry point ------------------------------------------------------------------

def _region_set_consistent(mv: MeshView, rs: RegionSet, verts) -> bool:
    if mv.n_tri == 0 or len(verts) < mv.n_vtx:
        return False
    for t in range(mv.n_tri):
        if int(mv.comp_tris[t]) < 0:
            return False
        for s in range(3):
            e = int(mv.tri_edges[t, s])
            if e < 0 or e >= mv.n_edge:
                return False
    for e in range(mv.n_edge):
        a, b = mv.comp_edges[e]
        if a < 0 or a >= mv.n_vtx or b < 0 or b >= mv.n_vtx:
            return False

    def known_region(rid: int) -> bool:
        return rid < 0 or any(r.id == rid for r in rs.regions)

    for r in rs.regions:
        if r.id < 0:
            return False
        for t in r.tris:
            if t < 0 or t >= mv.n_tri:
                return False
        for lp in r.loops:
            if len(lp.chain_idx) != len(lp.reversed):
                return False
            for ci in lp.chain_idx:
                if ci < 0 or ci >= len(rs.chains):
                    return False
    for ch in rs.chains:
        if not known_region(ch.reg_a) or not known_region(ch.reg_b):
            return False
        for e in ch.mesh_edges:
            if e < 0 or e >= mv.n_edge:
                return False
        for v in ch.mesh_verts:
            if v < 0 or v >= mv.n_vtx:
                return False
    for k in range(min(mv.n_tri, len(rs.tri_region))):
        if not known_region(rs.tri_region[k]):
            return False
    return True


def build_faces(mv: MeshView, rs: RegionSet, verts: list):
    """P2 entry point. Returns (ok, faces); ok=False => caller reverts to the
    faceted build (R2). Planar subset of the reference buildFaces."""
    faces_out: list = []
    try:
        if mv.n_tri == 0:
            return False, faces_out
        if len(verts) < mv.n_vtx:
            return False, faces_out
        if not _region_set_consistent(mv, rs, verts):
            for r in rs.regions:
                r.reject = Reject.CHAIN_UNSTABLE
                r.built_as = BuiltAs.NOT_BUILT
            return False, faces_out

        # Stage P (prismatic rebuild) is M5 — decline byte-identically.
        sew_tol = mv.sew_tol if mv.sew_tol > 0.0 else _confusion()
        was_closed = _mesh_component_closed(mv)

        mesh_e: list = [None] * mv.n_edge
        edge_ok = [0] * mv.n_edge

        def rebuild_mesh_edges() -> None:
            for i in range(mv.n_edge):
                mesh_e[i] = None
                edge_ok[i] = 0
            for i in range(mv.n_edge):
                a, b = mv.comp_edges[i]
                if a < 0 or b < 0 or a >= len(verts) or b >= len(verts):
                    continue
                try:
                    me = BRepBuilderAPI_MakeEdge(verts[a], verts[b])
                    if me.IsDone():
                        mesh_e[i] = me.Edge()
                        edge_ok[i] = 1
                except Standard_Failure:
                    continue

        rebuild_mesh_edges()

        def restore_shared() -> None:
            # Fresh vertex TShapes so a discarded analytic attempt's fat
            # tolerances never leak into the next round (adjudication F6).
            builder = BRep_Builder()
            for i in range(len(verts)):
                p = mv.pts[int(mv.comp_vtx[i])]
                nv = TopoDS_Vertex()
                builder.MakeVertex(nv, gp_Pnt(float(p[0]), float(p[1]), float(p[2])), _confusion())
                verts[i] = nv
            rebuild_mesh_edges()

        collapsed = [0] * len(rs.chains)
        geom: list = [[] for _ in rs.chains]
        chain_edge_fail = [0] * len(rs.chains)
        recover_pass = 0
        rounds = 0
        exploded = [0] * len(rs.regions)

        def region_exploded(rid: int) -> bool:
            return 0 <= rid < len(exploded) and exploded[rid] != 0

        def rebuild_collapsed() -> None:
            diag_collapse = os.environ.get("MESH2STEP_COLLAPSE_DIAG", "") not in ("", "0")
            n_mix = n_none = n_fail = n_ok = 0
            for ci in range(len(rs.chains)):
                collapsed[ci] = 0
                geom[ci] = []
                chain_edge_fail[ci] = 0
            for ci in range(len(rs.chains)):
                ch = rs.chains[ci]
                a = _region_by_id(rs, ch.reg_a)
                b = _region_by_id(rs, ch.reg_b)
                if a is not None and region_exploded(a.id):
                    a = None
                if b is not None and region_exploded(b.id):
                    b = None
                if not (_is_analytic(a) and _is_analytic(b)):
                    # mixed analytic|faceted, or island|island: polyline verbatim
                    n_mix += 1
                    if (a is not None and b is None and _is_analytic(a)) or (
                        b is not None and a is None and _is_analytic(b)
                    ):
                        an = a if _is_analytic(a) else b
                        for eid in ch.mesh_edges:
                            if eid < 0 or eid >= mv.n_edge or not edge_ok[eid]:
                                continue
                            ea, eb = mv.comp_edges[eid]
                            d = _mixed_edge_deviation(verts[ea], verts[eb], an)
                            rs.stats.max_edge_tol = max(rs.stats.max_edge_tol, d)
                    continue

                # analytic | analytic (plane|plane, plane|cylinder, cylinder|cylinder)
                curve = _intersect_surfaces(a, b, mv, ch, sew_tol)
                if curve.kind == _Curve.NONE:
                    n_none += 1
                    if (
                        (a.type == SurfType.PLANE and b.type == SurfType.PLANE)
                        or (a.type == SurfType.PLANE and b.type == SurfType.CYLINDER)
                        or (a.type == SurfType.CYLINDER and b.type == SurfType.PLANE)
                    ):
                        chain_edge_fail[ci] = 1
                    continue

                full = ch.closed_loop
                if ch.closed_loop:
                    cyl = a if a.type == SurfType.CYLINDER else (
                        b if b.type == SurfType.CYLINDER else None
                    )
                    if cyl is not None:
                        ia = ib = _seam_vertex_of(mv, cyl, ch)
                    else:
                        ia = ib = ch.mesh_verts[0]
                else:
                    if len(ch.mesh_verts) < 2:
                        continue
                    ia, ib = ch.mesh_verts[0], ch.mesh_verts[-1]
                if ia < 0 or ib < 0 or ia >= len(verts) or ib >= len(verts):
                    continue
                cyl_r = a if a.type == SurfType.CYLINDER else (
                    b if b.type == SurfType.CYLINDER else None
                )
                pln_r = a if a.type == SurfType.PLANE else (
                    b if b.type == SurfType.PLANE else None
                )
                # F1: closed360 cap circles must be V-isos of the fitted cylinder
                # (refit_build.cpp:3842-3849).
                if curve.kind == _Curve.CIRC and cyl_r is not None:
                    v = gp_Vec(cyl_r.ax.Location(), curve.circ.Location()).Dot(
                        gp_Vec(cyl_r.ax.Direction())
                    )
                    if pln_r is not None and _plane_perp_cylinder(pln_r, cyl_r):
                        v = _plane_v_on_cylinder(pln_r, cyl_r)
                    curve.circ = _cylinder_iso_circle(cyl_r, v)

                snap_cap = _analytic_snap_cap(mv, a, b)
                if a.type == SurfType.PLANE and b.type == SurfType.PLANE:
                    d_a = _curve_residual(curve, _pnt_of(verts[ia]))
                    d_b = _curve_residual(curve, _pnt_of(verts[ib]))
                    sew = mv.sew_tol if mv.sew_tol > 0.0 else _confusion()
                    accept_cap = max(sew * 50.0, 1.0)
                    d_pair = max(
                        d_a if math.isfinite(d_a) else 0.0,
                        d_b if math.isfinite(d_b) else 0.0,
                    )
                    snap_cap = max(snap_cap, min(d_pair, accept_cap))
                _snap_vertex_to_curve(verts[ia], curve, snap_cap)
                _snap_vertex_to_curve(verts[ib], curve, snap_cap)

                e = None
                if full and curve.kind == _Curve.CIRC:
                    # Plane inner wires around Seamed360 holes: MakeEdge(circ,V,V)
                    # fails on coarse loops — use the F1 iso-circle + makeFullCircle
                    # ladder (refit_build.cpp:3887-3893).
                    e = _make_full_circle(curve.circ, verts[ia])
                    if e is None or e.IsNull():
                        e = _make_edge_from_curve(curve, verts[ia], verts[ib], full)
                else:
                    e = _make_edge_from_curve(curve, verts[ia], verts[ib], full)
                if e is None or e.IsNull():
                    identic = ia == ib or (
                        _pnt_of(verts[ia]).Distance(_pnt_of(verts[ib])) <= _confusion()
                    )
                    if not identic:
                        chain_edge_fail[ci] = 1
                        n_fail += 1
                    continue
                if full and curve.kind == _Curve.CIRC and len(ch.mesh_verts) >= 2:
                    p0 = mv.pts[int(mv.comp_vtx[ch.mesh_verts[0]])]
                    p1 = mv.pts[int(mv.comp_vtx[ch.mesh_verts[1]])]
                    t0 = ElCLib.Parameter_s(
                        curve.circ, gp_Pnt(float(p0[0]), float(p0[1]), float(p0[2]))
                    )
                    t1 = ElCLib.Parameter_s(
                        curve.circ, gp_Pnt(float(p1[0]), float(p1[1]), float(p1[2]))
                    )
                    dt = t1 - t0
                    while dt < 0.0:
                        dt += 2.0 * K_PI
                    if dt > K_PI:
                        e = TopoDS.Edge_s(e.Reversed())
                geom[ci] = [e]
                collapsed[ci] = 1
                n_ok += 1

            if diag_collapse:
                print(
                    f"DIAG_COLLAPSE mix={n_mix} none={n_none} fail={n_fail} ok={n_ok} "
                    f"total={len(rs.chains)} recover={recover_pass} rounds={rounds}",
                    file=sys.stderr,
                )

        def build_one_region(r: Region, acc: list) -> bool:
            if region_exploded(r.id):
                return True
            r.built_as = BuiltAs.NOT_BUILT
            if r.type in (SurfType.CONE, SurfType.SPHERE, SurfType.TORUS):
                r.reject = (
                    Reject.CONE_NYI
                    if r.type == SurfType.CONE
                    else Reject.SPHERE_NYI
                    if r.type == SurfType.SPHERE
                    else Reject.TORUS_NYI
                )
                return False
            if r.closed360 and r.type == SurfType.CYLINDER:
                f360 = _try_seamed_360(r, rs, mv, verts, geom, collapsed, mesh_e, edge_ok, sew_tol)
                if f360 is not None and _cylinder_post_fit_ok(r, mv, rs):
                    r.built_as = BuiltAs.SEAMED360
                    acc.append(f360)
                    return True
                cap_l = cap_h = None
                for lp in r.loops:
                    if lp.role == LoopRole.CAP_LOW:
                        cap_l = lp
                    if lp.role == LoopRole.CAP_HIGH:
                        cap_h = lp
                halves: list = []
                if (
                    _try_two_halves(
                        r, mv, verts, cap_l, cap_h, rs, geom, collapsed, sew_tol, halves
                    )
                    and _cylinder_post_fit_ok(r, mv, rs)
                ):
                    all_ok = True
                    for hf in halves:
                        if not _ensure_face_valid(hf, _mesh_tol_cap(mv, r)):
                            all_ok = False
                    if all_ok:
                        r.built_as = BuiltAs.TWO_HALVES
                        acc.extend(halves)
                        return True
                return False
            if r.type == SurfType.CYLINDER:
                f = _build_cylindrical_face(r, rs, mv, geom, collapsed, mesh_e, edge_ok)
                if f is None:
                    return False
                r.built_as = BuiltAs.SINGLE
                acc.append(f)
                return True
            if r.type == SurfType.PLANE:
                f = _build_planar_face(r, rs, mv, geom, collapsed, mesh_e, edge_ok)
                if f is None:
                    return False
                r.built_as = BuiltAs.SINGLE
                acc.append(f)
                return True
            return False

        def uncollapse_region_chains(rid: int) -> None:
            for ci in range(len(rs.chains)):
                ch = rs.chains[ci]
                if ch.reg_a != rid and ch.reg_b != rid:
                    continue
                collapsed[ci] = 0
                geom[ci] = []

        def explode_region(rid: int) -> None:
            if rid < 0 or rid >= len(exploded) or exploded[rid]:
                return
            exploded[rid] = 1
            rr = _region_by_id(rs, rid)
            if rr is not None:
                rr.built_as = BuiltAs.EXPLODED_TO_FACETS
                rr.reject = Reject.FACE_BUILD_FAILED
            uncollapse_region_chains(rid)
            restore_shared()

        def explode_all() -> bool:
            any_ = False
            for r in rs.regions:
                if region_exploded(r.id):
                    continue
                explode_region(r.id)
                any_ = True
            return any_

        while True:  # try_rebuild: J6 decline paths re-enter here
            rounds = 0
            unstable = False
            built: list = []
            k_max_rounds = 2
            while True:
                rebuild_collapsed()
                built = []
                any_fail = False
                failed_ids = []
                build_order = sorted(range(len(rs.regions)), key=lambda i: rs.regions[i].id)
                for oi in build_order:
                    r = rs.regions[oi]
                    if region_exploded(r.id):
                        continue
                    acc = []
                    if not build_one_region(r, acc):
                        any_fail = True
                        failed_ids.append(r.id)
                        r.reject = Reject.FACE_BUILD_FAILED
                        r.built_as = BuiltAs.NOT_BUILT
                    else:
                        built.extend(acc)
                if not any_fail:
                    break
                failed_ids = sorted(set(failed_ids))
                for rid in failed_ids:
                    explode_region(rid)
                rounds += 1
                if rounds > k_max_rounds:
                    rebuild_collapsed()
                    built = []
                    any_fail = False
                    for oi in build_order:
                        r = rs.regions[oi]
                        if region_exploded(r.id):
                            continue
                        acc = []
                        if not build_one_region(r, acc):
                            any_fail = True
                            r.reject = Reject.FACE_BUILD_FAILED
                            r.built_as = BuiltAs.NOT_BUILT
                        else:
                            built.extend(acc)
                    if any_fail:
                        unstable = True
                    break

            if unstable:
                for r in rs.regions:
                    if r.reject == Reject.FACE_BUILD_FAILED:
                        r.reject = Reject.CHAIN_UNSTABLE
                restore_shared()
                explode_all()
                built = []
                for k in range(mv.n_tri):
                    f = _make_facet(mv, verts, mesh_e, edge_ok, k)
                    if f is not None and not f.IsNull():
                        built.append(f)
                if not built:
                    return False, []
                # Fall through to shell assembly of the faceted baseline.

            # Facet islands + exploded-region triangles.
            if not unstable:
                for k in range(mv.n_tri):
                    rid = rs.tri_region[k] if k < len(rs.tri_region) else -1
                    iid = rs.tri_island[k] if k < len(rs.tri_island) else -1
                    exp = rid >= 0 and region_exploded(rid)
                    if iid < 0 and not exp:
                        continue
                    f = _make_facet(mv, verts, mesh_e, edge_ok, k)
                    if f is not None and not f.IsNull():
                        _ensure_face_valid(f, _mesh_tol_cap(mv, None))
                        built.append(f)

            if not built:
                return False, []

            _orient_face_walk(built)

            # J4: assemble a shell and SameParameter(forced).
            builder = BRep_Builder()
            shell = TopoDS_Shell()
            builder.MakeShell(shell)
            for f in built:
                builder.Add(shell, f)
            sp_cap = _mesh_tol_cap(mv, None)
            for rg in rs.regions:
                sp_cap = max(sp_cap, _mesh_tol_cap(mv, rg))
            sp_cap = max(sp_cap, 0.05 * (mv.diag if mv.diag > 0.0 else 1.0))
            sp_cap = max(sp_cap, 25.0)
            try:
                BRepLib.SameParameter_s(shell, min(sew_tol, sp_cap), True)
            except Standard_Failure:
                return False, []

            # J6: targeted heals are M3-M5; the deferred edge-failure R1 and the
            # full explode ladder are the planar-path equivalents.
            sh_closed = bool(BRep_Tool.IsClosed_s(shell))
            shell.Closed(sh_closed)
            if was_closed and not sh_closed:
                did = False
                if recover_pass < 1:
                    edge_fail_ids = []
                    for ci in range(len(rs.chains)):
                        if not chain_edge_fail[ci]:
                            continue
                        for rid in (rs.chains[ci].reg_a, rs.chains[ci].reg_b):
                            if rid < 0 or region_exploded(rid):
                                continue
                            if rid not in edge_fail_ids:
                                edge_fail_ids.append(rid)
                    for rid in sorted(edge_fail_ids):
                        explode_region(rid)
                        did = True
                if did:
                    recover_pass += 1
                    continue
                if recover_pass < 2 and explode_all():
                    recover_pass += 1
                    continue
                return False, []

            sh_valid = _shell_is_valid(shell)
            if sh_closed and not sh_valid:
                # Cascade ladder (closed-but-invalid) is M3-M5: decline here.
                return False, []

            return True, built
    except Standard_Failure:
        return False, []
    except Exception:  # noqa: BLE001 - port of the reference's catch-all guard
        import traceback
        traceback.print_exc()
        return False, []
