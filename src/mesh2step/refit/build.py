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

import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepLib import BRepLib
from OCP.BRepTools import BRepTools_WireExplorer
from OCP.ElCLib import ElCLib
from OCP.Geom import Geom_CylindricalSurface, Geom_Line, Geom_Plane
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.gp import gp_Ax1, gp_Ax3, gp_Cylinder, gp_Dir, gp_Lin, gp_Pln, gp_Pnt, gp_Vec
from OCP.IntAna import IntAna_QuadQuadGeo, IntAna_ResultType
from OCP.Precision import Precision
from OCP.ShapeFix import ShapeFix_Face
from OCP.Standard import Standard_Failure
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import (
    TopoDS,
    TopoDS_Face,
    TopoDS_Shell,
    TopoDS_Vertex,
    TopoDS_Wire,
)

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
    __slots__ = ("kind", "lin")

    NONE, LIN = 0, 1

    def __init__(self):
        self.kind = _Curve.NONE
        self.lin: gp_Lin | None = None


def _curve_residual(curve: _Curve, p: gp_Pnt) -> float:
    try:
        if curve.kind == _Curve.LIN and curve.lin is not None:
            return curve.lin.Distance(p)
    except Standard_Failure:
        return 1e300
    return 1e300


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
    n = iq.NbSolutions()
    if ty in (IntAna_ResultType.IntAna_Line, IntAna_ResultType.IntAna_PointAndCircle):
        for i in range(1, n + 1):
            cand = _Curve()
            try:
                cand.kind = _Curve.LIN
                cand.lin = iq.Line(i)
                r = _chain_residual(cand, mv, chain)
                if r < best_r:
                    best_r = r
                    best = cand
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
    """Plane|plane intersection (the only analytic|analytic class in M2)."""
    tol_ang = Precision.Angular_s()
    tol = max(sew_tol, _confusion())
    try:
        iq = IntAna_QuadQuadGeo(_ax3_of(a), _ax3_of(b), tol_ang, tol)
        accept_r = _int_ana_accept_residual(mv, chain, sew_tol, a, b)
        return _pick_int_ana(iq, mv, chain, sew_tol, accept_r)
    except Standard_Failure:
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
            for ci in range(len(rs.chains)):
                collapsed[ci] = 0
                geom[ci] = []
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
                # analytic | analytic (plane|plane in M2; plane|cyl etc are M3+)
                curve = _Curve()
                if a.type == SurfType.PLANE and b.type == SurfType.PLANE:
                    curve = _intersect_surfaces(a, b, mv, ch, sew_tol)
                if curve.kind == _Curve.NONE:
                    if a.type == SurfType.PLANE and b.type == SurfType.PLANE:
                        chain_edge_fail[ci] = 1
                    continue

                full = ch.closed_loop
                if ch.closed_loop:
                    ia = ib = ch.mesh_verts[0]
                else:
                    if len(ch.mesh_verts) < 2:
                        continue
                    ia, ib = ch.mesh_verts[0], ch.mesh_verts[-1]
                if ia < 0 or ib < 0 or ia >= len(verts) or ib >= len(verts):
                    continue
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
                e = _make_edge_from_curve(curve, verts[ia], verts[ib], full)
                if e is None or e.IsNull():
                    identic = ia == ib or (
                        _pnt_of(verts[ia]).Distance(_pnt_of(verts[ib])) <= _confusion()
                    )
                    if not identic:
                        chain_edge_fail[ci] = 1
                    continue
                geom[ci] = [e]
                collapsed[ci] = 1

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
